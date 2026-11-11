"""DB에 들어가기 전의 L0 내부 자료형."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

_WS = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """공백을 한 칸으로 줄이고 앞뒤를 자른다. 해시와 인용 검증에 같은 규칙을 쓴다."""
    return _WS.sub(" ", text).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Document:
    law_id: str
    law_name: str
    law_kind: str
    version_key: str
    promulgated: date | None
    effective: date
    url: str = ""
    file_path: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class Provision:
    article_key: str  # '16', '16-1', '16의2-1' (조[의가지]-항)
    heading: str | None
    text: str
    effective_from: date
    effective_to: date | None = None

    @property
    def text_hash(self) -> str:
        return text_hash(self.text)

    @property
    def article(self) -> str:
        """항 번호를 뗀 조 키 ('16의2-1' -> '16의2')."""
        return self.article_key.split("-", 1)[0]


@dataclass
class ParsedLaw:
    document: Document
    provisions: list[Provision] = field(default_factory=list)


@dataclass(frozen=True)
class ProgramRecord:
    """공고 하나 (지원사업·장학금·창업 공고). text가 인용 검증 기준이다."""

    source: str
    external_id: str
    title: str
    text: str
    agency: str | None = None
    category: str | None = None
    url: str | None = None
    apply_start: date | None = None
    apply_end: date | None = None

    @property
    def text_hash(self) -> str:
        return text_hash(self.text)
