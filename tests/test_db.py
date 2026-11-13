"""Postgres 통합 테스트. KLOE_TEST_DATABASE_URL이 없으면 건너뛴다 (테스트가 public 스키마를 지운다)."""

import os
import re
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

    # 안 바뀐 조문(16-2 등)은 결과를 이어받고, 본문이 바뀐 16-1만 다시 분류 대상이 된다
    carried = {r["article_key"] for r in conn.execute(
        """select p.article_key from fact f join provision p on p.id = f.provision_id
           where f.carried_from is not null and f.payload->>'stage' = 'classify'""")}
    assert "16-1" not in carried and "16-2" in carried
    paths = cli.export_stage(conn, work, "classify", 100, 10)
    assert [j["article_key"] for p in paths for j in qi.read_jsonl(p)] == ["16-1"]
    assert db.carry_facts(conn) == 0  # 멱등
    line = cli.status_line(conn, work)
    assert "classify queue=" in line and "program queue=0" in line


def test_carry_facts_for_results_ingested_after_new_version(conn, tmp_path):
    """옛 판 조문으로 나간 배치가 개정판 적재 뒤에 들어와도, 다음 내보내기에서 다시 나가지 않는다."""
    work = tmp_path / "work"
    cli.load_files(conn, [FIX / "law_v1.xml"])
    paths = cli.export_stage(conn, work, "classify", limit=100, batch_size=10)
    qi.claim(work, "classify", paths[0].name)
    run_agent(work, "classify", paths[0].name)
    cli.load_files(conn, [FIX / "law_v2.xml"])  # 결과를 가져오기 전에 개정판이 들어옴
    cli.ingest_stage(conn, work, "classify")
    again = cli.export_stage(conn, work, "classify", 100, 10)
    assert [j["article_key"] for p in again for j in qi.read_jsonl(p)] == ["16-1"]


def test_audit_samples_extract_facts_and_reports(conn, tmp_path):
    work = tmp_path / "work"
    cli.load_files(conn, [FIX / "law_v1.xml", FIX / "decree_v1.xml"])
    cli.link_law(conn, "테스트특례법")
    drain(conn, work, "classify")
    drain(conn, work, "extract")
    paths = cli.export_stage(conn, work, "audit", limit=50, batch_size=20)
    jobs = [j for p in paths for j in qi.read_jsonl(p)]
    assert {j["article_key"] for j in jobs} == {"16-1", "17-1"} and all("fact" in j for j in jobs)
    assert cli.export_stage(conn, work, "audit", 50, 20) == []  # 대기 중인 것은 다시 안 나감
    for p in paths:
        qi.claim(work, "audit", p.name)
        run_agent(work, "audit", p.name)
    [rep] = cli.ingest_stage(conn, work, "audit")
    assert rep.ok
    assert cli.export_stage(conn, work, "audit", 50, 20) == []  # 이미 감사함
    report = cli.write_audit_report(conn, tmp_path / "reports").read_text(encoding="utf-8")
    assert "감사한 fact 2건, 문제 없음 1건" in report
    assert "| benefit_size | 1 | 0 | 0 |" in report and "공제한도는 3천만원" in report


def test_fact_links_view_and_dropped_jobs(conn, tmp_path):
    from kloe.queue import export as qx

    work = tmp_path / "work"
    cli.load_files(conn, [FIX / "law_v1.xml", FIX / "decree_v1.xml"])
    cli.link_law(conn, "테스트특례법")
    drain(conn, work, "classify")
    drain(conn, work, "extract")
    view = {r["article_key"]: (float(r["rate"]), r["cap_krw"]) for r in conn.execute("select * from extract_fact")}
    assert view == {"16-1": (0.1, None), "17-1": (0.05, None)}

    # parent_ref 풀기: 시행령 "법 제16조제1항" -> 법률 16-1, 같은 조 "제1항" -> 16-1
    prov = {r["article_key"] + "@" + r["law_name"]: r["id"] for r in conn.execute(
        "select p.id, p.article_key, d.law_name from provision p join source_document d on d.id = p.document_id")}
    batch = conn.execute("select id from batch limit 1").fetchone()["id"]
    for key, ref in (("10-1@테스트특례법 시행령", "법 제16조제1항"), ("16-2@테스트특례법", "제1항")):
        conn.execute(
            """insert into fact (provision_id, text_hash, batch_id, is_benefit, payload, status, extractor)
               select id, text_hash, %s, true, %s, 'verified', 'cc:test:kloe-extract@0.0' from provision where id = %s""",
            (batch, db.Jsonb({"stage": "extract", "is_benefit": True, "role": "condition", "parent_ref": ref}), prov[key]))
    assert db.link_facts(conn) == 2 and db.link_facts(conn) == 0
    targets = {r["ref"]: r["article_key"] for r in conn.execute(
        "select l.ref, p.article_key from fact_link l join provision p on p.id = l.target_id")}
    assert targets == {"법 제16조제1항": "16-1", "제1항": "16-1"}

    # 버린 job은 DB에 남고 다음 export에서 빠진다. undrop하면 다시 나간다
    fid = conn.execute("select id, text_hash from extract_fact where article_key = '16-1'").fetchone()
    failed = qx.stage_dir(work, "failed", "audit")
    (failed / qx.DROPPED).write_text(
        '{"fact_id": %d, "text_hash": "%s", "drop_reasons": ["인용이 원문에 없음"]}\n' % (fid["id"], fid["text_hash"]),
        encoding="utf-8")
    jobs = [j for p in cli.export_stage(conn, work, "audit", 50, 20) for j in qx.read_jsonl(p)]
    assert sorted(j["article_key"] for j in jobs) == ["10-1", "16-2", "17-1"]  # 16-1만 빠짐
    assert not (failed / qx.DROPPED).exists() and (failed / qx.DROPPED_LOG).exists()
    assert "audit queue=1 claimed=0 out=0 dropped=1" in cli.status_line(conn, work)
    assert db.undrop(conn, "audit") == 1
    jobs = [j for p in cli.export_stage(conn, work, "audit", 50, 20) for j in qx.read_jsonl(p)]
    assert [j["article_key"] for j in jobs] == ["16-1"]


def test_ideate_review_and_metrics(conn, tmp_path):
    from kloe import ideas

    work, reports = tmp_path / "work", tmp_path / "reports"
    cli.load_files(conn, [FIX / "law_v1.xml", FIX / "decree_v1.xml"])
    cli.link_law(conn, "테스트특례법")
    drain(conn, work, "classify")
    drain(conn, work, "extract")
    cs = ideas.clusters(conn)
    assert [c.key for c in cs] == ["테스트특례법 제16조", "테스트특례법 제17조"]
    card = ideas.render_card(1, cs[0])
    assert card.startswith("### C1 테스트특례법 제16조 [deduction] 율 10%") and "- fact:" in card

    paths = cli.export_stage(conn, work, "ideate", 0, 1)
    assert len(paths) == 4  # 렌즈마다 배치 하나
    assert cli.export_stage(conn, work, "ideate", 0, 1) == []  # 대기 중인 렌즈는 다시 안 나감
    job = qi.read_jsonl(paths[0])[0]
    catalog = Path(job["catalog"]).read_text(encoding="utf-8")
    assert "## 1. 전체 카드 (2장)" in catalog and "\"quotes\"" in catalog
    for p in paths:
        qi.claim(work, "ideate", p.name)
        run_agent(work, "ideate", p.name)
    reps = cli.ingest_stage(conn, work, "ideate")
    assert all(r.ok for r in reps)
    rows = {r["lens"]: r for r in conn.execute("select * from idea")}
    assert set(rows) == {"combo", "gap", "business"}  # time은 일몰 근거가 없어 0건
    assert len({e["id"] for e in rows["combo"]["evidence"]}) == 2

    # 같은 근거로 다시 내면 중복으로 막힌다
    conn.execute("delete from idea where lens = 'business'")
    conn.execute("insert into idea (week, title, body, lens, evidence, evidence_hash, status) values ('x', 't', 'b', 'business', '[]', %s, 'proposed')",
                 (rows["business"]["evidence_hash"],))
    conn.commit()
    [p] = cli.export_stage(conn, work, "ideate", 0, 1, lenses=("business",))  # 이번 주 business가 비어 다시 나감
    qi.claim(work, "ideate", p.name)
    run_agent(work, "ideate", p.name)
    [rep] = cli.ingest_stage(conn, work, "ideate")
    assert rep.ok and conn.execute("select count(*) as n from idea_duplicate").fetchone()["n"] == 1
    conn.execute("delete from idea where week = 'x'")

    path, n = ideas.write_review_file(conn, reports)
    assert n == 2 and path.name.endswith(".review.md")
    text = path.read_text(encoding="utf-8")
    first, second = [int(x) for x in re.findall(r"^## idea:(\d+)", text, flags=re.M)]
    text = text.replace("- [ ] keep", "- [x] keep", 1)
    marks, broken = ideas.parse_review_file(text)
    assert [m.idea_id for m in marks] == [first] and broken == []
    # drop + wrong_fact 표시
    text2 = text.split(f"## idea:{second}")[1].replace("- [ ] drop  사유:", "- [x] drop  사유: wrong_fact")
    marks2, _ = ideas.parse_review_file(f"## idea:{second}" + text2)
    assert db.store_review_marks(conn, marks + marks2) == (2, 0)
    assert db.store_review_marks(conn, marks) == (0, 1)  # 이미 점검함
    m = db.idea_metrics(conn)
    assert m["status"] == {"approved": 1, "rejected": 1} and m["drop_tags"] == {"wrong_fact": 1}
    assert m["wrong_fact_ids"] and m["batches"] == 5 and m["duplicates_blocked"] == 1

    # 근거 fact가 stale이 되면 needs_recheck
    conn.execute("update fact set status = 'stale' where stage = 'extract'")
    assert db.recheck_ideas(conn) == 1  # approved 1건 (rejected는 그대로)


def qx_first_job(work):
    from kloe.queue.export import read_jsonl, stage_dir

    for p in sorted(stage_dir(work, "done", "extract").glob("batch-*[0-9].jsonl")):
        for j in read_jsonl(p):
            if j["article_key"] == "16-1":
                return j
    raise AssertionError("16-1 job 없음")


class _Pages:
    """FakeFetch: 부를 때마다 다음 fixture를 준다."""

    def __init__(self, *names):
        self.names = list(names)

    def __call__(self, url):
        return (FIX / self.names.pop(0)).read_bytes()


def test_programs_end_to_end(conn, tmp_path, monkeypatch):
    import json

    from kloe.collect.programs import ProgramApiClient

    work, raw = tmp_path / "work", tmp_path / "raw"
    cli.load_files(conn, [FIX / "law_v1.xml"])  # 근거법령 연결 확인용 (테스트특례법)

    client = ProgramApiClient(key="k", fetch=_Pages("programs_gov24_p1.json", "programs_gov24_p2.json"))
    monkeypatch.setitem(__import__("kloe.collect.programs", fromlist=["SOURCES"]).SOURCES["gov24"], "per_page", 2)
    assert cli.fetch_programs(conn, raw, ["gov24"], client=client) == (3, 3)
    client = ProgramApiClient(key="k", fetch=_Pages("programs_kstartup_p1.json"))
    assert cli.fetch_programs(conn, raw, ["kstartup"], client=client) == (1, 1)
    client = ProgramApiClient(key="k", fetch=_Pages("programs_kstartup_p1.json"))
    assert cli.fetch_programs(conn, raw, ["kstartup"], client=client) == (0, 0)  # 같은 본문은 새 판 없음

    # 마감 지난 공고(2025년)는 내보내지 않는다
    paths = cli.export_stage(conn, work, "program", limit=100, batch_size=10)
    jobs = qi.read_jsonl(paths[0])
    # 순서: K-Startup → 마감일 있는 것 → 나머지
    assert [j["title"] for j in jobs] == ["2027년 테스트 예비창업패키지 모집", "테스트 청년 월세 지원", "테스트 대학생 장학금"]
    assert not any("문의처" in j["text"] or "구비서류" in j["text"] for j in jobs)
    assert cli.export_stage(conn, work, "program", 100, 10) == []  # 이미 나간 것은 다시 안 나감

    qi.claim(work, "program", paths[0].name)
    run_agent(work, "program", paths[0].name)
    [rep] = cli.ingest_stage(conn, work, "program")
    assert rep.ok
    assert conn.execute("select count(*) as n from program_fact where status = 'verified'").fetchone()["n"] == 3
    assert cli.export_stage(conn, work, "program", 100, 10) == []
    assert len(db.open_programs(conn)) == 3
    # 같은 소스의 최근 수집보다 3일 넘게 안 보인 공고는 퇴출 (목록에서 사라짐)
    conn.execute("update program set last_seen = last_seen - interval '4 days' where title = '테스트 대학생 장학금'")
    assert len(db.open_programs(conn)) == 2
    conn.execute("update program set last_seen = last_seen + interval '4 days' where title = '테스트 대학생 장학금'")

    basis = list(conn.execute("select basis, law_id from program_law_basis"))
    assert sorted((b["basis"], b["law_id"]) for b in basis) == [
        ("테스트주거지원법(제21조, 제0항)", None),  # 아직 안 모은 법령
        ("테스트특례법(제16조, 제1항)", "999001"),
    ]

    # 본문이 바뀌면 새 판 + 이전 fact stale + 다시 내보내기
    changed = json.loads((FIX / "programs_kstartup_p1.json").read_text(encoding="utf-8"))
    changed["data"][0]["pbanc_ctnt"] = "예비창업자에게 사업화 자금을 최대 1억5천만원까지 지원합니다."
    client = ProgramApiClient(key="k", fetch=lambda url: json.dumps(changed, ensure_ascii=False).encode())
    assert cli.fetch_programs(conn, raw, ["kstartup"], client=client) == (0, 1)
    assert conn.execute("select count(*) as n from program_fact where status = 'stale'").fetchone()["n"] == 1
    again = cli.export_stage(conn, work, "program", 100, 10)
    assert [j["title"] for j in qi.read_jsonl(again[0])] == ["2027년 테스트 예비창업패키지 모집"]


def test_recheck_exports_false_delegations_next_to_true(conn, tmp_path):
    work = tmp_path / "work"
    cli.load_files(conn, [FIX / "law_v1.xml", FIX / "decree_v1.xml"])
    cli.link_law(conn, "테스트특례법")
    drain(conn, work, "classify")  # 가짜 에이전트(@0.0): 16-1 true, 16-2 false
    conn.execute("""update fact f set payload = payload || '{"reason": "신청서를 하위 법령에 위임"}'
                    from provision p where p.id = f.provision_id and p.article_key = '16-2'""")

    def keys(paths):
        return [j["article_key"] for p in paths for j in qi.read_jsonl(p)]

    assert cli.export_stage(conn, work, "classify", 100, 10, recheck="0.0") == []  # 그 버전 결과가 이미 있음
    assert keys(cli.export_stage(conn, work, "classify", 100, 10, recheck="9.9")) == ["16-2"]
    assert cli.export_stage(conn, work, "classify", 100, 10, recheck="9.9") == []  # queue에 있는 동안은 다시 안 나감
