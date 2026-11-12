"""지원사업·창업 공고 API 클라이언트와 원본 저장 (공공데이터포털 키 하나로 둘 다 쓴다).

소스
- gov24: 행정안전부_대한민국 공공서비스(혜택) 정보 (data.go.kr 15113968). 정부24·보조금24의 서비스 목록.
  실제 호출로 확인 (2026-11-12): https://api.odcloud.kr/api/gov24/v3/serviceDetail, serviceKey, page·perPage·returnType=JSON,
  응답 {currentCount, matchCount, page, perPage, totalCount, data}. 전체 10,942건. 미확인: 호출 한도.
- kstartup: 창업진흥원_K-Startup 조회서비스 (data.go.kr 15125364), getAnnouncementInformation01.
  실제 호출로 확인 (2026-11-12): base URL, serviceKey, 같은 응답 모양. 전체 30,577건 중 cond[rcrt_prgs_yn::EQ]=Y
  (모집중)로 거르면 matchCount 217. 필터를 쓰면 totalCount는 전체, matchCount가 걸린 수다. 개발계정 일 10,000건(제3자 문서).

키는 환경변수 KLOE_DATA_GO_KR_KEY(포털의 '일반 인증키(Decoding)' 값)로만 받고, 저장하는 URL에서는 *** 로 지운다.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from kloe.collect import fetch_url, save_by_hash

Fetcher = Callable[[str], bytes]

SOURCES: dict[str, dict] = {
    "gov24": {
        "url": "https://api.odcloud.kr/api/gov24/v3/serviceDetail",
        "params": {"returnType": "JSON"},
        "per_page": 500,
    },
    "kstartup": {
        "url": "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01",
        "params": {"returnType": "json", "cond[rcrt_prgs_yn::EQ]": "Y"},  # 모집중만 (2026-11-12 기준 217건)
        "per_page": 500,
    },
}


def _default_fetch(url: str) -> bytes:
    return fetch_url(url, accept="application/json")


class ProgramApiError(RuntimeError):
    pass


@dataclass
class RawPage:
    source: str
    page: int
    path: Path
    sha256: str
    url: str  # 키를 지운 URL
    rows: list[dict]
    total: int | None


class ProgramApiClient:
    def __init__(self, key: str | None = None, fetch: Fetcher | None = None):
        self.key = key or os.environ.get("KLOE_DATA_GO_KR_KEY", "")
        self._fetch = fetch or _default_fetch

    def page_url(self, source: str, page: int, *, key: str | None = None, per_page: int | None = None) -> str:
        spec = SOURCES[source]
        q = {"serviceKey": self.key if key is None else key, "page": page,
             "perPage": per_page or spec["per_page"], **spec["params"]}
        return f"{spec['url']}?{urllib.parse.urlencode(q)}"

    def pages(self, source: str, raw_dir: Path, *, max_pages: int = 100, per_page: int | None = None) -> Iterator[RawPage]:
        """1쪽부터 끝까지(또는 max_pages까지) 받는다. 각 쪽은 내용 해시 이름으로 저장한다."""
        if source not in SOURCES:
            raise ProgramApiError(f"모르는 소스: {source}")
        if not self.key:
            raise ProgramApiError("KLOE_DATA_GO_KR_KEY가 없다. 공공데이터포털 인증키를 환경변수로 넣어라.")
        seen = 0
        for page in range(1, max_pages + 1):
            body = self._fetch(self.page_url(source, page, per_page=per_page))
            rows, total = parse_page(body)
            raw, sha = save_by_hash(body, Path(raw_dir) / "programs" / source, ".json")
            yield RawPage(source, page, raw, sha,
                          self.page_url(source, page, key="***", per_page=per_page), rows, total)
            seen += len(rows)
            if not rows or (total is not None and seen >= total):
                return


def parse_page(body: bytes) -> tuple[list[dict], int | None]:
    """{"data": [...], "matchCount": N} 형태만 받는다. 인증 오류(XML 또는 code/msg JSON)는 예외로 막는다."""
    head = body[:500].decode("utf-8", errors="replace")
    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProgramApiError(f"JSON이 아닌 응답: {head[:300]}") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        raise ProgramApiError(f"API 오류 응답: {head[:300]}")
    total = obj.get("matchCount", obj.get("totalCount"))  # 필터가 있으면 matchCount가 실제 건수
    return [r for r in obj["data"] if isinstance(r, dict)], int(total) if total is not None else None
