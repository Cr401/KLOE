"""법제처 Open API 클라이언트와 원본 저장.

확인된 것 (2026-11-04): DRF 엔드포인트는 OC 키와 함께 호출 서버의 IP/도메인 등록이 필요하다.
실제 응답으로 확인 (2026-11-09): lawService.do?target=law&type=XML&ID=<법령ID> 는 <법령><기본정보>…로 온다.
인증 실패는 <Response><result>사용자 정보 검증에 실패…</result>, 없는 ID는 <Law>일치하는 법령이 없습니다…</Law>.
lawSearch 응답의 법령상세링크에는 OC 값이 그대로 들어 있으므로 검색 응답은 저장·커밋하지 않는다.
미확인: 연혁 조회 파라미터, 호출 한도. 여기서는 현행 본문 조회(target=law)만 다룬다.
OC 키는 환경변수 KLOE_OC로만 받고, 로그나 저장 경로에 남기지 않는다.
"""

from __future__ import annotations

import hashlib
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BASE = "https://www.law.go.kr/DRF"

Fetcher = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kloe/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 고정된 https 엔드포인트
        return resp.read()


class LawApiError(RuntimeError):
    pass


@dataclass
class RawFile:
    path: Path
    sha256: str
    url: str  # OC 값을 지운 URL


class LawApiClient:
    def __init__(self, oc: str | None = None, fetch: Fetcher | None = None):
        self.oc = oc or os.environ.get("KLOE_OC", "")
        self._fetch = fetch or _default_fetch

    def law_url(self, law_id: str, *, oc: str | None = None) -> str:
        q = {"OC": self.oc if oc is None else oc, "target": "law", "type": "XML", "ID": law_id}
        return f"{BASE}/lawService.do?{urllib.parse.urlencode(q)}"

    def search_url(self, query: str, *, oc: str | None = None) -> str:
        q = {"OC": self.oc if oc is None else oc, "target": "law", "type": "XML", "query": query}
        return f"{BASE}/lawSearch.do?{urllib.parse.urlencode(q)}"

    def fetch_law(self, law_id: str, raw_dir: Path) -> RawFile:
        if not self.oc:
            raise LawApiError("KLOE_OC가 없다. 법제처 Open API OC 키를 환경변수로 넣어라.")
        body = self._fetch(self.law_url(law_id))
        check_api_error(body)
        return save_raw(body, raw_dir, law_id=law_id, url=self.law_url(law_id, oc="***"))


def check_api_error(body: bytes) -> None:
    """인증 실패·없는 법령 응답을 본문 XML로 착각하지 않게 막는다. 본문은 앞부분에 <기본정보>가 있다."""
    head = body[:2000].decode("utf-8", errors="replace")
    if "<기본정보>" not in head:
        raise LawApiError(f"API 오류 응답: {head[:300]}")


def save_raw(body: bytes, raw_dir: Path, *, law_id: str, url: str = "") -> RawFile:
    """원본을 내용 해시로 저장한다. 같은 내용이면 같은 파일이라 다시 받아도 중복이 생기지 않는다."""
    sha = hashlib.sha256(body).hexdigest()
    path = Path(raw_dir) / law_id / f"{sha}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.rename(path)
    return RawFile(path=path, sha256=sha, url=url)
