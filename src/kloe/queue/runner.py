"""L1 헤드리스 실행기: Mac에서 Claude Code(`claude -p`)로 배치를 처리한다.

잠금(queue -> claimed rename)과 결과 rename(.tmp -> 최종)은 이 실행기가 한다.
에이전트는 배치 파일을 읽고(Read) 결과 .tmp 하나를 쓰기(Write)만 한다. DB나 kloe 명령은 건드리지 않는다.
검증은 그대로 `kloe ingest`가 한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from kloe.queue.export import stage_dir
from kloe.queue.ingest import claim

REPO = Path(__file__).resolve().parents[3]
SKILLS = {"classify": "kloe-classify"}
SKILL_VERSION = {"classify": "0.2"}  # skills/kloe-classify/SKILL.md 의 version과 같아야 한다 (test_skills)

CommandBuilder = Callable[[str, str], Sequence[str]]  # (prompt, model) -> argv


MODEL_IDS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}


def claude_bin() -> str:
    """launchd·nvm PATH 차이 때문에 KLOE_CLAUDE_BIN(전체 경로)을 먼저 본다."""
    return os.environ.get("KLOE_CLAUDE_BIN") or shutil.which("claude") or "claude"


def claude_command(prompt: str, model: str) -> list[str]:
    """에이전트에게 주는 도구는 Read, Write 뿐이다 (--tools로 나머지는 아예 없앤다)."""
    return [
        claude_bin(), "-p", prompt,
        "--model", MODEL_IDS.get(model, model),
        "--effort", os.environ.get("KLOE_AGENT_EFFORT", "medium"),
        "--tools", "Read,Write",
        "--allowedTools", "Read,Write",
        "--permission-mode", "dontAsk",
        "--no-session-persistence",
        "--output-format", "text",
    ]


@dataclass
class RunResult:
    batch: str
    ok: bool
    detail: str = ""


def extractor(stage: str, model: str) -> str:
    return f"cc:{model}:{SKILLS[stage]}@{SKILL_VERSION[stage]}"


def build_prompt(stage: str, model: str, batch: Path, out_tmp: Path, skill_path: Path) -> str:
    return (
        f"{skill_path} 를 읽고 '판정 기준'과 '출력 형식'을 그대로 따라라.\n"
        f"'작업 순서'의 배치 고르기·이동·touch·rename은 실행기가 이미 했거나 할 것이니 하지 마라.\n"
        f"입력 배치: {batch}\n"
        f"이 파일의 모든 줄을 판정해서, 결과를 {out_tmp} 에 Write 도구로 한 번에 써라. "
        f"입력 줄 수와 결과 줄 수가 같아야 한다.\n"
        f"extractor 값은 정확히 \"{extractor(stage, model)}\" 로 써라.\n"
        f"다른 파일은 만들거나 고치지 마라."
    )


def _lines(path: Path) -> int:
    return sum(1 for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip())


def claim_next(work_dir: Path, stage: str, skip: set[str]) -> Path | None:
    for p in sorted(stage_dir(work_dir, "queue", stage).glob("batch-*.jsonl")):
        if p.name in skip:
            continue
        try:
            return claim(work_dir, stage, p.name)
        except FileNotFoundError:  # 다른 실행기가 먼저 가져감
            continue
    return None


def release(work_dir: Path, stage: str, claimed: Path) -> None:
    """실패한 배치를 queue로 되돌린다."""
    if claimed.exists():
        claimed.rename(stage_dir(work_dir, "queue", stage) / claimed.name)


def run_one(work_dir: Path, stage: str, claimed: Path, model: str, *,
            command: CommandBuilder = claude_command, timeout: int = 900) -> RunResult:
    out_dir = stage_dir(work_dir, "out", stage)
    final = out_dir / claimed.name
    tmp = out_dir / f"{claimed.name}.tmp"
    tmp.unlink(missing_ok=True)
    skill = REPO / "skills" / SKILLS[stage] / "SKILL.md"
    prompt = build_prompt(stage, model, claimed.resolve(), tmp.resolve(), skill)
    try:
        proc = subprocess.run(list(command(prompt, model)), cwd=REPO, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        release(work_dir, stage, claimed)
        return RunResult(claimed.name, False, f"시간 초과 {timeout}s")
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        release(work_dir, stage, claimed)
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        return RunResult(claimed.name, False, f"exit {proc.returncode}, 결과 없음: {tail[0][:200]}")
    want, got = _lines(claimed), _lines(tmp)
    if want != got:
        tmp.unlink(missing_ok=True)
        release(work_dir, stage, claimed)
        return RunResult(claimed.name, False, f"줄 수 불일치 {got}/{want}")
    tmp.rename(final)
    return RunResult(claimed.name, True, f"{got}줄")


def run(work_dir: Path, stage: str, *, model: str = "haiku", parallel: int = 3, max_batches: int = 30,
        command: CommandBuilder = claude_command, timeout: int = 900,
        log: Callable[[str], None] = print) -> list[RunResult]:
    """queue에서 배치를 최대 max_batches개 가져와 parallel개씩 동시에 처리한다.
    이번 실행에서 실패한 배치는 queue로 돌아가고, 같은 실행 안에서는 다시 가져가지 않는다."""
    if stage not in SKILLS:
        raise ValueError(f"{stage} 단계 실행기는 아직 없다")
    results: list[RunResult] = []
    tried: set[str] = set()
    lock = threading.Lock()

    def worker() -> None:
        while True:
            with lock:
                if len(tried) >= max_batches:
                    return
                claimed = claim_next(work_dir, stage, tried)
                if claimed is None:
                    return
                tried.add(claimed.name)
            r = run_one(work_dir, stage, claimed, model, command=command, timeout=timeout)
            with lock:
                log(f"{'ok' if r.ok else 'FAIL'} {stage}/{r.batch}: {r.detail}")
                results.append(r)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        for f in [ex.submit(worker) for _ in range(max(1, parallel))]:
            f.result()
    return results
