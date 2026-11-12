"""두 수집기(법제처, 공공데이터포털)가 같이 쓰는 HTTP 받기와 원본 저장."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path


def fetch_url(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": "kloe/0.1", **({"Accept": accept} if accept else {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:  # noqa: S310 - 고정된 https 엔드포인트
        return resp.read()


def save_by_hash(body: bytes, folder: Path, suffix: str) -> tuple[Path, str]:
    """원본을 내용 해시 이름으로 저장한다. 같은 내용이면 같은 파일이라 다시 받아도 중복이 생기지 않는다."""
    sha = hashlib.sha256(body).hexdigest()
    path = Path(folder) / f"{sha}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.rename(path)
    return path, sha
