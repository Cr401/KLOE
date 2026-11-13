"""skill 문서에 든 결과 예시가 실제 스키마와 검증을 통과하는지 확인한다. skill을 고치면 여기서 깨진다."""

import json
import re
from pathlib import Path

from kloe.queue.runner import SKILL_VERSION
from kloe.schema import EXTRACTOR_PATTERN, ClassifyResult

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def _json_blocks(md: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", md, flags=re.S)]


def test_classify_example_matches_schema():
    md = (SKILLS / "kloe-classify" / "SKILL.md").read_text(encoding="utf-8")
    examples = _json_blocks(md)
    assert examples
    for ex in examples:
        ClassifyResult.model_validate(ex)
        assert re.match(EXTRACTOR_PATTERN, ex["extractor"])
    version = re.search(r"^version: (\S+)$", md, flags=re.M).group(1)
    assert all(ex["extractor"].endswith(f"kloe-classify@{version}") for ex in examples)
    assert SKILL_VERSION["classify"] == version  # 실행기가 쓰는 extractor 버전
    # 문서에 적힌 benefit_type 표가 스키마의 값과 같아야 한다
    table = set(re.findall(r"^\| (\w+) \| ", md, flags=re.M)) - {"benefit_type"}
    allowed = set(ClassifyResult.model_fields["benefit_type"].annotation.__args__[0].__args__)
    assert table == allowed


def test_extract_examples_match_schema_and_verify():
    from kloe.schema import ExtractResult
    from kloe.verify import verify

    md = (SKILLS / "kloe-extract" / "SKILL.md").read_text(encoding="utf-8")
    examples = _json_blocks(md)
    assert len(examples) == 3
    version = re.search(r"^version: (\S+)$", md, flags=re.M).group(1)
    for ex in examples:
        r = ExtractResult.model_validate(ex)
        assert ex["extractor"].endswith(f"kloe-extract@{version}")
        # 예시 인용을 모두 담은 가짜 원문으로 검증이 통과해야 한다
        text = " ".join(q.quote for q in r.fact.quotes) + " " + (r.fact.parent_ref or "")
        assert verify(r, {"text": text, "effective_from": "2020-01-01"}) == []
    assert {e["fact"].get("role") for e in examples} == {"benefit", "condition", "none"}
    table = set(re.findall(r"^\| (\w+) \| ", md, flags=re.M)) - {"benefit_type", "role", "benefit", "condition", "none"}
    allowed = set(ClassifyResult.model_fields["benefit_type"].annotation.__args__[0].__args__)
    assert table == allowed


def test_role_rules():
    import pytest
    from kloe.schema import FactPayload

    with pytest.raises(ValueError):
        FactPayload.model_validate({"is_benefit": True, "role": "none", "not_benefit_reason": "x", "benefit_type": "credit", "quotes": [{"field": "a", "quote": "b"}]})
    with pytest.raises(ValueError):
        FactPayload.model_validate({"is_benefit": False, "role": "none"})
    with pytest.raises(ValueError):
        FactPayload.model_validate({"is_benefit": False, "role": "condition"})
    FactPayload.model_validate({"is_benefit": False, "role": "none", "not_benefit_reason": "위임만"})


def test_audit_examples_match_schema_and_verify():
    from kloe.schema import AuditResult
    from kloe.verify import verify

    md = (SKILLS / "kloe-audit" / "SKILL.md").read_text(encoding="utf-8")
    examples = _json_blocks(md)
    version = re.search(r"^version: (\S+)$", md, flags=re.M).group(1)
    assert SKILL_VERSION["audit"] == version and len(examples) == 2
    for ex in examples:
        r = AuditResult.model_validate(ex)
        assert ex["extractor"].endswith(f"kloe-audit@{version}")
        text = " ".join(i.quote for i in r.issues) or "원문"
        assert verify(r, {"text": text}) == []
    bad = AuditResult.model_validate({**examples[0], "issues": [{**examples[0]["issues"][0], "field": "없는필드"}]})
    assert verify(bad, {"text": examples[0]["issues"][0]["quote"]})


def test_ideate_examples_match_schema_and_verify():
    from kloe.schema import IdeateResult
    from kloe.verify import verify

    md = (SKILLS / "kloe-ideate" / "SKILL.md").read_text(encoding="utf-8")
    examples = _json_blocks(md)
    version = re.search(r"^version: (\S+)$", md, flags=re.M).group(1)
    assert SKILL_VERSION["ideate"] == version and len(examples) == 2
    for ex in examples:
        IdeateResult.model_validate(ex)
        assert ex["extractor"].endswith(f"kloe-ideate@{version}")
    combo = IdeateResult.model_validate(examples[0])
    c1, c2 = combo.ideas[0].claims
    index = {f"fact:{c1.id}": {"cluster": "A", "rate": c1.rate, "cap_krw": None, "quotes": ["... " + c1.quote + " ..."]},
             f"fact:{c2.id}": {"cluster": "B", "rate": c2.rate, "cap_krw": None}}
    job = {"lens": "combo", "index": index}
    assert verify(combo, job) == []
    # 같은 묶음 둘이면 조합 렌즈 형태 위반, 율이 다르면 수치 위반, 인용이 근거에 없으면 인용 위반
    assert any("조합" in e for e in verify(combo, {**job, "index": {**index, f"fact:{c2.id}": {**index[f"fact:{c2.id}"], "cluster": "A"}}}))
    assert any("율" in e for e in verify(combo, {**job, "index": {**index, f"fact:{c2.id}": {**index[f"fact:{c2.id}"], "rate": 0.07}}}))
    assert any("인용" in e for e in verify(combo, {**job, "index": {**index, f"fact:{c1.id}": {**index[f"fact:{c1.id}"], "quotes": ["다른 글"]}}}))
    assert any("허점" in e for e in verify(combo, {**job, "lens": "gap"}))
    assert any("카탈로그에 없음" in e for e in verify(combo, {**job, "index": {}}))


def test_review_file_parse():
    from kloe.ideas import parse_review_file

    text = """# 점검
## idea:1 · 조합 · a
- [x] keep
- [ ] drop  사유:
메모: 좋음
## idea:2 · 시간 · b
- [ ] keep
- [X] drop  사유: obvious, wrong_fact
메모:
## idea:3 · 허점 · c
- [ ] keep
- [ ] drop  사유:
## idea:4 · 사업화 · d
- [x] keep
- [x] drop  사유: other
## idea:5 · 조합 · e
- [ ] keep
- [x] drop  사유: 그냥
"""
    marks, broken = parse_review_file(text)
    assert [(m.idea_id, m.verdict, m.tags, m.note) for m in marks] == [
        (1, "approve", [], "좋음"), (2, "reject", ["obvious", "wrong_fact"], None)]
    assert len(broken) == 2 and "idea:4" in broken[0] and "idea:5" in broken[1]
