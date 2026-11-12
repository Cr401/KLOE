"""헤드리스 실행기: 진짜 claude 대신 프롬프트에서 경로를 읽어 결과를 쓰는 가짜 명령으로 돌린다."""

import json
import re
import sys

from agent_sim import fake_result
from kloe.queue import export as qx
from kloe.queue import ingest as qi
from kloe.queue import runner as qr
from test_queue import jobs

FAKE = r'''
import json, re, sys
prompt = sys.argv[1]
mode = sys.argv[2]
src = re.search(r"입력 배치: (\S+)", prompt).group(1)
dst = re.search(r"결과를 (\S+) 에 Write", prompt).group(1)
ext = re.search(r'extractor 값은 정확히 "([^"]+)"', prompt).group(1)
if mode == "crash":
    sys.exit(3)
rows = []
for line in open(src, encoding="utf-8"):
    j = json.loads(line)
    benefit = "공제한다" in j["text"]
    rows.append({"job_id": j["job_id"], "extractor": ext, "is_benefit": benefit,
                 "benefit_type": "deduction" if benefit else None, "reason": "test",
                 "quotes": [{"field": "is_benefit", "quote": j["text"].split(". ")[0]}] if benefit else []})
if mode == "short":
    rows = rows[:-1]
with open(dst, "w", encoding="utf-8") as f:
    f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
'''


def fake_command(tmp_path, mode="ok"):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    return lambda prompt, model: [sys.executable, str(script), prompt, mode]


def test_runs_all_batches_and_ingests(tmp_path):
    work = tmp_path / "work"
    for _ in range(4):
        qx.write_batch(work, "classify", jobs(3))
    logs = []
    res = qr.run(work, "classify", parallel=2, command=fake_command(tmp_path), log=logs.append)
    assert len(res) == 4 and all(r.ok for r in res)
    assert list(qx.stage_dir(work, "queue", "classify").iterdir()) == []
    assert not list(qx.stage_dir(work, "out", "classify").glob("*.tmp"))
    ready = qi.ready_batches(work, "classify")
    assert len(ready) == 4
    rep = qi.ingest_batch(work, "classify", ready[0])
    assert rep.ok and rep.extractor == "cc:haiku:kloe-classify@0.2"


def test_max_batches(tmp_path):
    work = tmp_path / "work"
    for _ in range(5):
        qx.write_batch(work, "classify", jobs(2))
    res = qr.run(work, "classify", parallel=3, max_batches=2, command=fake_command(tmp_path))
    assert len(res) == 2
    assert len(list(qx.stage_dir(work, "queue", "classify").glob("batch-*.jsonl"))) == 3


def test_failures_go_back_to_queue_once(tmp_path):
    work = tmp_path / "work"
    for _ in range(2):
        qx.write_batch(work, "classify", jobs(3))
    for mode in ("crash", "short"):
        res = qr.run(work, "classify", parallel=2, command=fake_command(tmp_path, mode))
        assert len(res) == 2 and not any(r.ok for r in res)  # 같은 실행 안에서 재시도하지 않음
        assert len(list(qx.stage_dir(work, "queue", "classify").glob("batch-*.jsonl"))) == 2
        assert list(qx.stage_dir(work, "claimed", "classify").iterdir()) == []
        assert list(qx.stage_dir(work, "out", "classify").iterdir()) == []


def test_command_limits_tools():
    argv = qr.claude_command("p", "haiku")
    assert argv[argv.index("--tools") + 1] == "Read,Write"
    assert argv[argv.index("--allowedTools") + 1] == "Read,Write"
    assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
    assert argv[argv.index("--effort") + 1] == "medium"


def test_exec_error_releases_batch_and_stops(tmp_path):
    work = tmp_path / "work"
    for _ in range(4):
        qx.write_batch(work, "classify", jobs(2))
    bad = tmp_path / "not_exec"
    bad.write_text("no shebang here\n")
    bad.chmod(0o755)
    res = qr.run(work, "classify", parallel=1, command=lambda p, m: [str(bad), p])
    assert len(res) == 1 and res[0].fatal and not res[0].ok
    assert len(list(qx.stage_dir(work, "queue", "classify").glob("batch-*.jsonl"))) == 4
    assert list(qx.stage_dir(work, "claimed", "classify").iterdir()) == []


def test_preflight_reports_unusable_binary(tmp_path):
    import pytest

    bad = tmp_path / "not_exec"
    bad.write_text("no shebang here\n")
    bad.chmod(0o755)
    with pytest.raises(qr.AgentUnavailable):
        qr.preflight(str(bad))
