"""기계 검증 (설계 5절). 결과 한 줄과 그 줄의 원본 job을 받아 실패 사유 목록을 돌려준다."""

from __future__ import annotations

import re
from datetime import date

from leo.models import normalize_ws
from leo.schema import ClassifyResult, ExtractResult, Quote

_UNIT = {"조": 10**12, "억": 10**8, "만": 10**4}
_SMALL = {"천": 1000, "백": 100, "십": 10}
# "2억5천만원", "3천만원", "1,000만원", "30,000,000원"
_AMOUNT_RE = re.compile(r"((?:[\d,]+\s*[천백십]?\s*[조억만]?\s*)+)원")
_CHUNK_RE = re.compile(r"([\d,]+)\s*([천백십])?\s*([조억만])?")


def parse_krw_amounts(text: str) -> set[int]:
    amounts: set[int] = set()
    for m in _AMOUNT_RE.finditer(text):
        total, any_chunk = 0, False
        for c in _CHUNK_RE.finditer(m.group(1)):
            digits = c.group(1).replace(",", "")
            if not digits:
                continue
            any_chunk = True
            n = int(digits) * _SMALL.get(c.group(2) or "", 1)
            total += n * _UNIT.get(c.group(3) or "", 1)
        if any_chunk:
            amounts.add(total)
    return amounts


def _rate_forms(rate: float) -> list[str]:
    pct = round(rate * 100, 4)
    pct_s = str(int(pct)) if pct == int(pct) else str(pct)
    return [f"100분의 {pct_s}", f"100분의{pct_s}", f"{pct_s}퍼센트", f"{pct_s}%"]


def check_quotes(quotes: list[Quote], source_text: str) -> list[str]:
    src = normalize_ws(source_text)
    errors = []
    for q in quotes:
        if normalize_ws(q.quote) not in src:
            errors.append(f"인용이 원문에 없음: field={q.field} quote={q.quote[:40]!r}")
    return errors


def check_numbers(result: ExtractResult) -> list[str]:
    size = result.fact.benefit_size
    if size is None:
        return []
    quotes = result.fact.quotes
    scoped = [q.quote for q in quotes if q.field.startswith("benefit_size")] or [q.quote for q in quotes]
    joined = normalize_ws(" ".join(scoped))
    compact = joined.replace(" ", "")
    errors = []
    if size.rate is not None and not any(f.replace(" ", "") in compact for f in _rate_forms(size.rate)):
        errors.append(f"benefit_size.rate={size.rate}이 인용 안에 없음")
    if size.cap_krw is not None and size.cap_krw not in parse_krw_amounts(joined):
        errors.append(f"benefit_size.cap_krw={size.cap_krw}이 인용 안에 없음")
    return errors


def check_time_window(result: ExtractResult, effective_from: date) -> list[str]:
    tw = result.fact.time_window
    if tw is None:
        return []
    errors = []
    if tw.sunset and tw.sunset < effective_from:
        errors.append(f"일몰({tw.sunset})이 조문 시행일({effective_from})보다 앞섬")
    if tw.sunset and tw.effective_from and tw.sunset < tw.effective_from:
        errors.append("일몰이 time_window.effective_from보다 앞섬")
    return errors


def verify(result: ClassifyResult | ExtractResult, job: dict) -> list[str]:
    text = job["text"]
    if isinstance(result, ClassifyResult):
        return check_quotes(result.quotes, text)
    errors = check_quotes(result.fact.quotes, text)
    errors += check_numbers(result)
    errors += check_time_window(result, date.fromisoformat(job["effective_from"]))
    return errors
