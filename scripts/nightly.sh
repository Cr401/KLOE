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

# 단계가 실패해도 조용히 끝나지 않게: 실패를 기록하고, 뒤 단계가 그 결과에 기대지 않으면 계속한다.
FAILED=""  # 실패한 단계 이름들 (macOS 기본 bash 3.2는 set -u에서 빈 배열을 못 다뤄 문자열로 둔다)
step() {  # step <이름> <명령...>
  local name="$1"; shift
  log "$name 시작"
  if "$@"; then log "$name 끝"; else local rc=$?; log "실패: $name (exit $rc)"; FAILED="$FAILED $name"; return $rc; fi
}
notify() {  # macOS 알림. 실패해도 무시
  /usr/bin/osascript -e "display notification \"$1\" with title \"KLOE nightly\"" >/dev/null 2>&1 || true
}

# migrate가 안 되면 뒤는 의미가 없으니 멈춘다
step migrate .venv/bin/kloe migrate || { notify "migrate 실패. 로그를 봐라"; exit 1; }
step requeue .venv/bin/kloe requeue --stale 6h || true
step nightly .venv/bin/kloe nightly || true

# 백업: DB 덤프와 work/failed(버린 job 목록)를 backups/ 에 날짜별로, 최근 7개만 둔다
BACKUP_DIR="$REPO/backups"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
backup() {
  docker compose exec -T postgres pg_dump -U kloe -Fc kloe > "$BACKUP_DIR/kloe-$STAMP.dump" &&
  { [[ ! -d work/failed ]] || tar -czf "$BACKUP_DIR/work-failed-$STAMP.tgz" work/failed; }
}
if step backup backup; then
  for prefix in kloe- work-failed-; do
    ls -1t "$BACKUP_DIR"/"$prefix"* 2>/dev/null | tail -n +8 | while read -r old; do rm -f -- "$old"; done || true
  done
else
  rm -f -- "$BACKUP_DIR/kloe-$STAMP.dump"  # 반쯤 쓴 덤프는 남기지 않는다
fi

SUMMARY="$(.venv/bin/kloe status 2>&1 || true)"
log "요약: $SUMMARY"
if [[ -n "$FAILED" ]]; then
  notify "실패:$FAILED"
  exit 1
fi
if [[ "$SUMMARY" =~ queue=[1-9] ]]; then
  notify "처리할 배치가 있다. kloe status 로 확인"
fi
