"""Postgres 통합 테스트. KLOE_TEST_DATABASE_URL이 없으면 건너뛴다 (테스트가 public 스키마를 지운다)."""

import os
from datetime import date
from pathlib import Path

import pytest

from agent_sim import run_agent
from kloe import cli, db
from kloe.queue import ingest as qi

URL = os.environ.get("KLOE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="KLOE_TEST_DATABASE_URL 없음")
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn():
    with db.connect(URL) as c:
        c.execute("drop schema public cascade")
        c.execute("create schema public")
        c.commit()
        db.migrate(c)
        yield c


def drain(conn, work, stage):
    """내보내기 -> 가짜 에이전트 -> 가져오기 한 바퀴."""
    paths = cli.export_stage(conn, work, stage, limit=100, batch_size=2)
    for p in paths:
        qi.claim(work, stage, p.name)
        run_agent(work, stage, p.name)
    return cli.ingest_stage(conn, work, stage), paths


def test_pipeline_end_to_end(conn, tmp_path):
    work = tmp_path / "work"
    assert db.migrate(conn) == []  # 두 번 돌려도 안전

    changed = cli.load_files(conn, [FIX / "law_v1.xml", FIX / "decree_v1.xml"])
    assert changed == {"테스트특례법", "테스트특례법 시행령"}
    assert cli.load_files(conn, [FIX / "law_v1.xml"]) == set()  # 같은 판은 다시 넣지 않음

    cli.link_law(conn, "테스트특례법")
    rows = list(conn.execute(
        """select s.article_key as src, t.article_key as tgt from delegation g
           join provision s on s.id = g.source_id left join provision t on t.id = g.target_id order by g.id"""))
    assert [(r["src"], r["tgt"]) for r in rows] == [("16-1", "10-1"), ("16-2", None), ("17-1", None)]
    cli.link_law(conn, "테스트특례법")
    assert conn.execute("select count(*) as n from delegation").fetchone()["n"] == 3  # 재실행해도 중복 없음

    # classify: 법률 4개 + 시행령 2개 조문
    reports, paths = drain(conn, work, "classify")
    assert len(paths) == 3 and all(r.ok for r in reports)
    assert cli.export_stage(conn, work, "classify", 100, 2) == []  # 이미 분류됨

    # extract: '공제한다'가 있는 16-1, 17-1만
    reports, _ = drain(conn, work, "extract")
    facts = list(conn.execute(
        """select p.article_key, f.payload from fact f join provision p on p.id = f.provision_id
           where f.payload->>'stage' = 'extract' order by p.article_key"""))
    assert [f["article_key"] for f in facts] == ["16-1", "17-1"]
    assert facts[0]["payload"]["benefit_size"]["rate"] == 0.1
    job = qx_first_job(work)
    assert job["delegations"] and job["delegations"][0]["target_text"].startswith("① 법 제16조제1항")

    batches = conn.execute("select count(*) as n from batch where status = 'ingested'").fetchone()["n"]
    assert batches == 4  # classify 3개 + extract 1개

    # 개정판 적재 -> 변경 감지, stale, 기준일 재현
    cli.load_files(conn, [FIX / "law_v2.xml"])
    events = {(r["article_key"], r["kind"]) for r in conn.execute("select article_key, kind from change_event")}
    assert events == {("16-1", "amended"), ("17-1", "repealed")}
    stale = {r["article_key"] for r in conn.execute(
        "select p.article_key from fact f join provision p on p.id = f.provision_id where f.status = 'stale'")}
    assert stale == {"16-1", "17-1"}

    v1 = db.provisions_as_of(conn, "999001", date(2026, 6, 1))
    v2 = db.provisions_as_of(conn, "999001", date(2027, 6, 1))
    assert {r["version_key"] for r in v1} == {"20260101-10001"}
    assert {r["version_key"] for r in v2} == {"20270101-10500"}
    assert "3천만원" in next(r["text"] for r in v1 if r["article_key"] == "16-1")
    assert "5천만원" in next(r["text"] for r in v2 if r["article_key"] == "16-1")
    assert db.provisions_as_of(conn, "999001", date(2025, 6, 1)) == []

    # 새 판의 조문만 다시 분류 대상이 된다 (현행 3개)
    paths = cli.export_stage(conn, work, "classify", 100, 10)
    assert sum(len(qi.read_jsonl(p)) for p in paths) == 3


def qx_first_job(work):
    from kloe.queue.export import read_jsonl, stage_dir

    for p in sorted(stage_dir(work, "done", "extract").glob("batch-*[0-9].jsonl")):
        for j in read_jsonl(p):
            if j["article_key"] == "16-1":
                return j
    raise AssertionError("16-1 job 없음")
