# KLOE

한국 법령에서 경제적 이익이 되는 조항을 발굴·구조화하는 개인 프로젝트. 설계와 결정 이력은 [docs/KLOE_CONTEXT.md](docs/KLOE_CONTEXT.md)에 있다 (문서 안의 "LEO", `leo`는 이 시스템의 이전 이름이고 지금은 KLOE, `kloe`다).

## 현재 상태 (2026-11-12)

- Phase 0: `data/golden/` 정답 셋은 초안. 사용자가 직접 완성한다.
- Phase 1 (L0 코드): `src/kloe/`. 수집, 정규화, 위임 연결, 배치 내보내기/가져오기 + 검증, requeue, DB 적재, CLI. 조세특례제한법·시행령·시행규칙(조문 4,961개)을 실제 법제처 API로 받아 돌린다. 남은 것: 연혁 수집, 부칙 파싱.
- Phase 2 (L1): 분류(`kloe-classify`)는 4,961건을 마쳤다 (true 2,414). 추출(`kloe-extract`)은 skill과 실행기가 준비됐고 돌릴 차례다. 공고(보조금24, K-Startup) 추출도 붙어 있다.
- Mac에서 launchd가 매일 03:00 `kloe nightly`를 돈다. L1은 `kloe agent`가 Claude Code 헤드리스(Haiku)로 돈다.

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
- 결과는 `work/out/<stage>/`에 같은 파일 이름으로 쓴다. 한 줄에 job 하나, `job_id`와 `extractor`(`<cowork|cc>:<모델>:<skill>@<버전>`) 필수. `cc`는 `kloe agent`(Claude Code 헤드리스), `cowork`는 Cowork.
- `extractor`의 skill 이름은 단계마다 달라야 한다 (`kloe-classify@…`, `kloe-extract@…`). 같으면 DB의 중복 방지 규칙에 걸려 결과가 저장되지 않는다.

## 매일 자동 실행 (Mac, launchd)

```bash
# 저장소 루트에서. OC 키는 ~/.zshrc 의 KLOE_OC 를 실행할 때마다 읽는다 (따로 저장하지 않음)
scripts/install_launchd.sh 3        # 매일 03:00
launchctl kickstart gui/$(id -u)/com.kloe.nightly   # 지금 한 번 실행
tail -f ~/Library/Logs/kloe/nightly.log
```

`scripts/nightly.sh`가 Docker와 Postgres를 띄우고 `kloe migrate` → `kloe requeue --stale 6h` → `kloe nightly` → 백업 → `kloe status` 한 줄 요약을 돌린다.
- 단계가 실패하면 로그에 `실패: <단계>`를 남기고 macOS 알림을 띄운다. migrate가 실패하면 거기서 멈추고, 나머지는 실패해도 다음 단계로 간다.
- 백업은 `backups/`(git 제외)에 DB 덤프(`pg_dump -Fc`)와 `work/failed` 묶음을 최근 7개씩 둔다. 같은 디스크라 디스크 고장에는 대비가 안 되니 가끔 다른 곳으로 복사한다. 되살리기: `docker compose exec -T postgres pg_restore -U kloe -d kloe --clean < backups/kloe-<시각>.dump`
- 처리할 배치가 queue에 있으면 알림으로 알려 준다. 지금 상태는 언제든 `.venv/bin/kloe status`. 내보내기는 실행마다 최대 5000건이라, 아직 안 나간 조문이 첫 실행에 다 나간다. 그 시각에 Mac이 잠자고 있으면 깨어날 때 실행된다.

## L1 헤드리스 실행 (기본)

Mac에서 Claude Code를 `claude -p`로 돌린다. 잠금과 결과 rename은 `kloe agent`가 하고, 에이전트에게는 Read·Write 도구만 준다.

```bash
.venv/bin/kloe agent --stage classify --model haiku --parallel 3 --max-batches 30 --ingest
.venv/bin/kloe export --stage extract            # 분류에서 true인 조문을 추출 큐로
.venv/bin/kloe agent --stage extract --model haiku --parallel 3 --max-batches 30 --ingest
```

- 추출(`kloe-extract`)은 조문마다 `role`을 다시 가른다: `benefit`(혜택 본문), `condition`(다른 조문 혜택의 요건·범위·계산), `none`(위임만, 가산세·추징, 절차). 분류는 애매하면 true로 넘기므로 여기서 거른다.
- 이 명령은 Mac 터미널에서 직접 돌린다. 원격 세션 안에서 `claude -p`를 띄우는 건 권한 설정이 막는다.

- 처음 한 번: `claude --version`이 되는지 보고, `claude auth login`으로 구독 로그인.
- `claude`가 PATH에 없거나(nvm 등) launchd에서 돌릴 때는 `KLOE_CLAUDE_BIN`에 전체 경로를 넣는다.
- 실패한 배치(종료 코드 오류, 결과 없음, 줄 수 불일치, 시간 초과)는 queue로 돌아가고 같은 실행 안에서는 다시 잡지 않는다.
- 에이전트는 `work/claimed/`와 `skills/`만 읽고 `work/out/`에만 쓸 수 있다 (공고 본문에 섞인 지시로 저장소 파일을 고치지 못하게).
- 검증에서 두 번 실패한 job은 `work/failed/<stage>/dropped.jsonl`에 남고 다시 내보내지 않는다. 다시 돌리려면 그 파일을 지운다.
- extractor는 `cc:<모델>:<skill>@<버전>`. 검증은 그대로 `kloe ingest`가 한다.

### classify 다시 돌리기 (skill을 고쳤을 때)

```bash
.venv/bin/kloe export --stage classify --recheck     # 0.1에서 false로 빠진 위임 항 중 같은 조에 true가 있는 것 (2026-11-12 기준 180건)
.venv/bin/kloe agent --stage classify --model haiku --parallel 2 --max-batches 10 --ingest
```

- 법령 개정판이 들어와도 본문이 같은 조문은 이전 결과(fact)를 이어받아 다시 나가지 않는다 (`fact.carried_from`). 본문이 바뀐 조문만 다시 분류·추출된다.
- 현재 skill 버전의 결과가 이미 있는 조문은 다시 나가지 않는다. 0.1 결과와 0.2 결과가 같이 남고, extract는 둘 중 하나라도 `true`면 그 조문을 내보낸다.
- 사용량 한도가 걱정되면 `--parallel`과 `--max-batches`를 줄인다.

### 추출 감사 (kloe-audit)

정답 셋 없이 추출 품질을 보는 방법이다. 상위 모델이 검증을 통과한 추출 결과 표본을 원문과 다시 대조해, 놓친 혜택(`lost`)·틀린 값(`wrong`)·지어낸 내용(`extra`)을 필드와 원문 인용으로 지적한다. fact는 고치지 않고 표만 남긴다.

```bash
.venv/bin/kloe export --stage audit                       # 기본 50건, role(none·condition·benefit 30%씩, uncertain 10%)으로 층화
.venv/bin/kloe agent --stage audit --model opus --parallel 1 --ingest
.venv/bin/kloe audit-report                               # reports/audit-<날짜>.md: 필드별 lost·wrong·extra 수, 놓친 것 목록
```

- 이어받은 fact는 표본에서 뺀다. 한 번 감사한 fact는 다시 나가지 않는다. 특정 법령만 보려면 `--law-filter 조세특례제한법`.
- 감사는 nightly가 자동으로 내보내지 않는다. 추출 시험 배치 뒤 한 번, 그다음은 extract skill 버전이 바뀔 때만 돌린다.
- 지적이 한 필드에 몰리면(예: `benefit_size`의 `lost`) skill을 고치고 다시 추출할지 판단한다.

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
- 주소, 키 파라미터(`serviceKey`), 응답 필드 이름은 2026-11-12 실제 응답으로 확인했다. 보조금24 전체 약 1만 1천 건, K-Startup 모집중 약 200건이다. 보조금24 신청기한은 연도 없는 자유 글이 많아서 그런 공고는 마감일이 비고, 마감일이 비면 계속 추출 대상이 된다.

## L1 예약 작업 (Cowork, 예비)

Cowork 예약 작업은 Mac 위 Linux VM에서 돌고 `kloe`를 실행하지 못한다. `work/` 파일만 다룬다 (설계 결정 16).
KLOE 폴더를 연결하고, 모델은 Haiku·effort medium, 프롬프트는 한 줄:

```
/Users/chris/KLOE/skills/kloe-classify/SKILL.md 를 읽고 그대로 따라서 배치 하나를 처리해라.
```
