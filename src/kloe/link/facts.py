"""추출 fact의 parent_ref를 조문 키로 푼다.

parent_ref는 추출 모델이 본문에서 글자 그대로 옮긴 상위 조문 표기다 (검증이 원문 포함을 확인함).
  "법 제29조의4제1항"        -> 같은 법령의 법률 29의4-1
  "영 제10조제1항 및 제2항"  -> 시행령 10-1, 10-2
  "제16조제1항"              -> 이 조문이 든 법령의 16-1
  "제2항"                    -> 같은 조의 2항
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ARTICLE_RE = re.compile(r"(?:(?<![가-힣])(법|영)\s*)?제(\d+)조(?:의(\d+))?")
PARAS_RE = re.compile(r"(?:\s*(?:및|·|,|와|과|또는|부터)?\s*제(\d+)항(?:\s*까지)?)+")
PARA_RE = re.compile(r"제(\d+)항")


@dataclass(frozen=True)
class Ref:
    level: str  # law / decree / same (이 조문이 든 법령)
    article: str | None  # '29의4'. None이면 같은 조
    paragraphs: tuple[int, ...] = ()


def base_law_name(name: str) -> str:
    for suffix in (" 시행령", " 시행규칙"):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return name


def _paragraphs(span: str) -> tuple[int, ...]:
    nums = [int(n) for n in PARA_RE.findall(span)]
    if "부터" in span and len(nums) == 2 and nums[0] < nums[1] <= nums[0] + 20:
        nums = list(range(nums[0], nums[1] + 1))
    return tuple(dict.fromkeys(nums))


def parse_ref(ref: str) -> list[Ref]:
    out: list[Ref] = []
    level = None
    for m in ARTICLE_RE.finditer(ref):
        level = {"법": "law", "영": "decree"}.get(m.group(1), level or "same")  # "법 제1조 및 제2조"는 앞 표기를 이어받음
        art = m.group(2) + (f"의{m.group(3)}" if m.group(3) else "")
        tail = PARAS_RE.match(ref, m.end())
        out.append(Ref(level, art, _paragraphs(tail.group(0)) if tail else ()))
    if not out and PARA_RE.search(ref):
        out.append(Ref("same", None, _paragraphs(ref)))
    return out


def resolve(ref: Ref, source_key: str, keys: set[str]) -> list[str]:
    """keys: 대상 법령의 현행 조문 키. 항이 있으면 그 항, 없거나 못 찾으면 그 조의 모든 키."""
    art = ref.article or source_key.split("-", 1)[0]
    exact = [f"{art}-{p}" for p in ref.paragraphs if f"{art}-{p}" in keys]
    if exact:
        return exact
    return sorted(k for k in keys if k == art or k.split("-", 1)[0] == art)
