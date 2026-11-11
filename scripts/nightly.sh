#!/bin/bash
# launchd가 매일 실행하는 래퍼. 저장소 루트에서 `kloe nightly`를 돌린다.
# 필요: ~/.zshrc 의 KLOE_OC(와 공고 수집용 KLOE_DATA_GO_KR_KEY), Docker Desktop, 저장소의 .venv
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# launchd는 ~/.zshrc를 읽지 않는다. 키는 ~/.zshrc 한 곳에만 두고, 실행할 때 값만 읽어 환경변수로 넘긴다 (출력하지 않음).
if [[ -z "${KLOE_OC:-}" ]]; then
  KLOE_OC="$(/bin/zsh -ic 'print -r -- ${KLOE_OC-}' </dev/null 2>/dev/null || true)"
  export KLOE_OC
fi
[[ -n "$KLOE_OC" ]] || log "경고: KLOE_OC 없음. 수집(fetch)은 건너뛰고 가져오기·내보내기만 한다"
# 공공데이터포털 인증키(보조금24·K-Startup 공고). KLOE_OC와 같은 방식으로 ~/.zshrc 에서만 읽는다.
if [[ -z "${KLOE_DATA_GO_KR_KEY:-}" ]]; then
  KLOE_DATA_GO_KR_KEY="$(/bin/zsh -ic 'print -r -- ${KLOE_DATA_GO_KR_KEY-}' </dev/null 2>/dev/null || true)"
  export KLOE_DATA_GO_KR_KEY
fi
[[ -n "$KLOE_DATA_GO_KR_KEY" ]] || log "경고: KLOE_DATA_GO_KR_KEY 없음. 공고 수집은 건너뛴다"
export KLOE_DATABASE_URL="${KLOE_DATABASE_URL:-postgresql://kloe:kloe@localhost:5432/kloe}"

# Docker와 Postgres가 떠 있어야 한다. 꺼져 있으면 켜고 최대 3분 기다린다.
if ! docker info >/dev/null 2>&1; then
  log "Docker 시작"
  open -a Docker
  for _ in $(seq 1 36); do docker info >/dev/null 2>&1 && break; sleep 5; done
fi
cd "$REPO"
docker compose up -d postgres >/dev/null
for _ in $(seq 1 30); do
  docker compose exec -T postgres pg_isready -U kloe >/dev/null 2>&1 && break; sleep 2
done

log "migrate"
.venv/bin/kloe migrate
log "requeue 시작"
.venv/bin/kloe requeue --stale 6h
log "nightly 시작"
.venv/bin/kloe nightly
log "nightly 끝"
