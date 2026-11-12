"""공고 API 응답 한 줄 -> ProgramRecord.

FIELDS는 (응답 필드 이름, 본문에 쓸 이름) 순서 목록이다. 본문은 "이름: 값" 줄을 이은 것이고, 에이전트 인용은 이 본문에서 검증한다.
gov24 필드 이름은 포털 페이지로 확인(2026-11-11). kstartup 필드 이름은 detl_pg_url 말고는 **가정**이다.
실제 응답을 처음 받으면 tests/fixtures/programs_*.json 과 여기를 맞춘다 (법제처 TAGS와 같은 방식).
"""

from __future__ import annotations

import re
from datetime import date

from kloe.models import ProgramRecord, normalize_ws

FIELDS: dict[str, list[tuple[str, str]]] = {
    "gov24": [
        ("서비스명", "서비스명"), ("소관기관명", "소관기관"), ("서비스분야", "서비스분야"), ("지원유형", "지원유형"),
        ("서비스목적", "서비스목적"), ("지원대상", "지원대상"), ("선정기준", "선정기준"), ("지원내용", "지원내용"),
        ("신청방법", "신청방법"), ("신청기한", "신청기한"), ("구비서류", "구비서류"), ("접수기관명", "접수기관"),
        ("문의처", "문의처"), ("법령", "근거법령"), ("자치법규", "근거자치법규"), ("행정규칙", "근거행정규칙"),
    ],
    "kstartup": [
        ("biz_pbanc_nm", "공고명"), ("pbanc_ntrp_nm", "공고기관"), ("sprv_inst", "주관기관"),
        ("supt_biz_clsfc", "지원분야"), ("pbanc_ctnt", "공고내용"), ("aply_trgt", "신청대상"),
        ("aply_trgt_ctnt", "신청대상내용"), ("aply_excl_trgt_ctnt", "제외대상"), ("biz_enyy", "업력"),
        ("biz_trgt_age", "대상연령"), ("supt_regin", "지역"),
        ("pbanc_rcpt_bgng_dt", "접수시작일"), ("pbanc_rcpt_end_dt", "접수마감일"), ("aply_mthd_onli_rcpt_istc", "온라인접수"),
    ],
}

# (ID, 제목, 기관, 분야, URL 후보들)
KEYS = {
    "gov24": ("서비스ID", "서비스명", ("소관기관명", "접수기관명"), "서비스분야", ("상세조회URL", "온라인신청사이트URL")),
    "kstartup": ("pbanc_sn", "biz_pbanc_nm", ("pbanc_ntrp_nm", "sprv_inst"), "supt_biz_clsfc", ("detl_pg_url",)),
}

_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_COMPACT = re.compile(r"^(20\d{2})(\d{2})(\d{2})")


def _str(v) -> str:
    return normalize_ws(str(v)) if v is not None else ""


def _first(row: dict, keys: tuple[str, ...]) -> str | None:
    return next((_str(row[k]) for k in keys if _str(row.get(k))), None)


def _to_date(y: str, m: str, d: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_dates(text: str) -> list[date]:
    """'2026.3.2', '2026-03-02', '2026년 3월 2일', '20260302' 를 읽는다. 상시·미정이면 빈 목록."""
    text = _str(text)
    m = _COMPACT.match(text)
    if m and len(text) in (8, 12, 14):
        d = _to_date(*m.groups())
        return [d] if d else []
    return [d for d in (_to_date(*g) for g in _DATE.findall(text)) if d]


def apply_window(source: str, row: dict) -> tuple[date | None, date | None]:
    if source == "kstartup":
        start = parse_dates(_str(row.get("pbanc_rcpt_bgng_dt")))
        end = parse_dates(_str(row.get("pbanc_rcpt_end_dt")))
        return (start[0] if start else None), (end[0] if end else None)
    dates = parse_dates(_str(row.get("신청기한")))
    if len(dates) >= 2:
        return dates[0], dates[-1]
    if len(dates) == 1:
        return None, dates[0]  # "~까지" 처럼 하나만 있으면 마감일로 본다
    return None, None


def parse_row(source: str, row: dict) -> ProgramRecord | None:
    id_key, title_key, agency_keys, cat_key, url_keys = KEYS[source]
    ext_id, title = _str(row.get(id_key)), _str(row.get(title_key))
    if not ext_id or not title:
        return None
    lines = [f"{label}: {_str(row[k])}" for k, label in FIELDS[source] if _str(row.get(k))]
    start, end = apply_window(source, row)
    return ProgramRecord(
        source=source, external_id=ext_id, title=title, text="\n".join(lines),
        agency=_first(row, agency_keys), category=_str(row.get(cat_key)) or None,
        url=_first(row, url_keys), apply_start=start, apply_end=end,
    )


def parse_rows(source: str, rows: list[dict]) -> list[ProgramRecord]:
    out = [parse_row(source, r) for r in rows]
    return [r for r in out if r is not None]
