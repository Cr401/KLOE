"""파일 핸드오프: 배치 내보내기 (설계 1.2절).

work/
  queue/{stage}/batch-000123.jsonl     L0가 만든 배치 (원문 포함)
  claimed/{stage}/batch-000123.jsonl   에이전트가 rename으로 가져감 (= 잠금)
  out/{stage}/batch-000123.jsonl       에이전트 결과
  done/{stage}/...                     가져오기 완료
  failed/{stage}/...                   검증 실패 줄 + 사유
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

STAGES = ("classify", "extract", "program", "synthesize", "report")
# 단계마다 job이 가리키는 대상의 키. program 단계는 조문이 아니라 공고 판(program_version)을 다룬다.
TARGET_KEY = {"program": "version_id"}
STATES = ("queue", "claimed", "out", "done", "failed")
_BATCH_RE = re.compile(r"^batch-(\d{6})\.jsonl$")


def stage_dir(work_dir: Path, state: str, stage: str) -> Path:
    if state not in STATES or stage not in STAGES:
        raise ValueError(f"잘못된 state/stage: {state}/{stage}")
    d = Path(work_dir) / state / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def batch_name(number: int) -> str:
    return f"batch-{number:06d}.jsonl"


def job_id(stage: str, provision_id: int, text_hash: str) -> str:
    return f"{stage}:{provision_id}:{text_hash[:12]}"


def make_job(
    stage: str,
    *,
    provision_id: int,
    text_hash: str,
    law_name: str,
    article_key: str,
    effective_from: str,
    text: str,
    delegations: list[dict] | None = None,
    attempt: int = 0,
) -> dict:
    return {
        "job_id": job_id(stage, provision_id, text_hash),
        "provision_id": provision_id,
        "text_hash": text_hash,
        "law_name": law_name,
        "article_key": article_key,
        "effective_from": effective_from,
        "text": text,
        "delegations": delegations or [],
        "attempt": attempt,
    }


def make_program_job(*, version_id: int, text_hash: str, source: str, title: str, apply_end: str | None,
                     text: str, attempt: int = 0) -> dict:
    return {
        "job_id": job_id("program", version_id, text_hash),
        "version_id": version_id,
        "text_hash": text_hash,
        "source": source,
        "title": title,
        "apply_end": apply_end,
        "text": text,
        "attempt": attempt,
    }


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl_atomic(path: Path, rows: Iterable[dict]) -> Path:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.rename(path)
    return path


def next_batch_number(work_dir: Path, stage: str) -> int:
    biggest = 0
    for state in STATES:
        for p in stage_dir(work_dir, state, stage).iterdir():
            m = _BATCH_RE.match(p.name)
            if m:
                biggest = max(biggest, int(m.group(1)))
    return biggest + 1


def write_batch(work_dir: Path, stage: str, jobs: list[dict]) -> Path | None:
    if not jobs:
        return None
    path = stage_dir(work_dir, "queue", stage) / batch_name(next_batch_number(work_dir, stage))
    return write_jsonl_atomic(path, jobs)


def in_flight_provision_ids(work_dir: Path, stage: str) -> set[int]:
    """아직 가져오지 않은 배치(queue, claimed)에 들어 있는 조문(program 단계는 공고 판). 중복 내보내기를 막는다."""
    key = TARGET_KEY.get(stage, "provision_id")
    ids: set[int] = set()
    for state in ("queue", "claimed"):
        for p in stage_dir(work_dir, state, stage).glob("batch-*.jsonl"):
            ids.update(int(j[key]) for j in read_jsonl(p))
    return ids


def chunk(jobs: list[dict], size: int) -> list[list[dict]]:
    return [jobs[i : i + size] for i in range(0, len(jobs), size)]
