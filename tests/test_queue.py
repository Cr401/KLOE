import os

from agent_sim import run_agent
from kloe.queue import export as qx
from kloe.queue import ingest as qi


def jobs(n, stage="classify", text="거주자가 출자하면 출자금액의 100분의 10을 공제한다. 끝."):
    return [qx.make_job(stage, provision_id=i, text_hash=f"{i:064x}", law_name="테스트특례법", article_key=f"{i}-1",
                        effective_from="2026-01-01", text=text) for i in range(1, n + 1)]


def test_round_trip_all_ok(tmp_path):
    p = qx.write_batch(tmp_path, "classify", jobs(3))
    assert p.name == "batch-000001.jsonl"
    assert qx.in_flight_provision_ids(tmp_path, "classify") == {1, 2, 3}
    qi.claim(tmp_path, "classify", p.name)
    assert qi.ready_batches(tmp_path, "classify") == []  # 결과 전
    run_agent(tmp_path, "classify", p.name)
    assert qi.ready_batches(tmp_path, "classify") == [p.name]

    rep = qi.ingest_batch(tmp_path, "classify", p.name)
    assert rep.ok and len(rep.accepted) == 3 and rep.requeued is None
    assert rep.extractor.startswith("cowork:")
    done = qx.stage_dir(tmp_path, "done", "classify")
    assert (done / "batch-000001.jsonl").exists() and (done / "batch-000001.out.jsonl").exists()
    assert qx.in_flight_provision_ids(tmp_path, "classify") == set()
    assert qx.next_batch_number(tmp_path, "classify") == 2


def test_failed_lines_are_requeued_once(tmp_path):
    p = qx.write_batch(tmp_path, "extract", jobs(4, stage="extract"))
    qi.claim(tmp_path, "extract", p.name)

    def tamper(rows):
        rows[0]["fact"]["quotes"][0]["quote"] = "원문에 없는 문장"  # 인용 검증 실패
        rows[1]["extractor"] = "sonnet"  # 스키마 실패
        rows.append(dict(rows[2]))  # job_id 중복
        rows.append("{not json\n")
        del rows[3]  # 4번째 job 결과 누락
        return rows

    run_agent(tmp_path, "extract", p.name, tamper)
    rep = qi.ingest_batch(tmp_path, "extract", p.name)
    assert len(rep.accepted) == 1
    assert len(rep.failed) == 4 and len(rep.missing) == 1
    failed_dir = qx.stage_dir(tmp_path, "failed", "extract")
    assert (failed_dir / "batch-000001.reason.json").exists()

    retry = qx.read_jsonl(rep.requeued)
    assert sorted(j["provision_id"] for j in retry) == [1, 2, 4]
    assert all(j["attempt"] == 1 for j in retry)

    # 재시도 배치도 실패하면 더 이상 대기열에 넣지 않는다
    qi.claim(tmp_path, "extract", rep.requeued.name)
    run_agent(tmp_path, "extract", rep.requeued.name, lambda rows: [])
    rep2 = qi.ingest_batch(tmp_path, "extract", rep.requeued.name)
    assert len(rep2.missing) == 3 and rep2.requeued is None
    # 버린 job은 다음 export에서 빠진다 (매일 밤 다시 나가지 않게)
    assert qx.in_flight_provision_ids(tmp_path, "extract") == {1, 2, 4}


def test_requeue_stale(tmp_path):
    a = qx.write_batch(tmp_path, "classify", jobs(1))
    b = qx.write_batch(tmp_path, "classify", jobs(1))
    qi.claim(tmp_path, "classify", a.name)
    qi.claim(tmp_path, "classify", b.name)
    run_agent(tmp_path, "classify", b.name)  # b는 결과가 있으니 되돌리지 않는다
    claimed = qx.stage_dir(tmp_path, "claimed", "classify") / a.name
    old = claimed.stat().st_mtime - 7 * 3600
    os.utime(claimed, (old, old))
    assert qi.requeue_stale(tmp_path, "classify", qi.parse_duration("6h")) == [a.name]
    assert (qx.stage_dir(tmp_path, "queue", "classify") / a.name).exists()
    assert qi.requeue_stale(tmp_path, "classify", qi.parse_duration("6h")) == []


def test_parse_duration():
    assert qi.parse_duration("6h") == 21600 and qi.parse_duration("30m") == 1800 and qi.parse_duration("10") == 10


def test_finish_later_and_floor(tmp_path):
    """DB 커밋 전에는 파일을 옮기지 않고, 재시도 배치 번호는 DB의 가장 큰 번호보다 크게 매긴다."""
    p = qx.write_batch(tmp_path, "classify", jobs(2))
    qi.claim(tmp_path, "classify", p.name)
    run_agent(tmp_path, "classify", p.name, lambda rows: rows[:1])
    rep = qi.ingest_batch(tmp_path, "classify", p.name, finish_now=False)
    assert qi.ready_batches(tmp_path, "classify") == [p.name] and rep.requeued is None  # 아직 그대로
    qi.finish(tmp_path, "classify", rep, floor=41)
    assert rep.requeued.name == "batch-000042.jsonl"
    assert qi.ready_batches(tmp_path, "classify") == []


def test_work_lock_is_exclusive(tmp_path):
    import fcntl

    import pytest

    with qx.work_lock(tmp_path):
        with open(tmp_path / ".lock") as other, pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(tmp_path / ".lock") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 끝나면 풀린다
