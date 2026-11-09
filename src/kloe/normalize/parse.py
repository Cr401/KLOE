"""법제처 Open API 법령 본문 XML -> Document + Provision 목록.

태그 이름은 2026-11-09 조세특례제한법(001584)·시행령(004920) 실제 응답으로 확인했다 (TAGS 전부 맞음).
실제 구조에서 추정과 달랐던 점:
- ①이 없는 조문의 호는 조문단위 바로 아래가 아니라 번호 없는 <항> 래퍼(항번호·항내용 없음) 안에 온다.
- 가지조문이 아니면 <조문가지번호> 태그 자체가 없다. 가지 호는 <호가지번호>가 따로 있고 호내용이 '10의2.'로 시작한다.
- 장·절 제목(조문여부=전문)도 조문번호가 붙는다(다음 조문 번호). 삭제 조문은 조문내용 '제4조 삭제 <…>' 한 줄로 온다.
- 본문에 '<개정 …>' 주석, 표(┌…┐), <img> 텍스트가 섞여 있다. 그대로 원문으로 둔다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # 타입 표기용

from defusedxml.ElementTree import fromstring as safe_fromstring
from datetime import date

from kloe.models import Document, ParsedLaw, Provision

TAGS = {
    "basic": "기본정보",
    "law_id": "법령ID",
    "law_name": "법령명_한글",
    "law_kind": "법종구분",
    "promulgated": "공포일자",
    "promulgation_no": "공포번호",
    "effective": "시행일자",
    "articles": "조문",
    "article": "조문단위",
    "article_no": "조문번호",
    "article_branch": "조문가지번호",
    "article_kind": "조문여부",  # '조문' 또는 '전문'(장·절 제목)
    "article_title": "조문제목",
    "article_effective": "조문시행일자",
    "article_text": "조문내용",
    "paragraph": "항",
    "paragraph_no": "항번호",
    "paragraph_text": "항내용",
    "item": "호",
    "item_text": "호내용",
    "subitem": "목",
    "subitem_text": "목내용",
}

_CIRCLED = {chr(0x2460 + i): i + 1 for i in range(20)}  # ①..⑳
_DIGITS = re.compile(r"\d+")


def _yyyymmdd(value: str | None) -> date | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) != 8:
        return None
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def paragraph_number(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw[0] in _CIRCLED:
        return _CIRCLED[raw[0]]
    m = _DIGITS.search(raw)
    return int(m.group()) if m else None


def _items_text(parent: ET.Element) -> list[str]:
    lines: list[str] = []
    for item in parent.findall(TAGS["item"]):
        t = _text(item, TAGS["item_text"])
        if t:
            lines.append(t)
        for sub in item.findall(TAGS["subitem"]):
            st = _text(sub, TAGS["subitem_text"])
            if st:
                lines.append(st)
    return lines


def parse_law_xml(xml: bytes | str, *, url: str = "", file_path: str = "", sha256: str = "") -> ParsedLaw:
    root = safe_fromstring(xml)
    basic = root.find(TAGS["basic"])
    if basic is None:
        raise ValueError(f"<{TAGS['basic']}> 없음: 법령 본문 XML이 아니다")

    effective = _yyyymmdd(_text(basic, TAGS["effective"]))
    if effective is None:
        raise ValueError("시행일자 없음")
    promulgated = _yyyymmdd(_text(basic, TAGS["promulgated"]))
    prom_no = _text(basic, TAGS["promulgation_no"])

    doc = Document(
        law_id=_text(basic, TAGS["law_id"]),
        law_name=_text(basic, TAGS["law_name"]),
        law_kind=_text(basic, TAGS["law_kind"]),
        # 같은 법령의 판을 구분하는 키: 시행일 + 공포번호
        version_key=f"{effective:%Y%m%d}-{prom_no or 'na'}",
        promulgated=promulgated,
        effective=effective,
        url=url,
        file_path=file_path,
        sha256=sha256,
    )
    if not doc.law_id or not doc.law_name:
        raise ValueError("법령ID 또는 법령명 없음")

    provisions: list[Provision] = []
    seen: set[str] = set()
    articles = root.find(TAGS["articles"])
    for art in articles.findall(TAGS["article"]) if articles is not None else []:
        if _text(art, TAGS["article_kind"]) != "조문":
            continue  # 장·절 제목
        no = _text(art, TAGS["article_no"])
        branch = _text(art, TAGS["article_branch"])
        art_key = f"{no}의{branch}" if branch and branch != "0" else no
        heading = _text(art, TAGS["article_title"]) or None
        eff = _yyyymmdd(_text(art, TAGS["article_effective"])) or effective
        head_text = _text(art, TAGS["article_text"])

        all_paras = art.findall(TAGS["paragraph"])
        paragraphs = [p for p in all_paras if p.find(TAGS["paragraph_no"]) is not None]
        if not paragraphs:
            # ①이 없는 조문: 호는 번호 없는 <항> 래퍼 안에 있다
            body = "\n".join([head_text, *(t for p in all_paras for t in _items_text(p))]).strip()
            rows = [(art_key, body)]
        else:
            rows = []
            for i, para in enumerate(paragraphs, start=1):
                n = paragraph_number(_text(para, TAGS["paragraph_no"])) or i
                lines = [_text(para, TAGS["paragraph_text"]), *_items_text(para)]
                if n == 1 and head_text and not lines[0]:
                    lines[0] = head_text  # 항이 하나뿐이고 본문이 조문내용에만 있는 경우
                rows.append((f"{art_key}-{n}", "\n".join(l for l in lines if l)))

        for key, body in rows:
            if not body or key in seen:
                continue
            seen.add(key)
            provisions.append(Provision(article_key=key, heading=heading, text=body, effective_from=eff))

    return ParsedLaw(document=doc, provisions=provisions)
