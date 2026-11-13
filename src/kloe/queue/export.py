"""파일 핸드오프: 배치 내보내기 (설계 1.2절).

work/
  queue/{stage}/batch-000123.jsonl     L0가 만든 배치 (원문 포함)
  claimed/{stage}/batch-000123.jsonl   에이전트가 rename으로 가져감 (= 잠금)
  out/{stage}/batch-000123.jsonl       에이전트 결과
  done/{stage}/...                     가져오기 완료
  failed/{stage}/...                   검증 실패 줄 + 사유
"""

from __future__ import annotations

import fcntl
import json
import re
from contextlib import contextmanager
from collections.abc import Iterable
from pathlib import Path

STAGES = ("classify", "extract", "program", "audit", "ideate", "synthesize", "report")
# 단계마다 job이 가리키는 대상의 키. program 단계는 조문이 아니라 공고 판(program_version)을 다룬다.
TARGET_KEY = {"program": "version_id", "audit": "fact_id"}
STATES = ("queue", "claimed", "out", "done", "failed")
DROPPED = "dropped.jsonl"  # 재시도까지 실패한 job
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


def make_audit_job(*, fact_id: int, text_hash: str, law_name: str, article_key: str, text: str,
                   fact: dict, attempt: int = 0) -> dict:
    return {
        "job_id": job_id("audit", fact_id, text_hash),
        "fact_id": fact_id,
        "text_hash": text_hash,
        "law_name": law_name,
        "article_key": article_key,
        "text": text,
        "fact": fact,
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


def next_batch_number(work_dir: Path, stage: str, floor: int = 0) -> int:
    """work/ 안의 가장 큰 번호와 floor(DB에 기록된 가장 큰 번호) 중 큰 것 + 1. work/done을 지워도 이름이 겹치지 않는다."""
    biggest = floor
    for state in STATES:
        for p in stage_dir(work_dir, state, stage).iterdir():
            m = _BATCH_RE.match(p.name)
            if m:
                biggest = max(biggest, int(m.group(1)))
    return biggest + 1


def write_batch(work_dir: Path, stage: str, jobs: list[dict], floor: int = 0) -> Path | None:
    if not jobs:
        return None
    path = stage_dir(work_dir, "queue", stage) / batch_name(next_batch_number(work_dir, stage, floor))
    return write_jsonl_atomic(path, jobs)


def in_flight_provision_ids(work_dir: Path, stage: str) -> set[int]:
    """아직 가져오지 않은 배치(queue, claimed)에 들어 있는 조문(program 단계는 공고 판)과,
    재시도까지 실패해서 버린 조문(failed/<stage>/dropped.jsonl). 둘 다 다시 내보내지 않는다."""
    key = TARGET_KEY.get(stage, "provision_id")
    ids: set[int] = set()
    for state in ("queue", "claimed"):
        for p in stage_dir(work_dir, state, stage).glob("batch-*.jsonl"):
            ids.update(int(j[key]) for j in read_jsonl(p))
    dropped = stage_dir(work_dir, "failed", stage) / DROPPED
    if dropped.exists():
        ids.update(int(j[key]) for j in read_jsonl(dropped))
    return ids


def chunk(jobs: list[dict], size: int) -> list[list[dict]]:
    return [jobs[i : i + size] for i in range(0, len(jobs), size)]


@contextmanager
def work_lock(work_dir: Path):
    """배치 번호를 매기고 파일을 옮기는 일(export, ingest)은 한 프로세스씩만 한다.
    새벽 nightly와 `kloe agent --ingest`가 겹쳐도 같은 배치를 두 번 가져오거나 같은 번호를 쓰지 않게 한다. 중첩하면 멈춘다."""
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(work_dir) / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
