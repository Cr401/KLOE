"""skill 문서에 든 결과 예시가 실제 스키마와 검증을 통과하는지 확인한다. skill을 고치면 여기서 깨진다."""

import json
import re
from pathlib import Path

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
    # 문서에 적힌 benefit_type 표가 스키마의 값과 같아야 한다
    table = set(re.findall(r"^\| (\w+) \| ", md, flags=re.M)) - {"benefit_type"}
    allowed = set(ClassifyResult.model_fields["benefit_type"].annotation.__args__[0].__args__)
    assert table == allowed
