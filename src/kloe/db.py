"""Postgres 적재. DB에는 코드만 쓴다 (에이전트 결과는 ingest 검증을 통과한 것만)."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from kloe.link.delegation import DelegationLink
from kloe.models import ParsedLaw
from kloe.queue.ingest import IngestReport

DEFAULT_URL = "postgresql://kloe:kloe@localhost:5432/kloe"
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or os.environ.get("KLOE_DATABASE_URL", DEFAULT_URL), row_factory=dict_row)


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS) -> list[str]:
    conn.execute("create table if not exists schema_migration (name text primary key, applied_at timestamptz default now())")
    done = {r["name"] for r in conn.execute("select name from schema_migration")}
    applied = []
    for f in sorted(migrations_dir.glob("*.sql")):
        if f.name in done:
            continue
        conn.execute(f.read_text(encoding="utf-8"))
        conn.execute("insert into schema_migration (name) values (%s)", (f.name,))
        applied.append(f.name)
    conn.commit()
    return applied


# ---------- 수집·정규화 결과 ----------

def store_parsed(conn: psycopg.Connection, parsed: ParsedLaw) -> tuple[int, dict[str, int], bool]:
    """판 하나를 저장한다. 이미 있으면 그대로 돌려준다. (document_id, {article_key: provision_id}, 새로 넣었는지)"""
    d = parsed.document
    row = conn.execute(
        "select id from source_document where law_id = %s and version_key = %s", (d.law_id, d.version_key)
    ).fetchone()
    if row:
        ids = {r["article_key"]: r["id"] for r in conn.execute(
            "select id, article_key from provision where document_id = %s", (row["id"],))}
        return row["id"], ids, False

    doc_id = conn.execute(
        """insert into source_document (law_id, law_name, law_kind, version_key, promulgated, effective, url, file_path, sha256)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (d.law_id, d.law_name, d.law_kind, d.version_key, d.promulgated, d.effective, d.url, d.file_path, d.sha256),
    ).fetchone()["id"]
    ids: dict[str, int] = {}
    for p in parsed.provisions:
        ids[p.article_key] = conn.execute(
            """insert into provision (document_id, article_key, heading, text, text_hash, effective_from, effective_to)
               values (%s, %s, %s, %s, %s, %s, %s) returning id""",
            (doc_id, p.article_key, p.heading, p.text, p.text_hash, p.effective_from, p.effective_to),
        ).fetchone()["id"]
    _close_previous_version(conn, d.law_id, doc_id, d.effective, ids)
    return doc_id, ids, True


def _close_previous_version(conn, law_id: str, new_doc_id: int, effective: date, new_ids: dict[str, int]) -> None:
    """직전 판의 조문에 effective_to를 채우고, 변경 이벤트를 남기고, 바뀐 조문의 fact를 stale로 바꾼다."""
    prev = conn.execute(
        """select id from source_document where law_id = %s and id <> %s and effective <= %s
           order by effective desc, id desc limit 1""",
        (law_id, new_doc_id, effective),
    ).fetchone()
    if not prev:
        return
    old = {r["article_key"]: r for r in conn.execute(
        "select id, article_key, text_hash from provision where document_id = %s", (prev["id"],))}
    new_hash = {r["article_key"]: r["text_hash"] for r in conn.execute(
        "select article_key, text_hash from provision where document_id = %s", (new_doc_id,))}
    conn.execute(
        "update provision set effective_to = %s where document_id = %s and effective_to is null",
        (effective - timedelta(days=1), prev["id"]),
    )
    for key in sorted(set(old) | set(new_ids)):
        if key not in old:
            kind, old_id = "added", None
        elif key not in new_ids:
            kind, old_id = "repealed", old[key]["id"]
        elif old[key]["text_hash"] != new_hash[key]:
            kind, old_id = "amended", old[key]["id"]
        else:
            continue
        conn.execute(
            "insert into change_event (law_id, article_key, old_provision, new_provision, kind) values (%s, %s, %s, %s, %s)",
            (law_id, key, old_id, new_ids.get(key), kind),
        )
        if old_id is not None:
            conn.execute("update fact set status = 'stale' where provision_id = %s and status <> 'rejected'", (old_id,))


def store_links(conn, source_ids: dict[str, int], target_ids: dict[str, dict[str, int]], links: list[DelegationLink]) -> int:
    """target_ids: {'decree': {article_key: id}, 'rule': {...}}"""
    n = 0
    for lk in links:
        src = source_ids.get(lk.source_key)
        if src is None:
            continue
        tgt = target_ids.get(lk.target_level, {}).get(lk.target_key) if lk.target_key else None
        exists = conn.execute(
            "select 1 from delegation where source_id = %s and phrase = %s", (src, lk.phrase)
        ).fetchone()
        if exists:
            conn.execute("update delegation set target_id = %s where source_id = %s and phrase = %s", (tgt, src, lk.phrase))
        else:
            conn.execute(
                "insert into delegation (source_id, target_id, phrase, method) values (%s, %s, %s, %s)",
                (src, tgt, lk.phrase, lk.method),
            )
            n += 1
    return n


def current_provisions(conn, law_name: str) -> dict[str, dict]:
    """해당 법령의 가장 최근 판 조문."""
    doc = conn.execute(
        "select id from source_document where law_name = %s order by effective desc, id desc limit 1", (law_name,)
    ).fetchone()
    if not doc:
        return {}
    return {r["article_key"]: r for r in conn.execute(
        "select id, article_key, text from provision where document_id = %s", (doc["id"],))}


def provisions_as_of(conn, law_id: str, as_of: date) -> list[dict]:
    """기준일 조문 재현: 기준일에 시행 중이던 판의 조문."""
    return list(conn.execute(
        """select p.article_key, p.heading, p.text, p.text_hash, d.version_key
           from provision p join source_document d on d.id = p.document_id
           where d.id = (select id from source_document where law_id = %s and effective <= %s
                         order by effective desc, id desc limit 1)
             and p.effective_from <= %s
           order by p.id""",
        (law_id, as_of, as_of),
    ))


# ---------- 배치 ----------

def export_candidates(conn, stage: str, limit: int, exclude: set[int]) -> list[dict]:
    """classify: 현행 조문 중 분류 fact가 없는 것. extract: 혜택으로 분류됐는데 추출 fact가 없는 것."""
    base = """
      select p.id, p.article_key, p.text, p.text_hash, p.effective_from, d.law_name
      from provision p join source_document d on d.id = p.document_id
      where p.effective_to is null
        and not exists (select 1 from fact f where f.provision_id = p.id and f.text_hash = p.text_hash
                        and f.payload->>'stage' = %(stage)s and f.status <> 'rejected')
    """
    if stage == "extract":
        base += """ and exists (select 1 from fact f where f.provision_id = p.id and f.text_hash = p.text_hash
                               and f.payload->>'stage' = 'classify' and f.is_benefit and f.status = 'verified')"""
    elif stage != "classify":
        raise ValueError(f"{stage} 단계 내보내기는 Phase 1 범위 밖")
    rows = [r for r in conn.execute(base + " order by p.id", {"stage": stage}) if r["id"] not in exclude]
    rows = rows[:limit]
    for r in rows:
        r["delegations"] = [
            {"phrase": x["phrase"], "target_text": x["target_text"]}
            for x in conn.execute(
                """select g.phrase, t.text as target_text from delegation g left join provision t on t.id = g.target_id
                   where g.source_id = %s order by g.id""",
                (r["id"],),
            )
        ]
    return rows


def batch_key(stage: str, name: str) -> str:
    """배치 번호는 단계마다 따로 매기므로, batch.file_name(전역 unique)에는 '단계/파일명'을 넣는다."""
    return f"{stage}/{name}"


def record_batch(conn, stage: str, name: str) -> int:
    return conn.execute(
        "insert into batch (stage, file_name) values (%s, %s) returning id", (stage, batch_key(stage, name))
    ).fetchone()["id"]


def store_report(conn, report: IngestReport) -> int:
    """검증 통과한 결과를 fact로 넣고 배치 상태를 갱신한다. 넣은 fact 수를 돌려준다."""
    b = conn.execute("select id from batch where file_name = %s", (batch_key(report.stage, report.batch),)).fetchone()
    batch_id = b["id"] if b else record_batch(conn, report.stage, report.batch)
    n = 0
    for job, result in report.accepted:
        if report.stage == "classify":
            payload = {"stage": "classify", **result.model_dump(mode="json", exclude={"job_id", "extractor"})}
            is_benefit = result.is_benefit
        else:
            payload = {"stage": "extract", **result.fact.model_dump(mode="json")}
            is_benefit = result.fact.is_benefit
        cur = conn.execute(
            """insert into fact (provision_id, text_hash, batch_id, is_benefit, payload, status, extractor)
               values (%s, %s, %s, %s, %s, 'verified', %s)
               on conflict (provision_id, text_hash, extractor) do nothing""",
            (job["provision_id"], job["text_hash"], batch_id, is_benefit, Jsonb(payload), result.extractor),
        )
        n += cur.rowcount
    # 같은 조문·해시·extractor 결과가 이미 있으면 넣지 않는다. extractor의 skill 이름이 단계마다 달라야 하는 이유.
    duplicates = len(report.accepted) - n
    parts = []
    if not report.ok:
        parts.append(f"failed={len(report.failed)} missing={len(report.missing)}")
    if duplicates:
        parts.append(f"duplicate={duplicates}")
    reason = " ".join(parts) or None
    conn.execute(
        "update batch set status = %s, extractor = %s, ingested_at = now(), fail_reason = %s where id = %s",
        ("ingested" if report.accepted or report.ok else "failed", report.extractor, reason, batch_id),
    )
    return n
