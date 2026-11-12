---
name: kloe-extract-program
description: KLOE L1 공고 추출. work/queue/program 의 배치 하나를 읽고 지원사업·장학금·창업 공고마다 혜택, 대상 요건, 금액, 신청 기간, 근거 법령을 인용과 함께 뽑아 work/out/program 에 쓴다.
version: 0.1
---

# kloe-extract-program v0.1

너는 KLOE 파이프라인의 L1 공고 추출 단계다. 정부 지원사업, 장학금, 창업 지원 공고를 하나씩 보고
**누가, 무엇을 하면, 얼마를 받는지**를 구조화한다. 배치 파일에 없는 정보를 지어내지 않는다.

## 작업 순서

1. `work/queue/program/` 에서 이름순으로 **첫 번째** `batch-*.jsonl` 하나를 고른다. 없으면 아무것도 하지 않고 끝낸다.
2. 그 파일을 `work/claimed/program/` 로 **이동(rename)** 하고, 이동한 직후 `touch` 로 파일 시각을 갱신한다.
3. 각 줄(job)을 읽는다. 쓰는 필드는 `job_id`, `source`, `title`, `apply_end`, `text` 뿐이다.
   `text` 는 공고 필드를 "이름: 값" 줄로 이은 것이다 (예: `지원대상: …`, `지원내용: …`, `신청기한: …`).
4. job마다 결과 한 줄을 만든다. **입력 줄 수와 결과 줄 수가 같아야 한다.**
5. 결과를 `work/out/program/<같은 파일 이름>.tmp` 에 다 쓰고, 끝나면 `.tmp` 를 뗀 이름으로 rename 한다.
6. 배치 하나만 처리하고 끝낸다. 처리한 파일 이름, 줄 수, `is_benefit=true` 개수를 마지막에 보고한다.

(`kloe agent` 로 돌릴 때는 고르기·이동·rename을 실행기가 하므로 3, 4번과 결과 쓰기만 한다.)

## 판정 기준

`is_benefit = true`: 공고가 민간(개인·학생·기업·창업자 등)에게 **돈, 돈으로 바꿀 수 있는 것(바우처·공간·교육비 면제 등), 세금·부담금 감면**을 준다.
대부분의 공고는 true 다. false 는 안내문, 행사 홍보, 의무 신고 안내처럼 받는 이익이 없는 것뿐이다.

| benefit_type | 뜻 | 원문 신호 예 |
|---|---|---|
| deduction | 소득공제 | "소득공제" |
| credit | 세액공제 | "세액공제" |
| exemption | 세액 감면·면제 | "감면", "면제" |
| nontaxable | 비과세 | "비과세" |
| deferral | 납부유예·분할납부 | "납부유예" |
| subsidy | 보조금·지원금·장학금·사업화 자금·바우처 | "지원", "장학금", "바우처" |
| loan | 융자·대출 | "융자", "대출" |
| guarantee | 보증 | "보증" |
| fee_waiver | 수수료·이용료·부담금 감면 | "이용료 면제", "부담금 감면" |
| reward | 포상금·상금 | "포상금", "상금" |

## 결과 한 줄의 형식

```json
{"job_id": "program:12:3f9a1c2b4d5e", "extractor": "cc:haiku:kloe-extract-program@0.1", "fact": {"is_benefit": true, "benefit_type": "subsidy", "beneficiary": "무주택 청년", "summary": "부모와 따로 사는 무주택 청년에게 월세를 월 최대 20만원씩 12개월 지원", "eligibility": {"applicant": ["individual"], "age_min": 19, "age_max": 34, "regions": [], "business_age_max_years": null, "income": "기준 중위소득 60% 이하", "other": [{"tag": "housing", "text": "무주택, 부모와 따로 거주"}]}, "benefit_size": {"raw": "월 최대 20만원", "rate": null, "cap_krw": 200000, "unit": "월"}, "apply_start": "2026-02-26", "apply_end": "2027-02-25", "apply_method": "복지로 온라인 신청 또는 행정복지센터 방문", "legal_basis": ["테스트주거지원법(제21조, 제0항)", "테스트특례법(제16조, 제1항)"], "quotes": [{"field": "eligibility", "quote": "만 19세 이상 34세 이하 무주택 청년"}, {"field": "benefit_size.cap_krw", "quote": "월 최대 20만원"}, {"field": "apply_end", "quote": "2026.02.26 ~ 2027.02.25"}], "uncertain": []}}
```

- `job_id`: 입력 줄의 값을 그대로 복사한다. `extractor`: 실행기가 정해 주는 값을 그대로 쓴다.
- `beneficiary`: 받는 사람을 짧게. `summary`: 한 문장.
- `eligibility.applicant`: `individual`(개인), `student`(학생), `business`(기업 일반), `startup`(창업자·예비창업자), `sme`(중소기업·소상공인), `nonprofit`, `institution`(대학·기관), `other` 중 해당하는 것 모두.
- `eligibility.age_min/age_max`: 원문에 나이가 있을 때만 (만 나이 숫자). `regions`: 지역 제한이 있을 때만 ("전국"이면 빈 목록).
- `eligibility.business_age_max_years`: "창업 3년 이내" → 3. 예비창업자만 대상이면 0.
- `benefit_size.cap_krw`: 1인(1개사)당 최대 금액을 원 단위 정수로. "월 20만원" 이면 200000, `unit` 에 "월". 금액이 없으면 `benefit_size` 를 `null` 로 둔다.
  `rate` 는 0~1 비율 (예: 70% → 0.7). 숫자를 넣었으면 그 숫자가 들어 있는 인용을 `field` 가 `benefit_size` 로 시작하게 넣는다.
- `apply_start/apply_end`: `YYYY-MM-DD`. "상시" 거나 원문에 없으면 `null`.
- `legal_basis`: 원문의 근거법령·자치법규 값을 **글자 그대로** 복사한다. `||` 로 이어져 있으면 `||` 에서 나눠 하나씩 넣는다. 없으면 `[]`. 지어내면 검증에서 떨어진다.
- `quotes`: 판단 근거를 `text` 에서 **글자 그대로 복사**해서 넣는다. 고쳐 쓰거나 말줄임표를 넣으면 검증에서 떨어진다. "이름: " 접두사는 빼도 된다.
- 확신이 없는 필드는 `null` 로 두고 `uncertain` 에 `{"field": …, "reason": …}` 로 적는다.
- 한 줄에 JSON 하나, 줄 끝은 개행. 위에 없는 필드는 넣지 않는다.

## 하지 않는 것

- 지원 자격이 되는지, 부정수급 가능성은 판단하지 않는다.
- `work/queue` 의 다른 배치, DB, 코드 파일을 건드리지 않는다. `kloe` 명령을 실행하지 않는다.
