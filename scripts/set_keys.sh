#!/bin/bash
# API 키를 ~/.zshrc 에 넣고(이미 있으면 바꿈) 실제로 호출해서 확인한다. 키는 화면에 보이지 않고 출력·로그에 남지 않는다.
#
#   scripts/set_keys.sh            # 키 입력 + 확인 호출
#   scripts/set_keys.sh --check    # 입력 없이 ~/.zshrc 의 키로 확인 호출만
#
# 넣는 키
#   KLOE_DATA_GO_KR_KEY  공공데이터포털 인증키 하나. 신청한 data.go.kr API 전부(공공서비스 정보, K-Startup 등)에 같이 쓴다.
#   KLOE_OC              법제처 Open API OC (이미 넣었으면 엔터로 건너뜀)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RC="$HOME/.zshrc"
touch "$RC"

current() {  # ~/.zshrc 에 든 값. zsh로 읽고, 안 되면 export 줄을 직접 읽는다
  local v=""
  [[ -x /bin/zsh ]] && v="$(/bin/zsh -ic "print -r -- \${$1-}" </dev/null 2>/dev/null || true)"
  if [[ -z "$v" ]]; then
    v="$(grep -E "^[[:space:]]*export[[:space:]]+$1=" "$RC" | tail -1 | sed -E "s/^[^=]*=//; s/^['\"]//; s/['\"]$//" || true)"
  fi
  printf '%s' "$v"
}

set_var() {  # set_var NAME VALUE : ~/.zshrc 의 기존 export 줄을 지우고 새 줄을 붙인다
  local name="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -v -E "^[[:space:]]*export[[:space:]]+$name=" "$RC" > "$tmp" || true
  printf "export %s='%s'\n" "$name" "$value" >> "$tmp"
  cat "$tmp" > "$RC"   # 원래 파일의 권한을 유지하려고 덮어쓰기만 한다
  rm -f "$tmp"
}

ask() {  # ask NAME 설명
  local name="$1" desc="$2" have value
  have="$(current "$name")"
  if [[ -n "$have" ]]; then
    printf '%s (%s): 이미 있음 (끝 4자리 …%s). 바꾸려면 새 값, 그대로 두려면 엔터: ' "$name" "$desc" "${have: -4}"
  else
    printf '%s (%s): ' "$name" "$desc"
  fi
  IFS= read -rs value; echo
  value="${value//[[:space:]]/}"
  [[ -z "$value" ]] && return 0
  if [[ "$name" == KLOE_DATA_GO_KR_KEY && "$value" == *%* ]]; then
    # 'Encoding' 키(%2B 등)를 넣었으면 'Decoding' 형태로 바꾼다. 코드가 URL에 넣을 때 다시 인코딩한다.
    value="$(KLOE_V="$value" python3 -c 'import os, urllib.parse; print(urllib.parse.unquote(os.environ["KLOE_V"]))')"
    echo "  → Encoding 키로 보여서 Decoding 형태로 바꿔 저장함"
  fi
  if [[ "$value" == *"'"* ]]; then echo "  작은따옴표가 든 값은 넣을 수 없음. 건너뜀"; return 0; fi
  set_var "$name" "$value"
  echo "  → ~/.zshrc 에 저장함"
}

if [[ "${1:-}" != "--check" ]]; then
  [[ -f "$RC.kloe-backup" ]] || cp "$RC" "$RC.kloe-backup"
  echo "키를 입력하세요 (화면에 안 보임). 백업: ~/.zshrc.kloe-backup"
  ask KLOE_DATA_GO_KR_KEY "공공데이터포털 마이페이지 > 일반 인증키(Decoding)"
  ask KLOE_OC "법제처 Open API OC"
  echo
fi

# 확인 호출: 소스마다 1건만 받는다. 응답은 data/raw/programs/ 에 저장된다 (필드 이름 맞추는 데 씀).
export KLOE_DATA_GO_KR_KEY="$(current KLOE_DATA_GO_KR_KEY)"
if [[ -z "$KLOE_DATA_GO_KR_KEY" ]]; then echo "KLOE_DATA_GO_KR_KEY 없음. 확인 호출 건너뜀"; exit 1; fi
[[ -x "$REPO/.venv/bin/python" ]] || { echo ".venv 없음: 저장소에서 pip install -e '.[dev]' 먼저"; exit 1; }
cd "$REPO"
.venv/bin/python - <<'PY'
from pathlib import Path
from kloe.collect.programs import SOURCES, ProgramApiClient, ProgramApiError

client = ProgramApiClient()
ok = True
for source in SOURCES:
    try:
        page = next(client.pages(source, Path("data/raw"), max_pages=1, per_page=1))
        print(f"OK   {source}: 전체 {page.total}건, 받은 응답 {page.path}")
    except ProgramApiError as e:
        ok = False
        print(f"FAIL {source}: {e}")
    except OSError as e:  # 네트워크·HTTP 오류
        ok = False
        print(f"FAIL {source}: {type(e).__name__}: {e}")
print("\n전부 OK면 끝. FAIL이 있으면 그 줄을 그대로 Claude에게 붙여 주세요 (키는 들어 있지 않음).")
raise SystemExit(0 if ok else 1)
PY
