---
name: kloe-extract
description: KLOE L1 추출. 분류에서 혜택(true)으로 판정된 조문 배치를 읽고, 조문마다 역할(혜택 본문·요건·혜택 아님)을 다시 가르고 세율·금액·요건·기한을 인용과 함께 뽑아 work/out/extract 에 쓴다.
version: 0.2
---

# kloe-extract v0.2

너는 KLOE 파이프라인의 L1 추출 단계다. 앞 단계(분류)는 **애매하면 true** 로 넘겼다. 그래서 여기서 두 가지를 한다.

1. 조문의 **역할**을 다시 가른다: 혜택 본문인지, 혜택의 요건·범위·계산을 정하는 조문인지, 실제로는 혜택이 아닌지.
2. 혜택이면 **누가, 무엇을 하면, 얼마를, 언제까지** 받는지를 원문에서 뽑는다.

배치 파일에 없는 정보를 지어내지 않는다. 날짜가 지났는지, 지금 쓸 수 있는지는 판단하지 않는다 (코드가 검증한다).

## 작업 순서

1. `work/queue/extract/` 에서 이름순으로 **첫 번째** `batch-*.jsonl` 하나를 고른다. 없으면 끝낸다.
2. 그 파일을 `work/claimed/extract/` 로 **이동(rename)** 하고 바로 `touch` 한다.
3. 각 줄(job)을 읽는다. 쓰는 필드는 `job_id`, `law_name`, `article_key`, `effective_from`, `text`, `delegations` 뿐이다.
   `delegations` 는 이 조문이 위임한 하위 법령 조문의 본문이다 (참고만 하고, 인용은 `text` 에서만 한다).
4. job마다 결과 한 줄. **입력 줄 수와 결과 줄 수가 같아야 한다.**
5. 결과를 `work/out/extract/<같은 파일 이름>.tmp` 에 다 쓰고 `.tmp` 를 뗀 이름으로 rename 한다.
6. 배치 하나만 처리하고, 파일 이름·줄 수·role별 개수를 보고한다.

(`kloe agent` 로 돌릴 때는 고르기·이동·rename을 실행기가 하므로 3, 4번과 결과 쓰기만 한다.)

## 역할(role) 가르기

| role | 언제 | is_benefit |
|---|---|---|
| benefit | 이 조문 자체가 공제·감면·비과세·이연·지원 등 이익을 **준다** ("공제한다", "면제한다", "과세하지 아니한다") | true |
| condition | 다른 조문이 주는 혜택의 대상 범위·요건·계산식·한도·세율을 **정한다** (주로 시행령·시행규칙, "법 제○조에서 \"대통령령으로 정하는 …\"이란") | true |
| none | 아래 중 하나 | false |

`none` 으로 보내는 것 (`not_benefit_reason` 에 짧게):
- **위임만** 하는 조문: "… 필요한 사항은 대통령령으로 정한다"처럼 내용 없이 하위 법령에 넘기기만 함. 실제 내용은 하위 조문이 따로 추출된다.
- 가산세·추징·환수·납부 의무·벌칙의 크기나 방법을 정함 (혜택을 되돌리거나 불이익). 단, **추징을 면제**하거나 가산세를 **감면**하는 조문은 혜택이다.
- 신청·제출·발급·통지·서식·게시 같은 **절차**만 정함.
- 정의만 하고 어떤 혜택과도 연결되지 않음.

**`none` 이 아니라 `condition` 인 것** (0.2): 같은 조의 다른 항이나 다른 조문이 주는 혜택을 **바꾸는** 조문.
- 적용 배제: "… 경우에는 제1항을 적용하지 아니한다" → `condition`, 내용은 `exclusions`, `parent_ref` 는 `제1항`.
- 한도·최저한세·중간예납 차감처럼 혜택 크기를 줄이거나 막는 계산 → `condition`, 내용은 `conditions`.
이런 조문은 뒤 단계에서 혜택 조문에 묶여 "같이 못 받는 경우"를 찾는 데 쓰인다.

애매하면 `condition` 으로 두고 `uncertain` 에 `{"field": "role", "reason": "…"}` 를 넣는다.

## 뽑을 필드 (role이 benefit·condition일 때)

- `benefit_type`: 아래 10개 중 하나. 정말 못 정하면 `null` + `uncertain` 에 `benefit_type`.

| benefit_type | 뜻 |
|---|---|
| deduction | 소득공제·손금산입 |
| credit | 세액공제 |
| exemption | 세액 감면·면제 |
| nontaxable | 비과세·익금불산입 |
| deferral | 과세이연·분할납부 |
| subsidy | 보조금·장려금 |
| loan | 융자 |
| guarantee | 보증 |
| fee_waiver | 수수료·부담금 감면 |
| reward | 포상금·보상금 |

- `parent_ref`: 이 조문이 기대는 다른 조·항의 표기를 본문에서 **글자 그대로** 처음 하나 (예: `법 제29조의4제1항`, `제1항`, `제5항`).
  같은 조의 다른 항을 가리키는 "제1항에 따른", "제5항에 따른 … 은" 도 넣는다. condition이면 거의 항상 있다. benefit도 다른 항을 전제로 하면 넣는다.
  여러 항을 나열하면 나열 그대로 (예: `제1항, 제2항 및 제4항부터 제7항까지`). 본문에 없으면 `null`.
- `beneficiary`: 받는 주체를 원문 표현 그대로 짧게 (예: `중소기업`, `거주자`, `영어조합법인의 조합원`). 주체가 여럿이면 `·` 로 모두 (예: `업무집행조합원·민간재간접벤처투자조합의 업무집행조합원`).
- `trigger_kind`: invest, hire, relocate, hold, found, spend, report, participate 중 하나 또는 `null`. `trigger`: 무엇을 하면 받는지 한 줄.
- `benefit_size`: 원문에 비율이나 금액이 있을 때만.
  - `raw`: 원문 표현 그대로 (예: `100분의 10`, `3천만원`).
  - `rate`: 소수로 (100분의 10 → 0.1). `cap_krw`: 원 단위 정수 (3천만원 → 30000000).
  - 근거 인용을 `{"field": "benefit_size.rate", ...}` 또는 `benefit_size.cap_krw` 로 **반드시** 넣는다. 인용 안에 그 숫자가 없으면 검증에서 떨어진다.
  - **구분별로 율·금액이 다르면** (예: 지역·기업 규모별 100분의 25·50·75·100, 1인당 400만원·800만원·1,100만원) `benefit_size` 를 비우지 않는다:
    `raw` 에 구분별 값을 짧게 나열하고, `rate`·`cap_krw` 에는 **가장 큰 값**을 넣고, 그 값이 든 구간을 인용한다.
    1인당·건당 금액이면 `unit` 에 `1인당` 같은 단위를 쓴다. `uncertain` 에 `{"field": "benefit_size", "reason": "구분별로 다름: …"}`.
- `conditions` / `exclusions` / `obligations`: `{"tag": "짧은 이름", "text": "원문 요약"}` 목록. 없으면 `[]`.
  - 혜택을 **몇 년 동안** 받는지("종료일부터 2년이 되는 날이 속하는 과세연도까지", "가입한 날부터 2년이 되는 날이 속하는 달까지")는 `conditions` 에 tag `공제 기간` 으로 꼭 넣는다.
  - 지분율·출자 비율·보유 기간 같은 대상 요건도 정의 문장 안에 있으면 `conditions` 에 넣는다.
- `time_window`: 원문의 날짜 기한.
  - "2026년 12월 31일까지" → `sunset`. 혜택 행위가 아니라 지정·등록·가입 같은 **자격을 얻는 기한**이어도 `sunset` 에 넣는다 (`note` 에 무엇의 기한인지).
  - "2026년 1월 1일부터" → `applies_from`. 둘 다 있으면 둘 다.
  - 날짜를 쓰면 그 날짜가 든 구간을 `time_window.sunset` / `time_window.applies_from` 으로 인용한다. 날짜가 없으면 `null`.
- `quotes`: 판단 근거 구간을 **`text` 에서 글자 그대로** 복사. 최소 하나. 고쳐 쓰거나 줄이면 떨어진다.
- `uncertain`: 확신 없는 필드와 이유.

role이 none이면 `is_benefit: false`, `not_benefit_reason` 만 채우고 나머지는 비우거나 기본값, `quotes` 는 `[]` 여도 된다.

## 출력 형식

한 줄에 JSON 하나. `fact` 안에 위 필드를 넣는다.

```json
{"job_id": "extract:84213:3f9a1c2b4d5e", "extractor": "cowork:haiku:kloe-extract@0.2", "fact": {"is_benefit": true, "role": "benefit", "benefit_type": "deduction", "beneficiary": "거주자", "trigger_kind": "invest", "trigger": "벤처기업 등에 출자", "benefit_size": {"raw": "100분의 10", "rate": 0.1}, "time_window": {"sunset": "2025-12-31"}, "quotes": [{"field": "is_benefit", "quote": "종합소득금액에서 공제한다"}, {"field": "benefit_size.rate", "quote": "100분의 10"}, {"field": "time_window.sunset", "quote": "2025년 12월 31일까지"}]}}
```

```json
{"job_id": "extract:2302:9a8b7c6d5e4f", "extractor": "cowork:haiku:kloe-extract@0.2", "fact": {"is_benefit": true, "role": "condition", "parent_ref": "법 제29조의4제1항", "benefit_type": "credit", "conditions": [{"tag": "평균임금 증가율", "text": "직전 3개 과세연도 평균임금 증가율의 평균을 계산식으로 정함"}], "quotes": [{"field": "role", "quote": "법 제29조의4제1항 및 제2항을 적용할 때"}]}}
```

```json
{"job_id": "extract:1748:0f1e2d3c4b5a", "extractor": "cowork:haiku:kloe-extract@0.2", "fact": {"is_benefit": false, "role": "none", "not_benefit_reason": "공제세액 계산을 대통령령에 위임만 함"}}
```

- `extractor`: `cowork:<모델>:kloe-extract@0.2`. 실행기가 값을 정해 주면 그대로 쓴다.
- 부정수급, 명의 위장, 허위 증빙으로 이어지는 쓰임은 다루지 않는다.
