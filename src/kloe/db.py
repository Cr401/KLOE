"""Postgres 적재. DB에는 코드만 쓴다 (에이전트 결과는 ingest 검증을 통과한 것만)."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from kloe.link.delegation import DelegationLink
from kloe.models import ParsedLaw, ProgramRecord
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
    carry_facts(conn)
    return doc_id, ids, True


def carry_facts(conn) -> int:
    """같은 법령·조문 키·본문 해시를 가진 현행 조문으로 verified fact를 복사한다. 넣은 수를 돌려준다.

    개정판은 조문을 전부 새 행으로 넣으므로, 이게 없으면 안 바뀐 조문까지 법령 전체가 다시 분류·추출 큐로 나간다.
    멱등이라 몇 번 불러도 된다. 판 적재 직후와 내보내기 직전에 부른다: 개정판이 들어온 뒤에 옛 조문으로
    나갔던 배치 결과가 가져와지면, 그 fact도 다음 내보내기 전에 새 조문으로 넘어간다.
    위임 대상(하위 법령) 본문이 바뀌었는지는 보지 않는다 (추출 맥락이 옛것일 수 있음, 개선안 검토에서 받아들인 위험)."""
    cur = conn.execute(
        """insert into fact (provision_id, text_hash, batch_id, is_benefit, payload, status, extractor, carried_from)
           select np.id, f.text_hash, f.batch_id, f.is_benefit, f.payload, 'verified', f.extractor,
                  coalesce(f.carried_from, f.id)
           from fact f
           join provision op on op.id = f.provision_id
           join source_document od on od.id = op.document_id
           join provision np on np.article_key = op.article_key and np.text_hash = f.text_hash
                            and np.id <> op.id and np.effective_to is null
           join source_document nd on nd.id = np.document_id and nd.law_id = od.law_id
           where f.status = 'verified' and f.text_hash = op.text_hash
           on conflict (provision_id, text_hash, extractor) do nothing""")
    return cur.rowcount


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


def store_links(conn, source_ids: dict[str, dict[str, int]], target_ids: dict[str, dict[str, int]],
                links: list[DelegationLink]) -> int:
    """source_ids: {'law': {article_key: id}, 'decree': {...}}, target_ids: {'decree': {...}, 'rule': {...}}.
    (원천, 문구)마다 대상 집합을 새로 맞춘다: 없어진 대상은 지우고 새 대상은 넣는다. 새로 넣은 행 수를 돌려준다."""
    wanted: dict[tuple[int, str], set[int | None]] = {}
    methods: dict[tuple[int, str], str] = {}
    for lk in links:
        src = source_ids.get(lk.source_level, {}).get(lk.source_key)
        if src is None:
            continue
        tgt = target_ids.get(lk.target_level, {}).get(lk.target_key) if lk.target_key else None
        wanted.setdefault((src, lk.phrase), set()).add(tgt)
        methods[(src, lk.phrase)] = lk.method
    n = 0
    for (src, phrase), targets in wanted.items():
        if len(targets) > 1:
            targets.discard(None)
        have = {r["target_id"] for r in conn.execute(
            "select target_id from delegation where source_id = %s and phrase = %s", (src, phrase))}
        for gone in have - targets:
            conn.execute("delete from delegation where source_id = %s and phrase = %s and target_id is not distinct from %s",
                         (src, phrase, gone))
        for new in targets - have:
            conn.execute("insert into delegation (source_id, target_id, phrase, method) values (%s, %s, %s, %s)",
                         (src, new, phrase, methods[(src, phrase)]))
            n += 1
    return n


def current_provisions(conn, law_name: str) -> dict[str, dict]:
    """해당 법령의 현행 조문. 내보내기와 같은 기준(effective_to is null)으로, 이름이 아니라 law_id로 묶는다
    (법령명이 바뀐 판이 섞여 있어도 같은 법령)."""
    doc = conn.execute(
        "select law_id from source_document where law_name = %s order by effective desc, id desc limit 1", (law_name,)
    ).fetchone()
    if not doc:
        return {}
    return {r["article_key"]: r for r in conn.execute(
        """select p.id, p.article_key, p.text from provision p join source_document d on d.id = p.document_id
           where d.law_id = %s and p.effective_to is null order by d.effective, d.id""", (doc["law_id"],))}


def link_facts(conn) -> int:
    """verified 추출 fact 중 parent_ref가 있고 아직 안 이은 것을 현행 조문으로 잇는다 (fact_link). 멱등."""
    from kloe.link.facts import base_law_name, parse_ref, resolve

    rows = conn.execute(
        """select f.id, f.payload->>'parent_ref' as ref, p.id as pid, p.article_key, d.law_name
           from fact f join provision p on p.id = f.provision_id join source_document d on d.id = p.document_id
           where f.stage = 'extract' and f.status = 'verified' and p.effective_to is null
             and coalesce(f.payload->>'parent_ref', '') <> ''
             and not exists (select 1 from fact_link l where l.fact_id = f.id)""").fetchall()
    cache: dict[str, dict[str, dict]] = {}
    n = 0
    for r in rows:
        base = base_law_name(r["law_name"])
        for ref in parse_ref(r["ref"]):
            name = {"law": base, "decree": f"{base} 시행령"}.get(ref.level, r["law_name"])
            if name not in cache:
                cache[name] = current_provisions(conn, name)
            provs = cache[name]
            for key in resolve(ref, r["article_key"], set(provs)):
                if provs[key]["id"] == r["pid"]:
                    continue
                n += conn.execute(
                    "insert into fact_link (fact_id, target_id, ref) values (%s, %s, %s) on conflict do nothing",
                    (r["id"], provs[key]["id"], r["ref"])).rowcount
    conn.commit()
    return n


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


# ---------- 공고 (지원사업·장학금·창업) ----------

def store_programs(conn, records: list[ProgramRecord], *, file_path: str, sha256: str) -> tuple[int, int]:
    """공고를 넣거나 갱신한다. 본문이 바뀌면 새 판을 만들고 이전 판과 그 fact를 stale로 돌린다.
    (새 공고 수, 새 판 수)를 돌려준다."""
    new_programs = new_versions = 0
    for r in records:
        row = conn.execute(
            """insert into program (source, external_id, title, agency, category, url, apply_start, apply_end)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (source, external_id) do update set
                 title = excluded.title, agency = excluded.agency, category = excluded.category, url = excluded.url,
                 apply_start = excluded.apply_start, apply_end = excluded.apply_end, last_seen = now()
               returning id, (xmax = 0) as inserted""",
            (r.source, r.external_id, r.title, r.agency, r.category, r.url, r.apply_start, r.apply_end),
        ).fetchone()
        pid = row["id"]
        new_programs += row["inserted"]
        current = conn.execute(
            "select id, text_hash from program_version where program_id = %s and superseded_at is null", (pid,)
        ).fetchone()
        if current and current["text_hash"] == r.text_hash:
            continue
        if current:
            conn.execute("update program_version set superseded_at = now() where id = %s", (current["id"],))
            conn.execute("update program_fact set status = 'stale' where version_id = %s and status <> 'rejected'",
                         (current["id"],))
        old = conn.execute(
            "select id from program_version where program_id = %s and text_hash = %s", (pid, r.text_hash)
        ).fetchone()
        if old:  # 예전 본문으로 되돌아옴: 그 판을 다시 현행으로
            conn.execute("update program_version set superseded_at = null where id = %s", (old["id"],))
            conn.execute("update program_fact set status = 'verified' where version_id = %s and status = 'stale'",
                         (old["id"],))
            continue
        conn.execute(
            """insert into program_version (program_id, text, text_hash, file_path, sha256)
               values (%s, %s, %s, %s, %s)""",
            (pid, r.text, r.text_hash, file_path, sha256),
        )
        new_versions += 1
    return new_programs, new_versions


# 소스의 가장 최근 수집보다 이만큼 앞서 마지막으로 보인 공고는 목록에서 사라진 것으로 본다 (K-Startup은 모집중만 준다).
# 수집이 며칠 실패해도 소스별 최근 수집 기준이라 전부 퇴출되지는 않는다.
RETIRE_AFTER = "3 days"

_LIVE = f"""(p.apply_end is null or p.apply_end >= %(today)s)
   and p.last_seen >= (select max(q.last_seen) from program q where q.source = p.source) - interval '{RETIRE_AFTER}'"""

# 내보내기 순서: K-Startup(적고 마감이 분명) → 마감일 있는 것(이른 순) → 지원유형(현금·감면·융자 → 이용권·현물 → 나머지).
# 거르지 않고 순서만 정한다. 지원유형 순위는 이득이 큰 쪽을 먼저 보려는 추정이다.
_PROGRAM_ORDER = r"""
   (p.source <> 'kstartup'), (p.apply_end is null), p.apply_end,
   case when v.text ~ '지원유형: [^\n]*(현금|감면|융자|세제)' then 0
        when v.text ~ '지원유형: [^\n]*(이용권|현물)' then 1 else 2 end,
   v.id"""


def export_program_candidates(conn, limit: int, exclude: set[int], today: date | None = None) -> list[dict]:
    """현행 판 중 마감이 안 지났고(마감 미상 포함), 목록에서 사라지지 않았고, 추출 fact가 없는 것."""
    rows = conn.execute(
        f"""select v.id as version_id, v.text, v.text_hash, p.source, p.title, p.apply_end
           from program_version v join program p on p.id = v.program_id
           where v.superseded_at is null and {_LIVE}
             and not exists (select 1 from program_fact f where f.version_id = v.id and f.status <> 'rejected')
           order by {_PROGRAM_ORDER}""",
        {"today": today or date.today()},
    )
    return [r for r in rows if r["version_id"] not in exclude][:limit]


def open_programs(conn, today: date | None = None) -> list[dict]:
    """마감 전이고 목록에서 사라지지 않은 공고와 추출 결과 (kloe programs)."""
    return list(conn.execute(
        f"""select p.source, p.external_id, p.title, p.agency, p.apply_end, p.url, f.payload
           from program p
           join program_version v on v.program_id = p.id and v.superseded_at is null
           left join lateral (select payload from program_fact pf where pf.version_id = v.id and pf.status = 'verified'
                              order by pf.id desc limit 1) f on true
           where {_LIVE}
           order by p.apply_end nulls last, p.id""",
        {"today": today or date.today()},
    ))


# ---------- 추출 감사 ----------

# 표본 층: role별로 같은 몫 + uncertain이 있는 것 조금. 합이 1.
AUDIT_STRATA = (("none", 0.3), ("condition", 0.3), ("benefit", 0.3), ("uncertain", 0.1))


def export_audit_candidates(conn, sample: int, exclude: set[int], law_filter: str | None = None) -> list[dict]:
    """감사 표본: 현행 조문의 verified 추출 fact 중 아직 감사하지 않은 것을 층마다 골고루 고른다.
    순서는 md5(fact id)라 실행마다 같고, 먼저 적재된 법령에 몰리지 않는다. law_filter는 법령명 부분 문자열 (예: 시행)."""
    rows = list(conn.execute(
        """select f.id as fact_id, f.text_hash, f.payload, p.article_key, p.text, d.law_name
           from fact f join provision p on p.id = f.provision_id join source_document d on d.id = p.document_id
           where f.status = 'verified' and f.payload->>'stage' = 'extract' and p.effective_to is null
             and p.text_hash = f.text_hash and f.carried_from is null
             and not exists (select 1 from audit a where a.fact_id = f.id)
             and (%(lf)s::text is null or position(%(lf)s::text in d.law_name) > 0)
           order by md5(f.id::text)""",
        {"lf": law_filter}))
    rows = [r for r in rows if r["fact_id"] not in exclude]

    def stratum(r):
        if r["payload"].get("uncertain"):
            return "uncertain"
        return r["payload"].get("role") or "benefit"

    picked: list[dict] = []
    for name, share in AUDIT_STRATA:
        picked += [r for r in rows if stratum(r) == name][: round(sample * share)]
    rest = [r for r in rows if r not in picked]  # 어떤 층이 모자라면 남은 것으로 채운다
    return (picked + rest)[:sample]


def audit_summary(conn) -> dict:
    """감사 결과 집계: 전체·ok 수, 필드×방향별 지적 수, 놓친(lost) 지적 목록."""
    rows = list(conn.execute(
        """select a.ok, a.payload, a.extractor, p.article_key, d.law_name, f.payload as fact
           from audit a join fact f on f.id = a.fact_id join provision p on p.id = f.provision_id
           join source_document d on d.id = p.document_id order by d.law_name, p.id"""))
    by_field: dict[tuple[str, str], int] = {}
    lost = []
    for r in rows:
        for i in r["payload"].get("issues", []):
            key = (i["field"].split(".", 1)[0], i["direction"])
            by_field[key] = by_field.get(key, 0) + 1
            if i["direction"] == "lost":
                lost.append({"law_name": r["law_name"], "article_key": r["article_key"],
                             "role": r["fact"].get("role"), **i})
    return {"total": len(rows), "ok": sum(r["ok"] for r in rows), "by_field": by_field, "lost": lost,
            "extractors": sorted({r["extractor"] for r in rows})}


# ---------- 배치 ----------

def export_candidates(conn, stage: str, limit: int, exclude: set[int], recheck: str | None = None) -> list[dict]:
    """classify: 현행 조문 중 분류 fact가 없는 것. extract: 혜택으로 분류됐는데 추출 fact가 없는 것.

    recheck(skill 버전, classify만): false로 분류된 위임 항 중 같은 조의 다른 항이 true인 것을,
    그 버전의 결과가 아직 없으면 다시 내보낸다. 놓친 혜택은 다음 단계에서 되살릴 수 없어서다.
    """
    base = """
      select p.id, p.article_key, p.text, p.text_hash, p.effective_from, d.law_name
      from provision p join source_document d on d.id = p.document_id
      where p.effective_to is null
    """
    cls = "f.provision_id = p.id and f.text_hash = p.text_hash and f.payload->>'stage' = 'classify' and f.status = 'verified'"
    if recheck is None:
        base += """ and not exists (select 1 from fact f where f.provision_id = p.id and f.text_hash = p.text_hash
                                    and f.payload->>'stage' = %(stage)s and f.status <> 'rejected')"""
    elif stage == "classify":
        base += f"""
        and exists (select 1 from fact f where {cls} and not f.is_benefit
                    and (p.text ~ '(대통령령|재정경제부령)으로 정한다' or f.payload->>'reason' ~ '위임'))
        and not exists (select 1 from fact f where {cls} and f.is_benefit)
        and not exists (select 1 from fact f where {cls} and f.extractor like %(ver)s)
        and exists (select 1 from provision s join fact f on f.provision_id = s.id and f.text_hash = s.text_hash
                    where f.payload->>'stage' = 'classify' and f.status = 'verified' and f.is_benefit
                      and s.document_id = p.document_id and s.effective_to is null
                      and split_part(s.article_key, '-', 1) = split_part(p.article_key, '-', 1))"""
    else:
        raise ValueError("recheck은 classify 단계만")
    if stage == "extract":
        base += """ and exists (select 1 from fact f where f.provision_id = p.id and f.text_hash = p.text_hash
                               and f.payload->>'stage' = 'classify' and f.is_benefit and f.status = 'verified')"""
    elif stage != "classify":
        raise ValueError(f"{stage} 단계 내보내기는 Phase 1 범위 밖")
    rows = [r for r in conn.execute(base + " order by p.id", {"stage": stage, "ver": f"%kloe-classify@{recheck}"}) if r["id"] not in exclude]
    rows = rows[:limit]
    by_source: dict[int, list[dict]] = {r["id"]: [] for r in rows}
    for x in conn.execute(  # 조문마다 따로 묻지 않고 한 번에
        """select g.source_id, g.phrase, t.text as target_text from delegation g left join provision t on t.id = g.target_id
           where g.source_id = any(%s) order by g.id""",
        (list(by_source),),
    ):
        by_source[x["source_id"]].append({"phrase": x["phrase"], "target_text": x["target_text"]})
    for r in rows:
        r["delegations"] = by_source[r["id"]]
    return rows


def sync_dropped(conn, work_dir: Path, stage: str) -> int:
    """failed/<stage>/dropped.jsonl을 dropped_job으로 옮기고 파일은 dropped-log.jsonl 뒤에 붙인다 (멱등)."""
    from kloe.queue import export as qx

    path = qx.stage_dir(work_dir, "failed", stage) / qx.DROPPED
    if not path.exists():
        return 0
    key = qx.TARGET_KEY.get(stage, "provision_id")
    rows = qx.read_jsonl(path)
    n = 0
    for j in rows:
        n += conn.execute(
            """insert into dropped_job (stage, target_id, text_hash, reasons) values (%s, %s, %s, %s)
               on conflict do nothing""",
            (stage, int(j[key]), j.get("text_hash", ""), Jsonb(j.get("drop_reasons", []))),
        ).rowcount
    conn.commit()
    with open(path.with_name(qx.DROPPED_LOG), "a", encoding="utf-8") as f:
        f.write(path.read_text(encoding="utf-8"))
    path.unlink()
    return n


def dropped_ids(conn, stage: str) -> set[int]:
    return {r["target_id"] for r in conn.execute("select target_id from dropped_job where stage = %s", (stage,))}


def undrop(conn, stage: str) -> int:
    n = conn.execute("delete from dropped_job where stage = %s", (stage,)).rowcount
    conn.commit()
    return n


def max_batch_number(conn, stage: str) -> int:
    """이 단계에 기록된 가장 큰 배치 번호. work/를 지워도 새 배치 이름이 옛 기록과 겹치지 않게 한다."""
    row = conn.execute(
        r"select max(substring(file_name from 'batch-(\d+)\.jsonl$')::int) as n from batch where stage = %s", (stage,)
    ).fetchone()
    return row["n"] or 0


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
        if report.stage == "audit":
            cur = conn.execute(
                """insert into audit (fact_id, batch_id, ok, payload, extractor)
                   values (%s, %s, %s, %s, %s) on conflict (fact_id, extractor) do nothing""",
                (job["fact_id"], batch_id, result.ok,
                 Jsonb(result.model_dump(mode="json", exclude={"job_id", "extractor"})), result.extractor),
            )
            n += cur.rowcount
            continue
        if report.stage == "program":
            cur = conn.execute(
                """insert into program_fact (version_id, batch_id, payload, status, extractor)
                   values (%s, %s, %s, 'verified', %s) on conflict (version_id, extractor) do nothing""",
                (job["version_id"], batch_id, Jsonb(result.fact.model_dump(mode="json")), result.extractor),
            )
            n += cur.rowcount
            continue
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
