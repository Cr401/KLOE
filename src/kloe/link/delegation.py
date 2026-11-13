"""정규식 위임 연결.

법률 조문의 "대통령령으로 정하는 …" 같은 위임 문구를 찾고, 하위법령에서
"법 제16조제1항" 처럼 그 조문을 가리키는 조문을 대상으로 연결한다.
시행령 조문의 "기획재정부령으로 정하는 …"은 시행규칙에서 "영 제10조제1항"을 가리키는 조문으로 잇는다.
대상을 못 찾으면 target=None 으로 남기고, 이것이 G3(위임 공백) 후보가 된다.
정확히 같은 항을 가리키는 대상이 여럿이면 모두 잇는다. 조 단위로만 맞으면 하나만.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kloe.models import Provision

# 위임 주체: 대통령령 -> 시행령, 총리령·부령 -> 시행규칙
_AUTH = r"(대통령령|총리령|[가-힣]{1,12}부령)"
DELEGATION_RE = re.compile(_AUTH + r"(?:으로|로)\s*정(?:하는|한다|하며|하고|하여|할)(?:\s*바에\s*따라)?(?:\s+([가-힣]+))?")

# 하위법령이 상위법을 가리키는 표현. "국세기본법 제" 같은 다른 법 인용은 앞 글자가 한글이라 제외된다.
PARENT_REF_RE = re.compile(r"(?<![가-힣])법\s*제(\d+)조(?:의(\d+))?(?:\s*제(\d+)항)?")
# 시행규칙이 시행령을 가리키는 표현 ("영 제10조제1항"). "시행령 제" 처럼 앞이 한글이면 다른 법령 인용이라 제외.
DECREE_REF_RE = re.compile(r"(?<![가-힣])영\s*제(\d+)조(?:의(\d+))?(?:\s*제(\d+)항)?")


@dataclass(frozen=True)
class DelegationPhrase:
    authority: str  # 대통령령 / 총리령 / ○○부령
    phrase: str  # 문서에 나온 구간 그대로
    noun: str | None  # 위임 문구 뒤 첫 단어 ("중소기업" 등). 대상 좁히기에 씀

    @property
    def target_level(self) -> str:
        return "decree" if self.authority == "대통령령" else "rule"


@dataclass(frozen=True)
class DelegationLink:
    source_key: str
    phrase: str
    target_key: str | None
    target_level: str
    method: str = "regex"
    source_level: str = "law"  # law / decree


def find_phrases(text: str) -> list[DelegationPhrase]:
    out = []
    for m in DELEGATION_RE.finditer(text):
        out.append(DelegationPhrase(authority=m.group(1), phrase=m.group(0).strip(), noun=m.group(2)))
    return out


def parent_refs(text: str, pattern: re.Pattern = PARENT_REF_RE) -> set[str]:
    """하위법령 조문이 가리키는 상위법 키 집합. '16', '16-1', '16의2-3' 형태."""
    refs: set[str] = set()
    for m in pattern.finditer(text):
        art = m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")
        refs.add(art)
        if m.group(3):
            refs.add(f"{art}-{m.group(3)}")
    return refs


def _pick_targets(source: Provision, phrase: DelegationPhrase, candidates: list[tuple[Provision, set[str]]]) -> list[str]:
    exact = [p for p, refs in candidates if source.article_key in refs]
    loose = [p for p, refs in candidates if source.article in refs]
    pool = exact or loose
    if not pool:
        return []
    if phrase.noun:
        named = [p for p in pool if phrase.noun in p.text]
        if named:
            pool = named
    if exact:  # 같은 항을 콕 집어 가리키는 대상은 모두
        return list(dict.fromkeys(p.article_key for p in pool))
    return [pool[0].article_key]


def link(
    law: list[Provision],
    decree: list[Provision] | None = None,
    rule: list[Provision] | None = None,
) -> list[DelegationLink]:
    """법률 → 시행령·시행규칙, 시행령 → 시행규칙. (원천 단계, 원천 키, 문구, 대상)으로 중복을 없앤다."""
    decree, rule = decree or [], rule or []
    by_law = {
        "decree": [(p, parent_refs(p.text)) for p in decree],
        "rule": [(p, parent_refs(p.text)) for p in rule],
    }
    by_decree = {"rule": [(p, parent_refs(p.text, DECREE_REF_RE)) for p in rule]}
    links: dict[tuple, DelegationLink] = {}
    for level, sources, pools in (("law", law, by_law), ("decree", decree, by_decree)):
        for src in sources:
            for ph in find_phrases(src.text):
                if ph.target_level not in pools:  # 시행령이 다시 대통령령에 맡기는 경우는 잇지 않는다
                    continue
                for target in _pick_targets(src, ph, pools[ph.target_level]) or [None]:
                    lk = DelegationLink(src.article_key, ph.phrase, target, ph.target_level, source_level=level)
                    links.setdefault((level, src.article_key, ph.phrase, target), lk)
    return list(links.values())
