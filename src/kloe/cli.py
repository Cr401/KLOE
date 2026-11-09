"""kloe CLI (L0). launchd가 매일 `kloe nightly`를 돌린다."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from kloe import db
from kloe.collect.law_api import LawApiClient, LawApiError
from kloe.link.delegation import link
from kloe.models import Provision
from kloe.normalize.parse import parse_law_xml
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
    for law_id in ids:
        raw = client.fetch_law(law_id, raw_dir)
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


def export_stage(conn, work_dir: Path, stage: str, limit: int, batch_size: int) -> list[Path]:
    rows = db.export_candidates(conn, stage, limit, qx.in_flight_provision_ids(work_dir, stage))
    jobs = [
        qx.make_job(
            stage,
            provision_id=r["id"], text_hash=r["text_hash"], law_name=r["law_name"], article_key=r["article_key"],
            effective_from=r["effective_from"].isoformat(), text=r["text"], delegations=r["delegations"],
        )
        for r in rows
    ]
    paths = []
    for part in qx.chunk(jobs, batch_size):
        p = qx.write_batch(work_dir, stage, part)
        db.record_batch(conn, stage, p.name)
        paths.append(p)
    conn.commit()
    print(f"exported {stage}: {len(jobs)} jobs in {len(paths)} batches")
    return paths


def ingest_stage(conn, work_dir: Path, stage: str) -> list[qi.IngestReport]:
    reports = []
    for name in qi.ready_batches(work_dir, stage):
        rep = qi.ingest_batch(work_dir, stage, name)
        n = db.store_report(conn, rep)
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
        export_stage(conn, work_dir, args.stage, args.limit, args.batch_size)
    return 0


def cmd_ingest(args) -> int:
    work_dir, _ = _paths(args)
    with db.connect(args.db) as conn:
        for stage in args.stage or ("classify", "extract"):
            ingest_stage(conn, work_dir, stage)
    return 0


def cmd_requeue(args) -> int:
    work_dir, _ = _paths(args)
    secs = qi.parse_duration(args.stale)
    for stage in args.stage or ("classify", "extract"):
        for name in qi.requeue_stale(work_dir, stage, secs):
            print(f"requeued {stage}/{name}")
    return 0


def cmd_agent(args) -> int:
    work_dir, _ = _paths(args)
    results = qr.run(work_dir, args.stage, model=args.model, parallel=args.parallel,
                     max_batches=args.max_batches, timeout=args.timeout)
    ok = sum(r.ok for r in results)
    print(f"agent {args.stage}: {ok} ok, {len(results) - ok} failed")
    if args.ingest:
        with db.connect(args.db) as conn:
            ingest_stage(conn, work_dir, args.stage)
    return 0 if ok == len(results) else 1


def cmd_show(args) -> int:
    with db.connect(args.db) as conn:
        for r in db.provisions_as_of(conn, args.law_id, date.fromisoformat(args.as_of)):
            print(json.dumps({k: str(v) for k, v in r.items()}, ensure_ascii=False))
    return 0


def cmd_nightly(args) -> int:
    work_dir, raw_dir = _paths(args)
    files: list[Path] = []
    try:
        files = cmd_fetch(args)
    except LawApiError as e:
        print(f"fetch 건너뜀: {e}", file=sys.stderr)
    with db.connect(args.db) as conn:
        changed = load_files(conn, files)
        for name in sorted({_base_law_name(n) for n in changed}):
            link_law(conn, name)
        for stage in ("classify", "extract"):
            ingest_stage(conn, work_dir, stage)
        for stage in ("classify", "extract"):
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

    p = sub.add_parser("load", help="원본 XML을 파싱해서 DB에 저장")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("link", help="위임 연결 (법률 -> 시행령/시행규칙)")
    p.add_argument("--law", required=True, help="법률 이름 (예: 조세특례제한법)")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("export", help="배치 파일 내보내기")
    p.add_argument("--stage", choices=("classify", "extract"), required=True)
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--batch-size", type=int, default=20)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("ingest", help="결과 파일 가져오기 + 검증")
    p.add_argument("--stage", action="append", choices=("classify", "extract"))
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("requeue", help="오래된 claimed 배치를 queue로 되돌리기")
    p.add_argument("--stale", default="6h")
    p.add_argument("--stage", action="append", choices=("classify", "extract"))
    p.set_defaults(func=cmd_requeue)

    p = sub.add_parser("agent", help="Mac에서 claude -p로 queue 배치 처리 (L1 헤드리스)")
    p.add_argument("--stage", choices=tuple(qr.SKILLS), default="classify")
    p.add_argument("--model", default="haiku")
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--max-batches", type=int, default=30)
    p.add_argument("--timeout", type=int, default=900, help="배치 하나당 초")
    p.add_argument("--ingest", action="store_true", help="끝나고 바로 kloe ingest")
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("show", help="기준일 조문 재현")
    p.add_argument("--law-id", required=True)
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("nightly", help="수집 -> 정규화 -> 위임 연결 -> 가져오기 -> 내보내기")
    p.add_argument("--law-id", action="append")
    p.add_argument("--laws-file", default=str(ROOT / "config" / "laws.txt"))
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--batch-size", type=int, default=20)
    p.set_defaults(func=cmd_nightly)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
