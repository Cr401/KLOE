#!/bin/zsh
# launchd가 매일 부르는 kloe nightly 래퍼. Mac에서만 돈다 (Cowork VM에서는 .venv를 쓸 수 없다).
set -eu
ROOT="${0:A:h:h}"
cd "$ROOT"
mkdir -p logs
exec >>"logs/nightly-$(date +%Y%m%d).log" 2>&1
echo "=== $(date '+%F %T %Z') start"

# launchd는 ~/.zshrc를 읽지 않는다. 키는 값을 출력하지 않고 환경변수로만 넘긴다.
export KLOE_OC="$(/bin/zsh -ic 'print -r -- ${KLOE_OC-}' </dev/null 2>/dev/null)"
[[ -n "$KLOE_OC" ]] || echo "warn: KLOE_OC 없음, fetch는 건너뛴다"
export KLOE_DATABASE_URL="${KLOE_DATABASE_URL:-postgresql://kloe:kloe@localhost:5432/kloe}"
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

# Docker가 꺼져 있으면 켜고 Postgres가 받을 때까지 기다린다 (최대 3분)
if ! docker info >/dev/null 2>&1; then
  open -a Docker
  for _ in {1..60}; do docker info >/dev/null 2>&1 && break; sleep 3; done
fi
docker compose up -d
for _ in {1..60}; do docker compose exec -T postgres pg_isready -U kloe >/dev/null 2>&1 && break; sleep 3; done

.venv/bin/kloe migrate
.venv/bin/kloe nightly
echo "=== $(date '+%F %T %Z') done"
