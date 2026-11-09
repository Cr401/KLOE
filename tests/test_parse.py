from datetime import date

import pytest

from kloe.normalize.parse import paragraph_number, parse_law_xml


def test_document_fields(fixture_bytes):
    doc = parse_law_xml(fixture_bytes("law_v1.xml")).document
    assert doc.law_id == "999001"
    assert doc.law_name == "테스트특례법"
    assert doc.law_kind == "법률"
    assert doc.effective == date(2026, 1, 1)
    assert doc.promulgated == date(2025, 12, 31)
    assert doc.version_key == "20260101-10001"


def test_provision_keys_and_text(fixture_bytes):
    provs = {p.article_key: p for p in parse_law_xml(fixture_bytes("law_v1.xml")).provisions}
    # 장 제목(전문)은 빠지고, 항 단위로 쪼개지고, 가지조문은 '16의2'
    assert list(provs) == ["16-1", "16-2", "16의2", "17-1"]
    assert provs["16-1"].heading == "벤처투자 출자에 대한 소득공제"
    assert "100분의 10" in provs["16-1"].text
    # 항이 없는 조문은 조문내용 + 호 + 목을 합친다
    body = provs["16의2"].text
    assert body.startswith("제16조의2(사후관리)")
    assert "1. 출자일부터 3년" in body and "가. 신청서의" in body
    assert provs["16-1"].article == "16" and provs["16의2"].article == "16의2"


def test_text_hash_ignores_whitespace(fixture_bytes):
    p = parse_law_xml(fixture_bytes("law_v1.xml")).provisions[0]
    from kloe.models import text_hash

    assert p.text_hash == text_hash("  " + p.text.replace(" ", "   ") + "\n")


def test_amended_version_changes_hash(fixture_bytes):
    v1 = {p.article_key: p for p in parse_law_xml(fixture_bytes("law_v1.xml")).provisions}
    v2 = {p.article_key: p for p in parse_law_xml(fixture_bytes("law_v2.xml")).provisions}
    assert v1["16-1"].text_hash != v2["16-1"].text_hash
    assert v1["16-2"].text_hash == v2["16-2"].text_hash
    assert "17-1" not in v2
    assert v2["16-1"].effective_from == date(2027, 1, 1)


@pytest.mark.parametrize("raw,expected", [("①", 1), ("⑫", 12), ("3", 3), ("제2항", 2), ("", None)])
def test_paragraph_number(raw, expected):
    assert paragraph_number(raw) == expected


def test_real_excerpt(fixture_bytes):
    parsed = parse_law_xml(fixture_bytes("real_jstl_excerpt.xml"))
    doc = parsed.document
    assert (doc.law_id, doc.law_name, doc.law_kind) == ("001584", "조세특례제한법", "법률")
    assert doc.version_key == "20260918-21467" and doc.promulgated == date(2026, 3, 17)
    provs = {p.article_key: p for p in parsed.provisions}
    # 장 제목(전문)은 빠지고, 삭제 조문은 한 줄로 남고, ①이 없는 조문은 번호 없는 <항> 래퍼의 호까지 합친다
    assert list(provs) == ["4", "5의2", "16-1", "16-2", "16-3", "16-4"]
    assert provs["4"].text.startswith("제4조 삭제")
    assert provs["5의2"].text.startswith("제5조의2(") and "\n3. 제1호와 제2호 외에" in provs["5의2"].text
    assert provs["16-1"].heading == "벤처투자조합 출자 등에 대한 소득공제"
    assert "3천만원 이하분은 100분의 100" in provs["16-1"].text and "\n6. 「자본시장과" in provs["16-1"].text
    assert provs["16-1"].effective_from == date(2026, 9, 18)


def test_rejects_non_law_xml():
    with pytest.raises(ValueError):
        parse_law_xml("<LawSearch><totalCnt>0</totalCnt></LawSearch>")


def test_rejects_entity_expansion():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><법령>&a;</법령>'
    with pytest.raises(Exception):
        parse_law_xml(bomb)
