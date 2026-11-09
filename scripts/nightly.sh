#!/bin/bash
# launchd가 매일 실행하는 래퍼. 저장소 루트에서 `kloe nightly`를 돌린다.
# 필요: ~/.config/kloe/env (KLOE_OC, KLOE_DATABASE_URL), Docker Desktop, 저장소의 .venv
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${KLOE_ENV_FILE:-$HOME/.config/kloe/env}"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

if [[ ! -f "$ENV_FILE" ]]; then
  log "환경 파일 없음: $ENV_FILE (scripts/install_launchd.sh를 먼저 실행)"
  exit 1
fi
set -a; source "$ENV_FILE"; set +a

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

log "requeue 시작"
.venv/bin/kloe requeue --stale 6h
log "nightly 시작"
.venv/bin/kloe nightly
log "nightly 끝"
