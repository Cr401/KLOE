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
