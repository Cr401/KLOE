# KLOE

한국 법령에서 경제적 이익이 되는 조항을 발굴·구조화하는 개인 프로젝트. 설계와 결정 이력은 [docs/KLOE_CONTEXT.md](docs/KLOE_CONTEXT.md)에 있다 (문서 안의 "LEO", `leo`는 이 시스템의 이전 이름이고 지금은 KLOE, `kloe`다).

## 현재 상태

- Phase 0: `data/golden/` 정답 셋은 초안. 사용자가 직접 완성한다.
- Phase 1 (L0 코드): `src/kloe/` 초안. **테스트는 아직 없다.** 법제처 XML 태그 이름은 실제 응답을 보기 전이라 가정이다 (`src/kloe/normalize/parse.py`의 `TAGS`).

## 실행

```bash
docker compose up -d          # postgres
pip install -e '.[dev]'
export KLOE_DATABASE_URL=postgresql://kloe:kloe@localhost:5432/kloe
kloe migrate
export KLOE_OC=...             # 법제처 Open API OC 키 (호출하는 기기의 IP 등록 필요)
kloe nightly
```
