"""정규식 위임 연결.

법률 조문의 "대통령령으로 정하는 …" 같은 위임 문구를 찾고, 하위법령에서
"법 제16조제1항" 처럼 그 조문을 가리키는 조문을 대상으로 연결한다.
대상을 못 찾으면 target=None 으로 남기고, 이것이 G3(위임 공백) 후보가 된다.
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


def find_phrases(text: str) -> list[DelegationPhrase]:
    out = []
    for m in DELEGATION_RE.finditer(text):
        out.append(DelegationPhrase(authority=m.group(1), phrase=m.group(0).strip(), noun=m.group(2)))
    return out


def parent_refs(text: str) -> set[str]:
    """하위법령 조문이 가리키는 상위법 키 집합. '16', '16-1', '16의2-3' 형태."""
    refs: set[str] = set()
    for m in PARENT_REF_RE.finditer(text):
        art = m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")
        refs.add(art)
        if m.group(3):
            refs.add(f"{art}-{m.group(3)}")
    return refs


def _pick_target(source: Provision, phrase: DelegationPhrase, candidates: list[tuple[Provision, set[str]]]) -> str | None:
    exact = [p for p, refs in candidates if source.article_key in refs]
    loose = [p for p, refs in candidates if source.article in refs]
    pool = exact or loose
    if not pool:
        return None
    if phrase.noun:
        named = [p for p in pool if phrase.noun in p.text]
        if named:
            pool = named
    return pool[0].article_key


def link(
    law: list[Provision],
    decree: list[Provision] | None = None,
    rule: list[Provision] | None = None,
) -> list[DelegationLink]:
    levels = {
        "decree": [(p, parent_refs(p.text)) for p in decree or []],
        "rule": [(p, parent_refs(p.text)) for p in rule or []],
    }
    links: list[DelegationLink] = []
    for src in law:
        for ph in find_phrases(src.text):
            target = _pick_target(src, ph, levels[ph.target_level])
            links.append(DelegationLink(src.article_key, ph.phrase, target, ph.target_level))
    return links
