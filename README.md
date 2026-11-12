# KLOE

한국 법령에서 경제적 이익이 되는 조항을 발굴·구조화하는 개인 프로젝트. 설계와 결정 이력은 [docs/KLOE_CONTEXT.md](docs/KLOE_CONTEXT.md)에 있다 (문서 안의 "LEO", `leo`는 이 시스템의 이전 이름이고 지금은 KLOE, `kloe`다).

## 현재 상태

- Phase 0: `data/golden/` 정답 셋은 초안. 사용자가 직접 완성한다.
- Phase 1 (L0 코드): `src/kloe/`. 수집, 정규화, 위임 연결, 배치 내보내기/가져오기 + 검증, requeue, DB 적재, CLI. 테스트는 합성 fixture(`tests/fixtures/`, 실제 법령 아님)로 돈다.
- 법제처 XML 태그 이름은 실제 응답을 보기 전이라 가정이다 (`src/kloe/normalize/parse.py`의 `TAGS`). OC 키를 받으면 실제 응답으로 fixture와 `TAGS`를 맞춰야 한다.

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
- extractor는 `cc:<모델>:kloe-classify@0.1`. 검증은 그대로 `kloe ingest`가 한다.
- 사용량 한도가 걱정되면 `--parallel`과 `--max-batches`를 줄인다.

## 지원사업·장학금·창업 공고 (보조금24, K-Startup)

법령 말고 공고도 모은다 (설계 결정 18, 19). 공공데이터포털(data.go.kr)에서 아래 두 API를 **활용신청**하고, 마이페이지의 일반 인증키(Decoding)를 `~/.zshrc` 에 둔다.

- 행정안전부_대한민국 공공서비스(혜택) 정보: https://www.data.go.kr/data/15113968/openapi.do
- 창업진흥원_K-Startup 조회서비스: https://www.data.go.kr/data/15125364/openapi.do

```bash
export KLOE_DATA_GO_KR_KEY=...   # ~/.zshrc 에. nightly.sh 가 실행할 때 읽는다
.venv/bin/kloe migrate
.venv/bin/kloe fetch-programs --source gov24 --max-pages 1   # 처음엔 한 쪽만 받아 응답 모양 확인
.venv/bin/kloe agent --stage program --model haiku --parallel 3 --max-batches 5 --ingest
.venv/bin/kloe programs --extracted   # 마감 전 공고 + 추출 결과
```

- `kloe nightly` 가 매일 두 소스를 받고(키가 없으면 건너뜀), 마감이 안 지난 공고를 `work/queue/program/` 으로 내보낸다.
- 공고는 분류 없이 `kloe-extract-program` 스킬이 대상 요건, 금액, 신청 기간, 근거법령을 인용과 함께 뽑는다. 인용과 근거법령이 원문에 없으면 검증에서 떨어진다.
- 본문이 바뀌면 새 판이 생기고 이전 추출 결과는 stale이 되어 다시 나간다.
- 근거법령과 이미 모은 법령의 연결: `select * from program_law_basis;`
- **가정한 것**: 보조금24 base URL(`api.odcloud.kr/api`), 두 API의 키 파라미터 이름(`serviceKey`), K-Startup 응답 필드 이름과 모집중 필터 형식. 실제 응답을 처음 받으면 `src/kloe/normalize/program.py` 의 `FIELDS`·`KEYS` 와 `tests/fixtures/programs_*.json` 을 맞춘다.

## L1 예약 작업 (Cowork, 예비)

Cowork 예약 작업은 Mac 위 Linux VM에서 돌고 `kloe`를 실행하지 못한다. `work/` 파일만 다룬다 (설계 결정 16).
KLOE 폴더를 연결하고, 모델은 Haiku·effort medium, 프롬프트는 한 줄:

```
/Users/chris/KLOE/skills/kloe-classify/SKILL.md 를 읽고 그대로 따라서 배치 하나를 처리해라.
```
