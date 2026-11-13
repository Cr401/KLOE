"""kloe CLI (L0). launchd가 매일 `kloe nightly`를 돌린다."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from kloe import db
from kloe.collect.law_api import LawApiClient, LawApiError
from kloe.collect.programs import SOURCES as PROGRAM_SOURCES
from kloe.collect.programs import ProgramApiClient, ProgramApiError
from kloe.link.delegation import link
from kloe.models import Provision
from kloe.normalize.parse import parse_law_xml
from kloe.normalize.program import parse_rows
from kloe.queue import export as qx
from kloe.queue import ingest as qi
from kloe.queue import runner as qr

ROOT = Path.cwd()


def _paths(args) -> tuple[Path, Path]:
    return Path(args.work_dir), Path(args.raw_dir)


def _law_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (l.split("#", 1)[0].strip() for l in path.read_text(encoding="utf-8").splitlines())
    return [l for l in lines if l]


def cmd_migrate(args) -> int:
    with db.connect(args.db) as conn:
        print("applied:", db.migrate(conn) or "none")
    return 0


def cmd_fetch(args) -> list[Path]:
    _, raw_dir = _paths(args)
    ids = args.law_id or _law_ids(Path(args.laws_file))
    client = LawApiClient()
    files = []
    for law_id in ids:  # 한 법령이 실패해도(키 없음, 타임아웃, DNS) 나머지는 받고, 받은 것은 적재한다
        try:
            raw = client.fetch_law(law_id, raw_dir)
        except (LawApiError, OSError) as e:
            print(f"fetch 건너뜀 ({law_id}): {e}", file=sys.stderr)
            continue
        print(f"fetched {law_id} -> {raw.path}")
        files.append(raw.path)
    return files


def load_files(conn, files: list[Path]) -> set[str]:
    """XML 파일을 파싱해서 저장한다. 새로 들어간 판의 법령명을 돌려준다."""
    import hashlib

    changed: set[str] = set()
    for f in files:
        body = Path(f).read_bytes()
        parsed = parse_law_xml(body, file_path=str(f), sha256=hashlib.sha256(body).hexdigest())
        _, ids, new = db.store_parsed(conn, parsed)
        print(f"{'loaded' if new else 'exists'} {parsed.document.law_name} {parsed.document.version_key} ({len(ids)} provisions)")
        if new:
            changed.add(parsed.document.law_name)
    conn.commit()
    return changed


def _base_law_name(name: str) -> str:
    for suffix in (" 시행령", " 시행규칙"):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return name


def link_law(conn, law_name: str) -> int:
    def as_provisions(rows: dict[str, dict]) -> list[Provision]:
        return [Provision(article_key=k, heading=None, text=r["text"], effective_from=date.min) for k, r in rows.items()]

    law = db.current_provisions(conn, law_name)
    decree = db.current_provisions(conn, f"{law_name} 시행령")
    rule = db.current_provisions(conn, f"{law_name} 시행규칙")
    links = link(as_provisions(law), as_provisions(decree), as_provisions(rule))
    n = db.store_links(
        conn,
        {k: r["id"] for k, r in law.items()},
        {"decree": {k: r["id"] for k, r in decree.items()}, "rule": {k: r["id"] for k, r in rule.items()}},
        links,
    )
    conn.commit()
    gaps = sum(1 for lk in links if lk.target_key is None)
    print(f"linked {law_name}: {len(links)} phrases, {n} new, {gaps} without target (G3 후보)")
    return n


def fetch_programs(conn, raw_dir: Path, sources: list[str], *, max_pages: int = 100,
                   client: ProgramApiClient | None = None) -> tuple[int, int]:
    """공고 API를 쪽마다 받아 바로 적재한다. (새 공고 수, 새 판 수)"""
    client = client or ProgramApiClient()
    total_p = total_v = 0
    for source in sources:
        n_rows = 0
        for page in client.pages(source, raw_dir, max_pages=max_pages):
            records = parse_rows(source, page.rows)
            p, v = db.store_programs(conn, records, file_path=str(page.path), sha256=page.sha256)
            conn.commit()
            n_rows += len(records)
            total_p, total_v = total_p + p, total_v + v
        print(f"fetched programs {source}: {n_rows} rows")
    print(f"programs: {total_p} new, {total_v} new versions")
    return total_p, total_v


def export_stage(conn, work_dir: Path, stage: str, limit: int, batch_size: int, recheck: str | None = None,
                 law_filter: str | None = None) -> list[Path]:
    if stage == "audit":
        rows = db.export_audit_candidates(conn, limit, qx.in_flight_provision_ids(work_dir, stage), law_filter)
        return _write_batches(conn, work_dir, stage, [
            qx.make_audit_job(fact_id=r["fact_id"], text_hash=r["text_hash"], law_name=r["law_name"],
                              article_key=r["article_key"], text=r["text"],
                              fact={k: v for k, v in r["payload"].items() if k != "stage"})
            for r in rows
        ], batch_size)
    if stage == "program":
        rows = db.export_program_candidates(conn, limit, qx.in_flight_provision_ids(work_dir, stage))
        return _write_batches(conn, work_dir, stage, [
            qx.make_program_job(version_id=r["version_id"], text_hash=r["text_hash"], source=r["source"],
                                title=r["title"], apply_end=r["apply_end"].isoformat() if r["apply_end"] else None,
                                text=r["text"])
            for r in rows
        ], batch_size)
    db.carry_facts(conn)  # 개정판 뒤에 가져온 옛 조문 결과를 새 조문으로 (멱등)
    rows = db.export_candidates(conn, stage, limit, qx.in_flight_provision_ids(work_dir, stage), recheck)
    jobs = [
        qx.make_job(
            stage,
            provision_id=r["id"], text_hash=r["text_hash"], law_name=r["law_name"], article_key=r["article_key"],
            effective_from=r["effective_from"].isoformat(), text=r["text"], delegations=r["delegations"],
        )
        for r in rows
    ]
    return _write_batches(conn, work_dir, stage, jobs, batch_size)


def _write_batches(conn, work_dir: Path, stage: str, jobs: list[dict], batch_size: int) -> list[Path]:
    paths = []
    with qx.work_lock(work_dir):
        for part in qx.chunk(jobs, batch_size):
            p = qx.write_batch(work_dir, stage, part, db.max_batch_number(conn, stage))
            db.record_batch(conn, stage, p.name)
            paths.append(p)
        conn.commit()
    print(f"exported {stage}: {len(jobs)} jobs in {len(paths)} batches")
    return paths


def ingest_stage(conn, work_dir: Path, stage: str) -> list[qi.IngestReport]:
    reports = []
    with qx.work_lock(work_dir):
        for name in qi.ready_batches(work_dir, stage):
            rep = qi.ingest_batch(work_dir, stage, name, finish_now=False)
            n = db.store_report(conn, rep)
            conn.commit()  # DB에 먼저 넣고 파일을 옮긴다. 커밋이 실패하면 파일이 남아 다음에 다시 가져온다
            qi.finish(work_dir, stage, rep, db.max_batch_number(conn, stage))
            if rep.requeued:
                db.record_batch(conn, stage, rep.requeued.name)
                conn.commit()
            print(f"ingested {stage}/{name}: {n} facts, {len(rep.failed)} failed, {len(rep.missing)} missing"
                  + (f", requeued -> {rep.requeued.name}" if rep.requeued else ""))
            reports.append(rep)
    return reports


def cmd_load(args) -> int:
    with db.connect(args.db) as conn:
        load_files(conn, [Path(f) for f in args.files])
    return 0


def cmd_link(args) -> int:
    with db.connect(args.db) as conn:
        link_law(conn, args.law)
    return 0


def cmd_export(args) -> int:
    work_dir, _ = _paths(args)
    with db.connect(args.db) as conn:
        recheck = qr.SKILL_VERSION["classify"] if args.recheck else None
        limit = args.limit if args.limit is not None else (50 if args.stage == "audit" else 5000)
        export_stage(conn, work_dir, args.stage, limit, args.batch_size, recheck, args.law_filter)
    return 0


STAGES = ("classify", "extract", "program", "audit")  # 가져오기·되돌리기·상태 보기 대상
AUTO_EXPORT = ("classify", "extract", "program")  # nightly가 자동으로 내보내는 단계. 감사는 손으로만


def cmd_fetch_programs(args) -> int:
    _, raw_dir = _paths(args)
    with db.connect(args.db) as conn:
        fetch_programs(conn, raw_dir, args.source or list(PROGRAM_SOURCES), max_pages=args.max_pages)
    return 0


def cmd_programs(args) -> int:
    with db.connect(args.db) as conn:
        for r in db.open_programs(conn):
            f = r["payload"] or {}
            if args.extracted and not f:
                continue
            size = (f.get("benefit_size") or {}).get("raw")
            print(json.dumps({"source": r["source"], "title": r["title"], "agency": r["agency"],
                              "apply_end": r["apply_end"].isoformat() if r["apply_end"] else None,
                              "benefit_type": f.get("benefit_type"), "size": size,
                              "beneficiary": f.get("beneficiary"), "url": r["url"]}, ensure_ascii=False))
    return 0


def cmd_ingest(args) -> int:
    work_dir, _ = _paths(args)
    with db.connect(args.db) as conn:
        for stage in args.stage or STAGES:
            ingest_stage(conn, work_dir, stage)
    return 0


def cmd_requeue(args) -> int:
    work_dir, _ = _paths(args)
    secs = qi.parse_duration(args.stale)
    for stage in args.stage or STAGES:
        for name in qi.requeue_stale(work_dir, stage, secs):
            print(f"requeued {stage}/{name}")
    return 0


def cmd_agent(args) -> int:
    work_dir, _ = _paths(args)
    try:
        results = qr.run(work_dir, args.stage, model=args.model, parallel=args.parallel,
                         max_batches=args.max_batches, timeout=args.timeout)
    except qr.AgentUnavailable as e:
        print(f"agent 중단: {e}", file=sys.stderr)
        return 2
    ok = sum(r.ok for r in results)
    print(f"agent {args.stage}: {ok} ok, {len(results) - ok} failed")
    if args.ingest:
        with db.connect(args.db) as conn:
            ingest_stage(conn, work_dir, args.stage)
    return 0 if ok == len(results) else 1


def status_line(conn, work_dir: Path) -> str:
    """nightly 끝에 찍는 한 줄 요약: 단계별 대기·처리 중·결과 도착 배치 수, 버린 job 수, verified 수."""
    verified = {r["stage"]: r["n"] for r in conn.execute(
        """select payload->>'stage' as stage, count(*) as n from fact where status = 'verified' group by 1""")}
    verified["program"] = conn.execute(
        "select count(*) as n from program_fact where status = 'verified'").fetchone()["n"]
    parts = []
    for stage in STAGES:
        n = {state: len(list(qx.stage_dir(work_dir, state, stage).glob("batch-*.jsonl")))
             for state in ("queue", "claimed", "out")}
        dropped = qx.stage_dir(work_dir, "failed", stage) / qx.DROPPED
        nd = len(qx.read_jsonl(dropped)) if dropped.exists() else 0
        parts.append(f"{stage} queue={n['queue']} claimed={n['claimed']} out={n['out']} "
                     f"dropped={nd} verified={verified.get(stage, 0)}")
    return " | ".join(parts)


def cmd_status(args) -> int:
    work_dir, _ = _paths(args)
    with db.connect(args.db) as conn:
        print(status_line(conn, work_dir))
    return 0


def write_audit_report(conn, reports_dir: Path) -> Path:
    s = db.audit_summary(conn)
    lines = [f"# 추출 감사 {date.today().isoformat()}", "",
             f"감사한 fact {s['total']}건, 문제 없음 {s['ok']}건. 감사 모델: {', '.join(s['extractors']) or '없음'}.",
             "fact는 고치지 않았다. 계통 오류(같은 필드·방향이 반복)가 보이면 kloe-extract skill을 고친다.", "",
             "## 필드별 지적", "", "| 필드 | lost (놓침) | wrong (틀림) | extra (지어냄) |", "| --- | --- | --- | --- |"]
    for field in sorted({f for f, _ in s["by_field"]}):
        c = [s["by_field"].get((field, d), 0) for d in ("lost", "wrong", "extra")]
        lines.append(f"| {field} | {c[0]} | {c[1]} | {c[2]} |")
    lines += ["", "## 놓친 것 (lost)", ""]
    for i in s["lost"] or []:
        lines.append(f"- {i['law_name']} {i['article_key']} (role={i['role']}) `{i['field']}`: {i['problem']}"
                     f" — 원문: \"{i['quote']}\"")
    if not s["lost"]:
        lines.append("없음.")
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"audit-{date.today().isoformat()}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_audit_report(args) -> int:
    with db.connect(args.db) as conn:
        print(write_audit_report(conn, Path(args.reports_dir)))
    return 0


def cmd_show(args) -> int:
    with db.connect(args.db) as conn:
        for r in db.provisions_as_of(conn, args.law_id, date.fromisoformat(args.as_of)):
            print(json.dumps({k: str(v) for k, v in r.items()}, ensure_ascii=False))
    return 0


def cmd_nightly(args) -> int:
    work_dir, raw_dir = _paths(args)
    files = cmd_fetch(args)
    with db.connect(args.db) as conn:
        changed = load_files(conn, files)
        for name in sorted({_base_law_name(n) for n in changed}):
            link_law(conn, name)
        for source in PROGRAM_SOURCES:  # 한 소스가 실패해도 다른 소스는 받는다
            try:
                fetch_programs(conn, raw_dir, [source], max_pages=args.max_pages)
            except (ProgramApiError, OSError) as e:
                conn.rollback()
                print(f"공고 수집 건너뜀 ({source}): {e}", file=sys.stderr)
        for stage in STAGES:
            ingest_stage(conn, work_dir, stage)
        for stage in AUTO_EXPORT:
            export_stage(conn, work_dir, stage, args.limit, args.batch_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kloe")
    ap.add_argument("--db", default=None, help="Postgres URL (기본: KLOE_DATABASE_URL)")
    ap.add_argument("--work-dir", default=str(ROOT / "work"))
    ap.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate").set_defaults(func=cmd_migrate)

    p = sub.add_parser("fetch", help="법제처 API에서 원본 XML 받기 (KLOE_OC 필요)")
    p.add_argument("--law-id", action="append")
    p.add_argument("--laws-file", default=str(ROOT / "config" / "laws.txt"))
    p.set_defaults(func=lambda a: (cmd_fetch(a), 0)[1])

    p = sub.add_parser("fetch-programs", help="지원사업·창업 공고 API에서 받아 적재 (KLOE_DATA_GO_KR_KEY 필요)")
    p.add_argument("--source", action="append", choices=tuple(PROGRAM_SOURCES))
    p.add_argument("--max-pages", type=int, default=100)
    p.set_defaults(func=cmd_fetch_programs)

    p = sub.add_parser("programs", help="마감 전 공고와 추출 결과 보기 (한 줄에 JSON 하나)")
    p.add_argument("--extracted", action="store_true", help="추출이 끝난 공고만")
    p.set_defaults(func=cmd_programs)

    p = sub.add_parser("load", help="원본 XML을 파싱해서 DB에 저장")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("link", help="위임 연결 (법률 -> 시행령/시행규칙)")
    p.add_argument("--law", required=True, help="법률 이름 (예: 조세특례제한법)")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("export", help="배치 파일 내보내기")
    p.add_argument("--stage", choices=STAGES, required=True)
    p.add_argument("--limit", type=int, default=None, help="최대 job 수 (기본 5000, audit는 표본 50)")
    p.add_argument("--law-filter", default=None, help="audit만: 법령명에 이 글자가 든 조문만 (예: 시행)")
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--recheck", action="store_true",
                   help="classify만: false로 분류된 위임 항 중 같은 조에 true가 있는 것을 현재 skill 버전으로 다시 분류")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("ingest", help="결과 파일 가져오기 + 검증")
    p.add_argument("--stage", action="append", choices=STAGES)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("requeue", help="오래된 claimed 배치를 queue로 되돌리기")
    p.add_argument("--stale", default="6h")
    p.add_argument("--stage", action="append", choices=STAGES)
    p.set_defaults(func=cmd_requeue)

    p = sub.add_parser("agent", help="Mac에서 claude -p로 queue 배치 처리 (L1 헤드리스)")
    p.add_argument("--stage", choices=tuple(qr.SKILLS), default="classify")
    p.add_argument("--model", default="haiku")
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--max-batches", type=int, default=30)
    p.add_argument("--timeout", type=int, default=900, help="배치 하나당 초")
    p.add_argument("--ingest", action="store_true", help="끝나고 바로 kloe ingest")
    p.set_defaults(func=cmd_agent)

    sub.add_parser("status", help="단계별 대기 배치 수와 verified 수 한 줄").set_defaults(func=cmd_status)

    p = sub.add_parser("audit-report", help="추출 감사 결과를 reports/audit-<날짜>.md 로")
    p.add_argument("--reports-dir", default=str(ROOT / "reports"))
    p.set_defaults(func=cmd_audit_report)

    p = sub.add_parser("show", help="기준일 조문 재현")
    p.add_argument("--law-id", required=True)
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("nightly", help="법령·공고 수집 -> 정규화 -> 위임 연결 -> 가져오기 -> 내보내기")
    p.add_argument("--law-id", action="append")
    p.add_argument("--laws-file", default=str(ROOT / "config" / "laws.txt"))
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--max-pages", type=int, default=100, help="공고 소스마다 받을 최대 쪽 수")
    p.set_defaults(func=cmd_nightly)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
