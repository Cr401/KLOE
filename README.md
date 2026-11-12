# KLOE

한국 법령에서 경제적 이익이 되는 조항을 발굴·구조화하는 개인 프로젝트. 설계와 결정 이력은 [docs/KLOE_CONTEXT.md](docs/KLOE_CONTEXT.md)에 있다 (문서 안의 "LEO", `leo`는 이 시스템의 이전 이름이고 지금은 KLOE, `kloe`다).

## 현재 상태

- Phase 0: `data/golden/` 정답 셋은 초안. 사용자가 직접 완성한다.
- Phase 1 (L0 코드): `src/kloe/`. 수집, 정규화, 위임 연결, 배치 내보내기/가져오기 + 검증, requeue, DB 적재, CLI. 실제 법제처 응답(조특법·시행령·시행규칙)으로 동작을 확인했다. 테스트는 합성 fixture(`tests/fixtures/`, 실제 법령 아님)로 돈다.
- Phase 2 (L1): classify 진행 중. 현행 조문 4,961건 분류 완료(2026-11-12), skill 0.2로 위임 항 재분류 대기. extract는 아직 skill이 없다.

## 실행

```bash
docker compose up -d          # postgres
pip install -e '.[dev]'
export KLOE_DATABASE_URL=postgresql://kloe:kloe@localhost:5432/kloe
kloe migrate
export KLOE_OC=...             # 법제처 Open API OC 키 (호출하는 기기의 IP 등록 필요)
kloe nightly
```

## 테스트

```bash
pytest                                   # DB 없이 도는 테스트
KLOE_TEST_DATABASE_URL=postgresql://kloe:kloe@localhost:5432/kloe_test pytest   # Postgres 통합 테스트 포함 (public 스키마를 지운다)
```

## 배치 규칙 (L1 에이전트용)

- `work/queue/<stage>/batch-N.jsonl`을 `work/claimed/<stage>/`로 **rename**해서 가져가고, 가져간 직후 파일 시각을 갱신한다 (`touch`). `kloe requeue --stale 6h`가 이 시각을 본다.
- 결과는 `work/out/<stage>/`에 같은 파일 이름으로 쓴다. 한 줄에 job 하나, `job_id`와 `extractor`(`cowork:<모델>:<skill>@<버전>`) 필수.
- `extractor`의 skill 이름은 단계마다 달라야 한다 (`kloe-classify@…`, `kloe-extract@…`). 같으면 DB의 중복 방지 규칙에 걸려 결과가 저장되지 않는다.

## 매일 자동 실행 (Mac, launchd)

```bash
# 저장소 루트에서. OC 키는 ~/.zshrc 의 KLOE_OC 를 실행할 때마다 읽는다 (따로 저장하지 않음)
scripts/install_launchd.sh 3        # 매일 03:00
launchctl kickstart gui/$(id -u)/com.kloe.nightly   # 지금 한 번 실행
tail -f ~/Library/Logs/kloe/nightly.log
```

`scripts/nightly.sh`가 Docker와 Postgres를 띄우고 `kloe migrate` → `kloe requeue --stale 6h` → `kloe nightly`를 돌린다. 내보내기는 실행마다 최대 5000건이라, 아직 안 나간 조문이 첫 실행에 다 나간다. 그 시각에 Mac이 잠자고 있으면 깨어날 때 실행된다.

## L1 헤드리스 실행 (기본)

Mac에서 Claude Code를 `claude -p`로 돌린다. 잠금과 결과 rename은 `kloe agent`가 하고, 에이전트에게는 Read·Write 도구만 준다.

```bash
.venv/bin/kloe agent --stage classify --model haiku --parallel 3 --max-batches 30 --ingest
```

- 처음 한 번: `claude --version`이 되는지 보고, `claude auth login`으로 구독 로그인.
- `claude`가 PATH에 없거나(nvm 등) launchd에서 돌릴 때는 `KLOE_CLAUDE_BIN`에 전체 경로를 넣는다.
- 실패한 배치(종료 코드 오류, 결과 없음, 줄 수 불일치, 시간 초과)는 queue로 돌아가고 같은 실행 안에서는 다시 잡지 않는다.
- extractor는 `cc:<모델>:kloe-classify@<skill 버전>` (지금 0.2). 검증은 그대로 `kloe ingest`가 한다.
- 사용량 한도가 걱정되면 `--parallel`과 `--max-batches`를 줄인다.

## L1 예약 작업 (Cowork, 예비)

Cowork 예약 작업은 Mac 위 Linux VM에서 돌고 `kloe`를 실행하지 못한다. `work/` 파일만 다룬다 (설계 결정 16).
KLOE 폴더를 연결하고, 모델은 Haiku·effort medium, 프롬프트는 한 줄:

```
/Users/chris/KLOE/skills/kloe-classify/SKILL.md 를 읽고 그대로 따라서 배치 하나를 처리해라.
```

## classify 다시 돌리기 (skill을 고쳤을 때)

classify는 애매하면 `true`로 둔다. `false`로 빠진 조문은 다음 단계로 가지 않아서, 놓친 것은 다시 분류해야만 되살아난다.

```bash
.venv/bin/kloe export --stage classify --recheck     # 0.1에서 false로 빠진 위임 항 중 같은 조에 true가 있는 것 (2026-11-12 기준 180건)
.venv/bin/kloe agent --stage classify --model haiku --parallel 2 --max-batches 10 --ingest
```

- 현재 skill 버전의 결과가 이미 있는 조문은 다시 나가지 않는다. 같은 조문에 0.1 결과와 0.2 결과가 같이 남고, extract는 둘 중 하나라도 `true`면 그 조문을 내보낸다.
