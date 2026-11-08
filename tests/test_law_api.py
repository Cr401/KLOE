import pytest

from kloe.collect.law_api import LawApiClient, LawApiError, save_raw

AUTH_ERROR = (
    "<?xml version='1.0' encoding='UTF-8'?><OPEN_API><result>사용자 정보 검증에 실패하였습니다.</result>"
    "<msg>OPEN API 호출 시 사용자 검증을 위하여 정확한 서버장비의 IP주소 및 도메인주소를 등록해 주세요.</msg></OPEN_API>"
).encode()


def test_fetch_saves_raw_without_oc_in_url(tmp_path, fixture_bytes):
    calls = []

    def fake(url):
        calls.append(url)
        return fixture_bytes("law_v1.xml")

    raw = LawApiClient(oc="SECRET", fetch=fake).fetch_law("999001", tmp_path)
    assert "OC=SECRET" in calls[0] and "ID=999001" in calls[0]
    assert "SECRET" not in raw.url and "SECRET" not in str(raw.path)
    assert raw.path.read_bytes() == fixture_bytes("law_v1.xml")
    assert raw.path.parent.name == "999001"


def test_same_content_same_file(tmp_path, fixture_bytes):
    a = save_raw(fixture_bytes("law_v1.xml"), tmp_path, law_id="999001")
    b = save_raw(fixture_bytes("law_v1.xml"), tmp_path, law_id="999001")
    c = save_raw(fixture_bytes("law_v2.xml"), tmp_path, law_id="999001")
    assert a.path == b.path and a.path != c.path
    assert len(list((tmp_path / "999001").iterdir())) == 2


def test_auth_error_is_not_saved(tmp_path):
    client = LawApiClient(oc="x", fetch=lambda url: AUTH_ERROR)
    with pytest.raises(LawApiError):
        client.fetch_law("999001", tmp_path)
    assert not any(tmp_path.rglob("*.xml"))


def test_missing_oc(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOE_OC", raising=False)
    with pytest.raises(LawApiError):
        LawApiClient(fetch=lambda url: b"").fetch_law("999001", tmp_path)
