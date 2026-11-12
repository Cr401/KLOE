"""공고 수집·정규화·추출 검증 (DB 없이). fixture는 합성이다."""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from agent_sim import run_agent
from kloe.collect.programs import ProgramApiClient, ProgramApiError, parse_page
from kloe.normalize.program import parse_dates, parse_rows
from kloe.queue import export as qx
from kloe.queue import ingest as qi
from kloe.queue.runner import SKILLS, extractor
from kloe.schema import EXTRACTOR_PATTERN, ProgramResult
from kloe.verify import verify

FIX = Path(__file__).parent / "fixtures"
SKILL = Path(__file__).resolve().parents[1] / "skills" / "kloe-extract-program" / "SKILL.md"


def rows(name):
    return parse_page((FIX / name).read_bytes())[0]


class FakeFetch:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def __call__(self, url):
        self.urls.append(url)
        return (FIX / self.pages[len(self.urls) - 1]).read_bytes()


def test_pages_follow_total_and_mask_key(tmp_path):
    fetch = FakeFetch(["programs_gov24_p1.json", "programs_gov24_p2.json"])
    client = ProgramApiClient(key="SECRET-KEY", fetch=fetch)
    pages = list(client.pages("gov24", tmp_path, per_page=2))
    assert [len(p.rows) for p in pages] == [2, 1] and len(fetch.urls) == 2  # totalCount 3 에서 멈춤
    assert "serviceKey=SECRET-KEY" in fetch.urls[0] and "page=2" in fetch.urls[1]
    assert all("SECRET" not in p.url and "serviceKey=%2A%2A%2A" in p.url for p in pages)
    saved = list((tmp_path / "programs" / "gov24").glob("*.json"))
    assert len(saved) == 2 and all("SECRET" not in f.read_text(encoding="utf-8") for f in saved)


def test_missing_key_and_error_response(tmp_path):
    with pytest.raises(ProgramApiError, match="KLOE_DATA_GO_KR_KEY"):
        next(ProgramApiClient(key="", fetch=FakeFetch([])).pages("gov24", tmp_path))
    with pytest.raises(ProgramApiError, match="JSON이 아닌"):
        parse_page((FIX / "programs_error_auth.xml").read_bytes())
    with pytest.raises(ProgramApiError, match="API 오류"):
        parse_page('{"code": -4, "msg": "등록되지 않은 인증키 입니다."}'.encode())


def test_parse_dates():
    assert parse_dates("2026.02.26 ~ 2027.02.25") == [date(2026, 2, 26), date(2027, 2, 25)]
    assert parse_dates("2025년 3월 1일 ~ 2025년 3월 31일") == [date(2025, 3, 1), date(2025, 3, 31)]
    assert parse_dates("20270228") == [date(2027, 2, 28)]
    assert parse_dates("상시신청") == [] and parse_dates("2026.13.40") == []


def test_normalize_gov24_and_kstartup():
    g = parse_rows("gov24", rows("programs_gov24_p1.json"))
    assert [r.external_id for r in g] == ["T00000000001", "T00000000002"]
    youth = g[0]
    assert youth.apply_start == date(2026, 2, 26) and youth.apply_end == date(2027, 2, 25)
    assert youth.agency == "테스트부" and youth.url == "https://example.invalid/apply/1"
    assert youth.text.splitlines()[0] == "서비스명: 테스트 청년 월세 지원"
    assert "근거법령: 테스트주거지원법(제21조, 제0항)||테스트특례법(제16조, 제1항)" in youth.text
    assert "수정일시" not in youth.text and "근거자치법규" not in youth.text  # None은 빈 값
    assert g[1].apply_end is None  # 상시

    k = parse_rows("kstartup", rows("programs_kstartup_p1.json"))[0]
    assert (k.external_id, k.apply_start, k.apply_end) == ("990001", date(2027, 2, 1), date(2027, 2, 28))
    assert k.url == "https://example.invalid/kstartup/view.do?schM=view&pbancSn=990001"  # &amp; 풀림
    assert "통합공고사업명: 2027년 테스트 예비창업패키지(1차)" in k.text  # &amp;#40; 두 번 풀림
    assert "공고내용: 예비창업자에게" in k.text and "우대사항" not in k.text
    assert parse_rows("kstartup", [{"pbanc_sn": "", "biz_pbanc_nm": "x"}]) == []  # ID 없으면 버림
    assert parse_page((FIX / "programs_kstartup_p1.json").read_bytes())[1] == 1  # 필터 있으면 matchCount


def job_for(record, version_id=1):
    return qx.make_program_job(version_id=version_id, text_hash=record.text_hash, source=record.source,
                               title=record.title, apply_end=None, text=record.text)


def test_skill_example_passes_schema_and_verify():
    md = SKILL.read_text(encoding="utf-8")
    examples = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", md, flags=re.S)]
    version = re.search(r"^version: (\S+)$", md, flags=re.M).group(1)
    assert examples and SKILLS["program"] == "kloe-extract-program"
    assert extractor("program", "haiku") == f"cc:haiku:kloe-extract-program@{version}"
    youth = parse_rows("gov24", rows("programs_gov24_p1.json"))[0]
    for ex in examples:
        assert re.match(EXTRACTOR_PATTERN, ex["extractor"]) and ex["extractor"].endswith(f"@{version}")
        assert verify(ProgramResult.model_validate(ex), job_for(youth)) == []
    table = set(re.findall(r"^\| (\w+) \| ", md, flags=re.M)) - {"benefit_type"}
    allowed = set(ProgramResult.model_fields["fact"].annotation.model_fields["benefit_type"].annotation.__args__[0].__args__)
    assert table == allowed


def test_verify_catches_invented_basis_and_amount():
    youth = parse_rows("gov24", rows("programs_gov24_p1.json"))[0]
    bad = ProgramResult.model_validate({
        "job_id": "program:1:x", "extractor": "cc:haiku:kloe-extract-program@0.1",
        "fact": {"is_benefit": True, "benefit_type": "subsidy", "legal_basis": ["없는법 제1조"],
                 "benefit_size": {"raw": "월 30만원", "cap_krw": 300000},
                 "quotes": [{"field": "benefit_size.cap_krw", "quote": "월 최대 20만원"}]}})
    errors = verify(bad, job_for(youth))
    assert any("근거법령" in e for e in errors) and any("cap_krw=300000" in e for e in errors)
    with pytest.raises(ValueError, match="apply_end"):
        ProgramResult.model_validate({"job_id": "j", "extractor": "cc:h:kloe-extract-program@0.1",
                                      "fact": {"is_benefit": False, "apply_start": "2027-02-01", "apply_end": "2027-01-01"}})


def test_program_queue_round_trip(tmp_path):
    recs = parse_rows("gov24", rows("programs_gov24_p1.json"))
    p = qx.write_batch(tmp_path, "program", [job_for(r, i) for i, r in enumerate(recs, 1)])
    assert qx.in_flight_provision_ids(tmp_path, "program") == {1, 2}
    qi.claim(tmp_path, "program", p.name)
    run_agent(tmp_path, "program", p.name)
    rep = qi.ingest_batch(tmp_path, "program", p.name)
    assert rep.ok and len(rep.accepted) == 2
    assert rep.accepted[0][1].fact.legal_basis == ["테스트주거지원법(제21조, 제0항)", "테스트특례법(제16조, 제1항)"]
