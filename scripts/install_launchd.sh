#!/bin/bash
# kloe nightly를 매일 실행하도록 launchd에 등록한다 (macOS 전용).
# 사용: scripts/install_launchd.sh [시각(0-23), 기본 3]
# ~/Library/LaunchAgents/com.kloe.nightly.plist 를 만들고 등록한다.
# OC 키는 따로 저장하지 않는다. nightly.sh가 실행할 때마다 ~/.zshrc 의 KLOE_OC 를 읽는다.
# 해제: launchctl bootout gui/$(id -u)/com.kloe.nightly
set -euo pipefail

HOUR="${1:-3}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$HOME/Library/Logs/kloe"
PLIST="$HOME/Library/LaunchAgents/com.kloe.nightly.plist"

if [[ -z "$(/bin/zsh -ic 'print -r -- ${KLOE_OC-}' </dev/null 2>/dev/null)" ]]; then
  echo "경고: ~/.zshrc 에서 KLOE_OC 를 못 읽었다. 수집 없이 가져오기·내보내기만 돈다." >&2
fi
[[ -x "$REPO/.venv/bin/kloe" ]] || { echo "$REPO/.venv/bin/kloe 없음. pip install -e . 먼저." >&2; exit 1; }

mkdir -p "$LOGDIR" "$(dirname "$PLIST")"

sed -e "s#__REPO__#$REPO#g" -e "s#__HOUR__#$HOUR#g" -e "s#__LOGDIR__#$LOGDIR#g" \
  "$REPO/scripts/launchd/com.kloe.nightly.plist.template" > "$PLIST"
chmod +x "$REPO/scripts/nightly.sh"

launchctl bootout "gui/$(id -u)/com.kloe.nightly" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "등록 완료: 매일 ${HOUR}:00 실행, 로그 $LOGDIR/nightly.log"
echo "지금 한 번 돌려보기: launchctl kickstart gui/$(id -u)/com.kloe.nightly"
