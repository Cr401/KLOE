"""기계 검증 (설계 5절). 결과 한 줄과 그 줄의 원본 job을 받아 실패 사유 목록을 돌려준다."""

from __future__ import annotations

import re
from datetime import date

from kloe.models import normalize_ws
from kloe.schema import AuditResult, BenefitSize, ClassifyResult, ExtractResult, FactPayload, ProgramResult, Quote

_BIG = {"조": 10**12, "억": 10**8, "만": 10**4}
_SMALL = {"천": 1000, "백": 100, "십": 10}
# "2억5천만원", "1천5백만원", "3천만원", "1,000만원", "30,000,000원"
_AMOUNT_RE = re.compile(r"((?:[\d,]*\s*[천백십조억만]\s*|[\d,]+\s*)+)원")
_TOKEN_RE = re.compile(r"([\d,]+)|([천백십])|([조억만])")


def _korean_number(s: str) -> int | None:
    """숫자+한글 단위. 작은 단위(천·백·십)는 모았다가 큰 단위(만·억·조)에 곱한다: 1천5백만 = (1000+500)×만."""
    total = small = 0
    num: int | None = None
    seen = False
    for m in _TOKEN_RE.finditer(s):
        digits, sm, big = m.groups()
        if digits is not None:
            d = digits.replace(",", "")
            if not d:
                continue
            if num is not None:
                small += num
            num, seen = int(d), True
        elif sm:
            small += (num if num is not None else 1) * _SMALL[sm]
            num, seen = None, True
        else:
            if num is not None:
                small += num
            total += (small or 1) * _BIG[big]
            small, num, seen = 0, None, True
    if num is not None:
        small += num
    return total + small if seen else None


def parse_krw_amounts(text: str) -> set[int]:
    amounts: set[int] = set()
    for m in _AMOUNT_RE.finditer(text):
        n = _korean_number(m.group(1))
        if n:
            amounts.add(n)
    return amounts


# "100분의 10", "1천분의 5", "5분의 4", "10,000분의 3"
_FRACTION_RE = re.compile(r"([\d,]*\s*[천백십만]?)\s*분의\s*([\d.]+)")


def parse_fractions(text: str) -> set[float]:
    out: set[float] = set()
    for m in _FRACTION_RE.finditer(text):
        den = _korean_number(m.group(1).replace(" ", "")) if m.group(1).strip() else None
        try:
            num = float(m.group(2))
        except ValueError:
            continue
        if den:
            out.add(num / den)
    return out


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


def check_numbers(result: ExtractResult | ProgramResult) -> list[str]:
    return check_size(result.fact.benefit_size, result.fact.quotes)


def check_size(size: BenefitSize | None, quotes: list[Quote]) -> list[str]:
    if size is None:
        return []
    scoped = [q.quote for q in quotes if q.field.startswith("benefit_size")] or [q.quote for q in quotes]
    joined = normalize_ws(" ".join(scoped))
    compact = joined.replace(" ", "")
    errors = []
    if size.rate is not None and not (
        any(f.replace(" ", "") in compact for f in _rate_forms(size.rate))
        or any(abs(v - size.rate) < 1e-9 for v in parse_fractions(joined))
    ):
        errors.append(f"benefit_size.rate={size.rate}이 인용 안에 없음")
    if size.cap_krw is not None and size.cap_krw not in parse_krw_amounts(joined):
        errors.append(f"benefit_size.cap_krw={size.cap_krw}이 인용 안에 없음")
    return errors


def check_time_window(result: ExtractResult, effective_from: date) -> list[str]:
    tw = result.fact.time_window
    if tw is None:
        return []
    # 일몰이 지난 특례도 현행 법령에 본문이 남아 있으면 그대로 기록한다 (결정 21). 지났는지는 조회할 때 본다.
    errors = []
    if tw.sunset and tw.effective_from and tw.sunset < tw.effective_from:
        errors.append("일몰이 time_window.effective_from보다 앞섬")
    return errors


def check_legal_basis(basis: list[str], source_text: str) -> list[str]:
    src = normalize_ws(source_text)
    return [f"근거법령이 원문에 없음: {b[:40]!r}" for b in basis if normalize_ws(b) not in src]


def check_audit(result: AuditResult, source_text: str) -> list[str]:
    """지적마다 근거 인용이 조문 원문에 있고, 필드 이름이 실제 fact 필드인지 본다. 인용 없는 지적은 받지 않는다."""
    src = normalize_ws(source_text)
    errors = []
    for i in result.issues:
        if i.field.split(".", 1)[0] not in FactPayload.model_fields:
            errors.append(f"감사 지적의 필드가 fact에 없음: {i.field!r}")
        if normalize_ws(i.quote) not in src:
            errors.append(f"감사 지적의 인용이 원문에 없음: field={i.field} quote={i.quote[:40]!r}")
    return errors


def verify(result: ClassifyResult | ExtractResult | ProgramResult | AuditResult, job: dict) -> list[str]:
    text = job["text"]
    if isinstance(result, AuditResult):
        return check_audit(result, text)
    if isinstance(result, ClassifyResult):
        return check_quotes(result.quotes, text)
    if isinstance(result, ProgramResult):
        errors = check_quotes(result.fact.quotes, text)
        errors += check_numbers(result)
        errors += check_legal_basis(result.fact.legal_basis, text)
        return errors
    errors = check_quotes(result.fact.quotes, text)
    errors += check_numbers(result)
    errors += check_time_window(result, date.fromisoformat(job["effective_from"]))
    if result.fact.parent_ref and normalize_ws(result.fact.parent_ref).replace(" ", "") not in normalize_ws(text).replace(" ", ""):
        errors.append(f"parent_ref가 원문에 없음: {result.fact.parent_ref[:40]!r}")
    return errors
