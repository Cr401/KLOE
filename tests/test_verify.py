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


def test_sunset_before_effective():
    errs = verify(result(time_window={"sunset": "2025-12-31"}), JOB)
    assert any("일몰" in e for e in errs)


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
