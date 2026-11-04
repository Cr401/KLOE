"""파일 핸드오프: 결과 가져오기 + 검증, 실패 줄 재대기, 오래된 claimed 되돌리기."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from leo.queue.export import read_jsonl, stage_dir, write_batch, write_jsonl_atomic
from leo.schema import RESULT_MODELS
from leo.verify import verify

MAX_ATTEMPTS = 2  # 처음 1번 + 실패 줄 재시도 1번


@dataclass
class IngestReport:
    stage: str
    batch: str
    accepted: list[tuple[dict, object]] = field(default_factory=list)  # (job, 검증된 결과 모델)
    failed: list[dict] = field(default_factory=list)  # {"job_id", "reasons", "line"}
    missing: list[str] = field(default_factory=list)  # 결과가 없는 job_id
    requeued: Path | None = None

    @property
    def extractor(self) -> str | None:
        return next((getattr(r, "extractor", None) for _, r in self.accepted), None)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.missing


def claim(work_dir: Path, stage: str, name: str) -> Path:
    """에이전트가 하는 일과 같다: queue -> claimed rename. 테스트와 수동 실행용."""
    src = stage_dir(work_dir, "queue", stage) / name
    dst = stage_dir(work_dir, "claimed", stage) / name
    src.rename(dst)
    os.utime(dst)  # rename은 mtime을 보존하므로, stale 판단 기준을 가져간 시각으로 맞춘다
    return dst


def ready_batches(work_dir: Path, stage: str) -> list[str]:
    """claimed에 원본이 있고 out에 결과가 도착한 배치."""
    out = stage_dir(work_dir, "out", stage)
    claimed = stage_dir(work_dir, "claimed", stage)
    return sorted(p.name for p in out.glob("batch-*.jsonl") if (claimed / p.name).exists())


def _parse_result_lines(path: Path) -> list[tuple[str | None, dict | None, str]]:
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            rows.append((obj.get("job_id") if isinstance(obj, dict) else None, obj, raw))
        except json.JSONDecodeError:
            rows.append((None, None, raw))
    return rows


def ingest_batch(work_dir: Path, stage: str, name: str) -> IngestReport:
    model = RESULT_MODELS[stage]
    claimed_path = stage_dir(work_dir, "claimed", stage) / name
    out_path = stage_dir(work_dir, "out", stage) / name
    jobs = {j["job_id"]: j for j in read_jsonl(claimed_path)}
    report = IngestReport(stage=stage, batch=name)
    seen: set[str] = set()

    for jid, obj, raw in _parse_result_lines(out_path):
        if obj is None:
            report.failed.append({"job_id": None, "reasons": ["JSON 파싱 실패"], "line": raw})
            continue
        if jid not in jobs:
            report.failed.append({"job_id": jid, "reasons": ["배치에 없는 job_id"], "line": raw})
            continue
        if jid in seen:
            report.failed.append({"job_id": jid, "reasons": ["job_id 중복"], "line": raw})
            continue
        seen.add(jid)
        try:
            result = model.model_validate(obj)
        except ValidationError as e:
            reasons = [f"스키마: {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
            report.failed.append({"job_id": jid, "reasons": reasons, "line": raw})
            continue
        reasons = verify(result, jobs[jid])
        if reasons:
            report.failed.append({"job_id": jid, "reasons": reasons, "line": raw})
        else:
            report.accepted.append((jobs[jid], result))

    report.missing = [jid for jid in jobs if jid not in seen]
    _finish(work_dir, stage, name, claimed_path, out_path, jobs, report)
    return report


def _finish(work_dir, stage, name, claimed_path, out_path, jobs, report: IngestReport) -> None:
    done = stage_dir(work_dir, "done", stage)
    stem = name.removesuffix(".jsonl")
    if report.failed or report.missing:
        failed_dir = stage_dir(work_dir, "failed", stage)
        failed_lines = [json.loads(f["line"]) if _is_json(f["line"]) else {"raw": f["line"]} for f in report.failed]
        write_jsonl_atomic(failed_dir / name, failed_lines)
        reasons = {
            "batch": name,
            "failed": [{"job_id": f["job_id"], "reasons": f["reasons"]} for f in report.failed],
            "missing": report.missing,
        }
        (failed_dir / f"{stem}.reason.json").write_text(json.dumps(reasons, ensure_ascii=False, indent=2), encoding="utf-8")
        retry_ids = [f["job_id"] for f in report.failed if f["job_id"] in jobs] + report.missing
        retry = [{**jobs[j], "attempt": jobs[j].get("attempt", 0) + 1} for j in retry_ids]
        retry = [j for j in retry if j["attempt"] < MAX_ATTEMPTS]
        report.requeued = write_batch(work_dir, stage, retry)
    claimed_path.rename(done / name)
    out_path.rename(done / f"{stem}.out.jsonl")


def _is_json(raw: str) -> bool:
    try:
        json.loads(raw)
        return True
    except json.JSONDecodeError:
        return False


def requeue_stale(work_dir: Path, stage: str, older_than_s: float, now: float | None = None) -> list[str]:
    """결과 없이 claimed에 오래 머문 배치를 queue로 되돌린다 (`leo requeue --stale 6h`)."""
    now = time.time() if now is None else now
    claimed = stage_dir(work_dir, "claimed", stage)
    out = stage_dir(work_dir, "out", stage)
    queue = stage_dir(work_dir, "queue", stage)
    moved = []
    for p in sorted(claimed.glob("batch-*.jsonl")):
        if (out / p.name).exists():
            continue
        if now - p.stat().st_mtime >= older_than_s:
            p.rename(queue / p.name)
            moved.append(p.name)
    return moved


def parse_duration(text: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    text = text.strip().lower()
    if text and text[-1] in units:
        return float(text[:-1]) * units[text[-1]]
    return float(text)
