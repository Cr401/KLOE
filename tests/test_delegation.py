from kloe.link.delegation import find_phrases, link, parent_refs
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
