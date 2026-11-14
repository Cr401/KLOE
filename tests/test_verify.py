import pytest

from kloe.schema import ExtractResult
from kloe.verify import parse_krw_amounts, verify

TEXT = ("① 거주자가 대통령령으로 정하는 중소기업에 출자하는 경우에는 출자금액의 100분의 10에 상당하는 금액을 "
        "그 과세연도의 종합소득금액에서 공제한다. 다만, 공제한도는 3천만원으로 한다.")
JOB = {"job_id": "extract:1:abc", "text": TEXT, "effective_from": "2026-01-01"}


def result(**fact_overrides):
    fact = {
        "is_benefit": True,
        "benefit_type": "deduction",
        "trigger_kind": "invest",
        "benefit_size": {"raw": "100분의 10, 한도 3천만원", "rate": 0.1, "cap_krw": 30_000_000},
        "quotes": [
            {"field": "benefit_size.rate", "quote": "출자금액의 100분의 10에 상당하는 금액"},
            {"field": "benefit_size.cap_krw", "quote": "공제한도는  3천만원으로 한다"},
        ],
        "time_window": {"sunset": "2028-12-31"},
    }
    fact.update(fact_overrides)
    return ExtractResult.model_validate({"job_id": "extract:1:abc", "extractor": "cowork:sonnet:kloe-extract@0.1", "fact": fact})


@pytest.mark.parametrize("text,amount", [
    ("3천만원", 30_000_000), ("1억원", 100_000_000), ("2억5천만원", 250_000_000),
    ("30,000,000원", 30_000_000), ("500만원", 5_000_000), ("1조 2천억원", 1_200_000_000_000),
    ("1천5백만원", 15_000_000), ("3억 2천5백만원", 325_000_000), ("1,000만원", 10_000_000),
])
def test_parse_krw(text, amount):
    assert amount in parse_krw_amounts(f"한도는 {text}으로 한다")


def test_valid_result_passes():
    assert verify(result(), JOB) == []


def test_quote_not_in_source():
    r = result(quotes=[{"field": "benefit_size", "quote": "출자금액의 100분의 20"}], benefit_size=None)
    assert any("인용이 원문에 없음" in e for e in verify(r, JOB))


def test_wrong_rate_and_cap():
    r = result(benefit_size={"raw": "x", "rate": 0.2, "cap_krw": 50_000_000})
    errs = verify(r, JOB)
    assert any("rate" in e for e in errs) and any("cap_krw" in e for e in errs)


def test_expired_sunset_is_recorded_not_rejected():
    # 결정 21: 일몰이 지난 특례도 본문이 남아 있으면 기록한다
    assert verify(result(time_window={"sunset": "2025-12-31"}), JOB) == []
    errs = verify(result(time_window={"sunset": "2025-12-31", "effective_from": "2026-03-01"}), JOB)
    assert any("일몰" in e for e in errs)  # 자기 모순은 여전히 실패
    # 조문 시행일을 time_window.effective_from에 그대로 넣은 경우는 받는다
    same = verify(result(time_window={"sunset": "2025-12-31", "effective_from": JOB["effective_from"]}), JOB)
    assert not any("일몰" in e for e in same)


def test_schema_rules():
    with pytest.raises(ValueError):
        result(benefit_type=None)  # 혜택인데 유형 없음
    with pytest.raises(ValueError):
        result(benefit_type="reward")  # reward인데 reward_terms 없음
    result(benefit_type=None, uncertain=[{"field": "benefit_type", "reason": "공제인지 감면인지 불분명"}])
    with pytest.raises(ValueError):
        ExtractResult.model_validate({"job_id": "x", "extractor": "sonnet", "fact": {"is_benefit": False}})


def test_parent_ref_must_be_in_text():
    from kloe.schema import ExtractResult
    from kloe.verify import verify

    r = ExtractResult.model_validate({"job_id": "extract:1:abc", "extractor": "cc:haiku:kloe-extract@0.1", "fact": {
        "is_benefit": True, "role": "condition", "parent_ref": "법 제99조", "benefit_type": "credit",
        "quotes": [{"field": "role", "quote": "공제한다"}]}})
    job = {"text": "법 제29조의4제1항을 적용할 때 공제한다", "effective_from": "2020-01-01"}
    assert any("parent_ref" in e for e in verify(r, job))
    r.fact.parent_ref = "법 제29조의4제1항"
    assert verify(r, job) == []


@pytest.mark.parametrize("quote,rate", [
    ("1천분의 5", 0.005), ("대통령령으로 정하는 금액의 5분의 4", 0.8), ("100분의 10", 0.1), ("1만분의 3", 0.0003),
])
def test_fraction_rates(quote, rate):
    from kloe.verify import check_size
    from kloe.schema import BenefitSize, Quote
    assert check_size(BenefitSize(raw=quote, rate=rate), [Quote(field="benefit_size.rate", quote=quote)]) == []
    assert check_size(BenefitSize(raw=quote, rate=rate / 2), [Quote(field="benefit_size.rate", quote=quote)])


def test_quote_matches_compatibility_ideograph():
    from kloe.schema import Quote
    from kloe.verify import check_quotes

    src = "영(\uf9b2)의 세율을 적용한다"  # 법령 본문의 호환 한자 零
    assert check_quotes([Quote(field="is_benefit", quote="영(\u96f6)의 세율을 적용한다")], src) == []
