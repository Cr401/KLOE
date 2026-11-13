"""공고 API 응답 한 줄 -> ProgramRecord.

FIELDS는 (응답 필드 이름, 본문에 쓸 이름) 순서 목록이다. 본문은 "이름: 값" 줄을 이은 것이고, 에이전트 인용은 이 본문에서 검증한다.
두 소스 모두 실제 응답으로 필드 이름을 확인했다 (2026-11-12, 각 1건).
- gov24 serviceDetail: 신청기한은 자유 글이고 연도가 없는 경우가 많다("5.1.~5.31."). 그럴 땐 기간을 비워 둔다.
  법령 칸은 "조세특례제한법(제100조의10, 제0항)||…" 처럼 || 로 이어져 있다. 상세에는 상세조회URL·서비스분야가 없다.
- kstartup: 값에 HTML 엔티티(&amp;, &amp;#40;)가 섞여 온다. 날짜는 YYYYMMDD.
문의처·구비서류는 본문에 넣지 않는다 (2026-11-13). 전화번호나 서류 목록만 바뀌어도 새 판이 생겨 다시 추출되기 때문이다.
"""

from __future__ import annotations

import html
import re
from datetime import date

from kloe.models import ProgramRecord, normalize_ws

FIELDS: dict[str, list[tuple[str, str]]] = {
    "gov24": [
        ("서비스명", "서비스명"), ("소관기관명", "소관기관"), ("서비스분야", "서비스분야"), ("지원유형", "지원유형"),
        ("서비스목적", "서비스목적"), ("지원대상", "지원대상"), ("선정기준", "선정기준"), ("지원내용", "지원내용"),
        ("신청방법", "신청방법"), ("신청기한", "신청기한"), ("접수기관명", "접수기관"),
        ("법령", "근거법령"), ("자치법규", "근거자치법규"), ("행정규칙", "근거행정규칙"),
    ],
    "kstartup": [
        ("biz_pbanc_nm", "공고명"), ("intg_pbanc_biz_nm", "통합공고사업명"), ("pbanc_ntrp_nm", "공고기관"),
        ("sprv_inst", "주관기관구분"), ("biz_prch_dprt_nm", "담당부서"),
        ("supt_biz_clsfc", "지원분야"), ("pbanc_ctnt", "공고내용"), ("aply_trgt", "신청대상"),
        ("aply_trgt_ctnt", "신청대상내용"), ("aply_excl_trgt_ctnt", "제외대상"), ("prfn_matr", "우대사항"),
        ("biz_enyy", "업력"), ("biz_trgt_age", "대상연령"), ("supt_regin", "지역"),
        ("pbanc_rcpt_bgng_dt", "접수시작일"), ("pbanc_rcpt_end_dt", "접수마감일"),
        ("aply_mthd_onli_rcpt_istc", "온라인접수"), ("aply_mthd_vst_rcpt_istc", "방문접수"),
        ("aply_mthd_pssr_rcpt_istc", "우편접수"), ("aply_mthd_fax_rcpt_istc", "팩스접수"),
        ("aply_mthd_eml_rcpt_istc", "이메일접수"), ("aply_mthd_etc_istc", "기타접수"),
    ],
}

# (ID, 제목, 기관, 분야, URL 후보들)
KEYS = {
    "gov24": ("서비스ID", "서비스명", ("소관기관명", "접수기관명"), "서비스분야", ("상세조회URL", "온라인신청사이트URL")),
    "kstartup": ("pbanc_sn", "biz_pbanc_nm", ("pbanc_ntrp_nm",), "supt_biz_clsfc", ("detl_pg_url", "biz_aply_url")),
}

_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_COMPACT = re.compile(r"^(20\d{2})(\d{2})(\d{2})")


def _str(v) -> str:
    """None·"None"은 빈 값. HTML 엔티티는 두 번까지 푼다 (&amp;#40; -> &#40; -> '(')."""
    if v is None:
        return ""
    s = str(v)
    for _ in range(2):
        s = html.unescape(s)
    s = normalize_ws(s)
    return "" if s == "None" else s


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
