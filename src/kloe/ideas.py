"""아이디어 단계: 조 클러스터 → 코드 카드 → kloe-ideate 입력, 그리고 사람 점검 파일.

- 클러스터(B1): 혜택(role=benefit) fact가 있는 조마다, 그 조의 benefit·condition fact + parent_ref로 그 조를 가리키는
  condition fact(fact_link) + 그 조의 위임 대상 조문의 fact + 같은 조의 role=none fact(배제·추징. 위임만 하는 조문의 none은 뺌).
- 카드(B2): 클러스터를 코드가 몇 줄로 렌더한 것. 저장하지 않는다 (fact의 순수 함수). LLM 카드는 점검 기록을 본 뒤에.
- ideate 입력: 렌즈마다 job 하나 = 전체 카드 + 렌즈에 맞게 코드가 고른 상세 묶음(원본 fact, 인용 포함).
  카탈로그는 길어서 job 줄에 넣지 않고 claimed/ideate/ 아래 마크다운 파일로 쓴다 (에이전트가 offset으로 나눠 읽는다).
- 점검(B4): reports/YYYY-Www.review.md. 블록마다 idea:ID, keep/drop 칸, drop 사유 태그.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

LENSES = ("combo", "time", "gap", "business")
LENS_KO = {"combo": "조합", "time": "시간", "gap": "허점", "business": "사업화"}
DETAIL_CLUSTERS = 8  # 렌즈별 상세 묶음 수 (검토자 추정 기반. 카탈로그 크기를 재고 조정)
DETAIL_PROGRAMS = 10  # 조합 렌즈에 붙이는 공고 수
DROP_TAGS = ("obvious", "wrong_fact", "infeasible", "duplicate", "other")


@dataclass
class Cluster:
    key: str  # "조세특례제한법 제16조"
    law_id: str
    article: str
    facts: list[dict] = field(default_factory=list)  # extract_fact 행 + member(역할 설명)

    @property
    def fact_ids(self) -> list[int]:
        return [f["id"] for f in self.facts]

    @property
    def sunset(self) -> date | None:
        days = [f["sunset"] for f in self.facts if f["sunset"]]
        return min(days) if days else None


def week_of(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def slot(week: str, lens: str) -> int:
    y, w = week.split("-W")
    return int(y) * 1000 + int(w) * 10 + LENSES.index(lens)


def _article(key: str) -> str:
    return key.split("-", 1)[0]


def _article_label(art: str) -> str:
    base, _, sub = art.partition("의")
    return f"제{base}조" + (f"의{sub}" if sub else "")


def clusters(conn) -> list[Cluster]:
    facts = list(conn.execute("select * from extract_fact order by id"))
    prov = {r["id"]: (r["law_id"], _article(r["article_key"])) for r in conn.execute(
        """select p.id, p.article_key, d.law_id from provision p join source_document d on d.id = p.document_id
           where p.effective_to is null""")}
    delegation_sources = {r["source_id"] for r in conn.execute("select distinct source_id from delegation")}
    by_art: dict[tuple[str, str], Cluster] = {}
    for f in facts:
        art = _article(f["article_key"])
        if f["role"] == "benefit" and (f["law_id"], art) not in by_art:
            by_art[(f["law_id"], art)] = Cluster(f"{f['law_name']} {_article_label(art)}", f["law_id"], art)
    seen: dict[tuple[str, str], set[int]] = {k: set() for k in by_art}

    def add(k, f, member):
        if k in by_art and f["id"] not in seen[k]:
            seen[k].add(f["id"])
            by_art[k].facts.append({**f, "member": member})

    for f in facts:  # 같은 조
        k = (f["law_id"], _article(f["article_key"]))
        if f["role"] == "none" and f["provision_id"] in delegation_sources:
            continue  # 위임만 하는 조문의 none은 정보가 없다 (위임 대상 fact가 대신 들어온다)
        add(k, f, "같은 조" if f["role"] != "none" else "같은 조(배제·사후)")
    by_prov: dict[int, list[dict]] = {}
    for f in facts:
        by_prov.setdefault(f["provision_id"], []).append(f)
    fid = {f["id"]: f for f in facts}
    for r in conn.execute("select fact_id, target_id from fact_link"):  # parent_ref로 이 조를 가리키는 condition
        if r["target_id"] in prov and r["fact_id"] in fid:
            add(prov[r["target_id"]], fid[r["fact_id"]], "요건(parent_ref)")
    for r in conn.execute("select source_id, target_id from delegation where target_id is not null"):
        if r["source_id"] in prov:
            for f in by_prov.get(r["target_id"], []):
                if f["role"] != "none":
                    add(prov[r["source_id"]], f, "위임 대상")
    return sorted(by_art.values(), key=lambda c: (c.law_id, c.key))


def _won(n: int) -> str:
    if n % 100_000_000 == 0:
        return f"{n // 100_000_000:,}억원"
    if n % 10_000 == 0:
        return f"{n // 10_000:,}만원"
    return f"{n:,}원"


def render_card(n: int, c: Cluster) -> str:
    main = [f for f in c.facts if f["role"] == "benefit"]
    types = sorted({f["benefit_type"] for f in main if f["benefit_type"]})
    sizes = [f for f in c.facts if f["rate"] is not None or f["cap_krw"] is not None]
    size = " · ".join(dict.fromkeys(
        (f"율 {float(f['rate']) * 100:g}%" if f["rate"] is not None else "")
        + (" " if f["rate"] is not None and f["cap_krw"] is not None else "")
        + (f"한도 {_won(f['cap_krw'])}" if f["cap_krw"] is not None else "") for f in sizes))
    head = f"### C{n} {c.key} [{','.join(types) or '?'}]" + (f" {size}" if size else "")
    if c.sunset:
        head += f" · 일몰 {c.sunset.isoformat()}"
    lines = [head]
    who = "; ".join(dict.fromkeys(x for f in main for x in (f["beneficiary"], f["trigger"]) if x))
    if who:
        lines.append(f"- 주체·계기: {who}")
    conds = list(dict.fromkeys(t["tag"] for f in c.facts for t in f["payload"].get("conditions", [])))
    if conds:
        lines.append("- 요건: " + "; ".join(conds[:12]))
    excl = list(dict.fromkeys(
        [t["tag"] for f in c.facts for t in f["payload"].get("exclusions", [])]
        + [f["payload"].get("not_benefit_reason") for f in c.facts if f["role"] == "none"]))
    excl = [e for e in excl if e]
    if excl:
        lines.append("- 배제·사후: " + "; ".join(excl[:8]))
    lines.append("- fact: " + " ".join(f"{f['id']}({f['role']},{f['article_key']})" for f in c.facts))
    return "\n".join(lines)


def _detail(c: Cluster) -> str:
    out = [f"#### {c.key}"]
    for f in c.facts:
        payload = {k: v for k, v in f["payload"].items() if k != "stage"}
        out.append(f"- fact:{f['id']} {f['law_name']} {f['article_key']} ({f['member']}) "
                   + json.dumps(payload, ensure_ascii=False))
    return "\n".join(out)


def _order(week: str, key: str) -> str:
    return hashlib.md5(f"{week}|{key}".encode()).hexdigest()


def pick_detail(lens: str, cs: list[Cluster], week: str, today: date, g3_sources: set[int]) -> list[Cluster]:
    if lens == "time":
        pool = sorted((c for c in cs if c.sunset and c.sunset >= today), key=lambda c: c.sunset)
    elif lens == "gap":
        pool = [c for c in cs if any(f["provision_id"] in g3_sources for f in c.facts)]
        pool.sort(key=lambda c: _order(week, c.key))
    elif lens == "business":
        rank = {"reward": 0, "subsidy": 1, "loan": 2, "guarantee": 2}
        pool = sorted(cs, key=lambda c: (min((rank.get(f["benefit_type"], 9) for f in c.facts), default=9),
                                          _order(week, c.key)))
    else:  # combo: 주마다 다른 표본. 요건이 붙은 묶음을 먼저 (조합할 거리가 있는 것)
        pool = sorted(cs, key=lambda c: (len(c.facts) < 2, _order(week, c.key)))
    return pool[:DETAIL_CLUSTERS]


def build_ideate(conn, work_dir: Path, today: date | None = None, lenses: tuple[str, ...] = LENSES) -> list[dict]:
    """렌즈마다 job 하나와 카탈로그 파일(claimed/ideate/catalog-<주>-<렌즈>.md)을 만든다."""
    from kloe.queue import export as qx

    today = today or date.today()
    week = week_of(today)
    cs = clusters(conn)
    if not cs:
        return []
    cards = [render_card(i, c) for i, c in enumerate(cs, 1)]
    g3 = list(conn.execute(
        """select g.id, g.source_id, g.phrase, d.law_name, p.article_key from delegation g
           join provision p on p.id = g.source_id join source_document d on d.id = p.document_id
           where g.target_id is null and p.effective_to is null order by g.id"""))
    changes = list(conn.execute(
        """select e.id, e.kind, e.article_key, e.new_provision, e.detected_at::date as day, d.law_name
           from change_event e join provision p on p.id = e.new_provision join source_document d on d.id = p.document_id
           where e.detected_at >= now() - interval '60 days' and p.effective_to is null order by e.id"""))
    programs = list(conn.execute(
        """select pf.id, p.title, p.apply_end, pf.payload from program_fact pf
           join program_version v on v.id = pf.version_id and v.superseded_at is null
           join program p on p.id = v.program_id
           where pf.status = 'verified' and (p.apply_end is null or p.apply_end >= %s)
           order by md5(%s || pf.id::text) limit %s""", (today, week, DETAIL_PROGRAMS)))
    prov_cluster = {f["provision_id"]: c.key for c in cs for f in c.facts}
    base_index: dict[str, dict] = {}
    for c in cs:
        for f in c.facts:
            base_index[f"fact:{f['id']}"] = {
                "cluster": c.key, "rate": float(f["rate"]) if f["rate"] is not None else None,
                "cap_krw": f["cap_krw"], "sunset": f["sunset"].isoformat() if f["sunset"] else None}
    for g in g3:
        base_index[f"delegation:{g['id']}"] = {"cluster": prov_cluster.get(g["source_id"], f"{g['law_name']} {g['article_key']}")}
    for e in changes:
        base_index[f"change:{e['id']}"] = {"cluster": prov_cluster.get(e["new_provision"], f"{e['law_name']} {e['article_key']}")}

    jobs = []
    out_dir = qx.stage_dir(work_dir, "claimed", "ideate")
    for lens in lenses:
        detail = pick_detail(lens, cs, week, today, {g["source_id"] for g in g3})
        index = {k: dict(v) for k, v in base_index.items()}
        for c in detail:
            for f in c.facts:
                index[f"fact:{f['id']}"]["quotes"] = [q["quote"] for q in f["payload"].get("quotes", [])]
        parts = [f"# 카탈로그 {week} · 렌즈 {LENS_KO[lens]}({lens})", "",
                 f"## 1. 전체 카드 ({len(cs)}장)", "", *cards, "",
                 f"## 2. 상세 묶음 ({len(detail)}개, 인용 포함)", "", *(_detail(c) for c in detail), ""]
        if lens == "combo" and programs:
            parts += ["## 3. 공고 (인용 포함)", ""]
            for p in programs:
                index[f"program:{p['id']}"] = {"cluster": f"공고 {p['id']}",
                                               "quotes": [q["quote"] for q in p["payload"].get("quotes", [])]}
                parts.append(f"- program:{p['id']} {p['title']} (마감 {p['apply_end'] or '미상'}) "
                             + json.dumps(p["payload"], ensure_ascii=False))
            parts.append("")
        if lens == "gap":
            parts += ["## 3. 위임 공백 (하위법령에서 대상 조문을 못 찾은 위임 문구)", ""]
            parts += [f"- delegation:{g['id']} {g['law_name']} {g['article_key']}: {g['phrase']}" for g in g3]
            parts.append("")
        if lens == "time" and changes:
            parts += ["## 3. 최근 60일 개정 이벤트", ""]
            parts += [f"- change:{e['id']} {e['law_name']} {e['article_key']} {e['kind']} ({e['day']})" for e in changes]
            parts.append("")
        name = f"catalog-{week}-{lens}.md"
        text = "\n".join(parts)
        tmp = out_dir / f".{name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.rename(out_dir / name)
        jobs.append({"job_id": f"ideate:{week}:{lens}", "lens": lens, "week": week, "slot": slot(week, lens),
                     "catalog": str((out_dir / name).resolve()), "catalog_chars": len(text),
                     "n_cards": len(cs), "detail": [c.key for c in detail], "attempt": 0, "index": index})
    return jobs


def evidence_of(idea) -> list[dict]:
    return sorted(({"kind": c.kind, "id": c.id} for c in idea.claims), key=lambda e: (e["kind"], e["id"]))


def evidence_hash(lens: str, evidence: list[dict]) -> str:
    keys = sorted({f"{e['kind']}:{e['id']}" for e in evidence})
    return hashlib.sha256((lens + "|" + ",".join(keys)).encode()).hexdigest()[:24]


# ---------- 점검 파일 ----------

def write_review_file(conn, reports_dir: Path, today: date | None = None) -> tuple[Path, int]:
    """점검 안 한 아이디어(proposed, needs_recheck)를 reports/YYYY-Www.review.md로. (경로, 블록 수)"""
    today = today or date.today()
    rows = list(conn.execute(
        """select i.* from idea i where i.status in ('proposed', 'needs_recheck')
             and not exists (select 1 from review r where r.target_kind = 'idea' and r.target_id = i.id)
           order by i.lens, i.id"""))
    labels = {r["id"]: r for r in conn.execute(
        """select f.id, d.law_name, p.article_key from fact f join provision p on p.id = f.provision_id
           join source_document d on d.id = p.document_id where f.id = any(%s)""",
        ([e["id"] for r in rows for e in r["evidence"] if e["kind"] == "fact"],))}
    out = [f"# 아이디어 점검 {week_of(today)}", "",
           "블록마다 keep 또는 drop 칸에 x를 넣는다. drop이면 사유에 태그 하나 이상: "
           + ", ".join(f"`{t}`" for t in DROP_TAGS) + ". 메모는 자유. 다 했으면 `kloe review-ingest <이 파일>`.", ""]
    for r in rows:
        p = r["payload"] or {}
        flag = " ⚠ 근거가 바뀜(다시 확인)" if r["status"] == "needs_recheck" else ""
        out += [f"## idea:{r['id']} · {LENS_KO.get(r['lens'], r['lens'])} · {r['title']}{flag}", "",
                f"> {r['summary']}", "", r["body"], "", "근거:"]
        for c in p.get("claims", []):
            where = labels.get(c["id"]) if c["kind"] == "fact" else None
            loc = f" {where['law_name']} {where['article_key']}" if where else ""
            out.append(f"- {c['kind']}:{c['id']}{loc}: {c['text']}" + (f" — \"{c['quote']}\"" if c.get("quote") else ""))
        if p.get("to_check"):
            out += ["", "확인할 것:"] + [f"- {t}" for t in p["to_check"]]
        out += ["", "- [ ] keep", "- [ ] drop  사유:", "메모:", ""]
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{week_of(today)}.review.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path, len(rows)


_BLOCK = re.compile(r"^## idea:(\d+)", flags=re.M)
_BOX = re.compile(r"^- \[([ xX])\] (keep|drop)(.*)$", flags=re.M)


@dataclass
class ReviewMark:
    idea_id: int
    verdict: str  # approve / reject
    tags: list[str]
    note: str | None


def parse_review_file(text: str) -> tuple[list[ReviewMark], list[str]]:
    """(표시된 블록, 깨진 블록 설명). 표시 안 한 블록은 건너뛴다. keep·drop 둘 다 표시, 사유 없는 drop은 깨진 것으로 센다."""
    marks, broken = [], []
    starts = list(_BLOCK.finditer(text))
    for i, m in enumerate(starts):
        block = text[m.start(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        boxes = {kind: (mark.strip().lower() == "x", rest) for mark, kind, rest in _BOX.findall(block)}
        keep, drop = boxes.get("keep", (False, ""))[0], boxes.get("drop", (False, ""))[0]
        note_m = re.search(r"^메모:(.*)$", block, flags=re.M)
        note = note_m.group(1).strip() if note_m and note_m.group(1).strip() else None
        iid = int(m.group(1))
        if "keep" not in boxes or "drop" not in boxes:
            broken.append(f"idea:{iid} keep/drop 칸이 없음")
        elif keep and drop:
            broken.append(f"idea:{iid} keep과 drop이 둘 다 표시됨")
        elif keep:
            marks.append(ReviewMark(iid, "approve", [], note))
        elif drop:
            tags = [t for t in re.findall(r"[a-z_]+", boxes["drop"][1]) if t in DROP_TAGS]
            if not tags:
                broken.append(f"idea:{iid} drop 사유 태그가 없음 ({', '.join(DROP_TAGS)})")
            else:
                marks.append(ReviewMark(iid, "reject", tags, note))
    return marks, broken
