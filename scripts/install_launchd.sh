#!/bin/bash
# kloe nightly를 매일 실행하도록 launchd에 등록한다 (macOS 전용).
# 사용: KLOE_OC가 설정된 셸에서  scripts/install_launchd.sh [시각(0-23), 기본 3]
# 하는 일:
#   1. ~/.config/kloe/env 에 KLOE_OC, KLOE_DATABASE_URL 저장 (권한 600). launchd는 ~/.zshrc를 읽지 않기 때문이다.
#   2. ~/Library/LaunchAgents/com.kloe.nightly.plist 생성 후 등록
# 해제: launchctl bootout gui/$(id -u)/com.kloe.nightly
set -euo pipefail

HOUR="${1:-3}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_DIR="$HOME/.config/kloe"
LOGDIR="$HOME/Library/Logs/kloe"
PLIST="$HOME/Library/LaunchAgents/com.kloe.nightly.plist"

if [[ -z "${KLOE_OC:-}" ]]; then
  echo "KLOE_OC가 없다. OC 키가 설정된 셸에서 실행해라." >&2
  exit 1
fi
[[ -x "$REPO/.venv/bin/kloe" ]] || { echo "$REPO/.venv/bin/kloe 없음. pip install -e . 먼저." >&2; exit 1; }

mkdir -p "$ENV_DIR" "$LOGDIR" "$(dirname "$PLIST")"
umask 077
{
  printf 'KLOE_OC=%q\n' "$KLOE_OC"
  printf 'KLOE_DATABASE_URL=%q\n' "${KLOE_DATABASE_URL:-postgresql://kloe:kloe@localhost:5432/kloe}"
} > "$ENV_DIR/env"
chmod 600 "$ENV_DIR/env"

sed -e "s#__REPO__#$REPO#g" -e "s#__HOUR__#$HOUR#g" -e "s#__LOGDIR__#$LOGDIR#g" \
  "$REPO/scripts/launchd/com.kloe.nightly.plist.template" > "$PLIST"
chmod +x "$REPO/scripts/nightly.sh"

launchctl bootout "gui/$(id -u)/com.kloe.nightly" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "등록 완료: 매일 ${HOUR}:00 실행, 로그 $LOGDIR/nightly.log"
echo "지금 한 번 돌려보기: launchctl kickstart gui/$(id -u)/com.kloe.nightly"
