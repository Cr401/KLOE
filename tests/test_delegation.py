from datetime import date

from kloe.link.delegation import find_phrases, link, parent_refs
from kloe.link.facts import Ref, parse_ref, resolve
from kloe.models import Provision
from kloe.normalize.parse import parse_law_xml


def test_find_phrases():
    phs = find_phrases("거주자가 대통령령으로 정하는 중소기업에 출자하고 기획재정부령으로 정하는 신청서를 낸다. 세부 사항은 총리령으로 정한다.")
    assert [(p.authority, p.noun, p.target_level) for p in phs] == [
        ("대통령령", "중소기업에", "decree"),
        ("기획재정부령", "신청서를", "rule"),
        ("총리령", None, "rule"),
    ]


def test_parent_refs_excludes_other_laws():
    assert parent_refs('법 제16조제1항에서 "대통령령으로 정하는 중소기업"이란') == {"16", "16-1"}
    assert parent_refs("법 제16조의2에 따른") == {"16의2"}
    assert parent_refs("국세기본법 제17조에 따른 기간") == set()


def test_link_fixture(fixture_bytes):
    law = parse_law_xml(fixture_bytes("law_v1.xml")).provisions
    decree = parse_law_xml(fixture_bytes("decree_v1.xml")).provisions
    links = {(lk.source_key, lk.target_level): lk for lk in link(law, decree, rule=[])}
    assert links[("16-1", "decree")].target_key == "10-1"
    assert links[("16-2", "rule")].target_key is None  # 시행규칙 없음 -> G3 후보
    assert links[("17-1", "decree")].target_key is None  # 시행령에 대응 조문 없음 -> G3 후보
    assert len(links) == 3


def P(key, text):
    return Provision(article_key=key, heading=None, text=text, effective_from=date(2026, 1, 1))


def test_decree_to_rule_and_multiple_exact_targets():
    law = [P("16-1", "대통령령으로 정하는 중소기업에 출자하면 공제한다.")]
    decree = [P("10-1", "법 제16조제1항에서 정하는 중소기업이란 기획재정부령으로 정하는 기업을 말한다."),
              P("11-1", "법 제16조제1항에 따른 중소기업 출자 계산은 다음과 같다."),
              P("12-1", "시행령 제10조제1항은 다른 법령 인용이다. 대통령령으로 정하는 것은 잇지 않는다.")]
    rule = [P("5-1", "영 제10조제1항에서 기획재정부령으로 정하는 기업은 별표와 같다."),
            P("6-1", "영 제10조에 따른 서식")]
    got = {(lk.source_level, lk.source_key, lk.target_key) for lk in link(law, decree, rule)}
    assert got == {("law", "16-1", "10-1"), ("law", "16-1", "11-1"),  # 같은 항을 콕 집은 대상은 모두
                   ("decree", "10-1", "5-1")}                           # 시행령 -> 시행규칙 (조 단위 6-1은 exact가 있어 빠짐)
    assert len(link(law, decree, rule)) == 3


def test_parse_and_resolve_parent_ref():
    assert parse_ref("법 제29조의4제1항 및 제2항") == [Ref("law", "29의4", (1, 2))]
    assert parse_ref("영 제10조제1항부터 제3항까지") == [Ref("decree", "10", (1, 2, 3))]
    assert parse_ref("제16조") == [Ref("same", "16", ())]
    assert parse_ref("제2항") == [Ref("same", None, (2,))]
    assert parse_ref("국세기본법 제17조") == [Ref("same", "17", ())]  # 앞이 한글이면 법|영 표기로 보지 않음
    keys = {"16", "16-1", "16-2", "16의2"}
    assert resolve(Ref("same", None, (2,)), "16-1", keys) == ["16-2"]
    assert resolve(Ref("law", "16", (9,)), "1", keys) == ["16", "16-1", "16-2"]  # 없는 항이면 조 전체
