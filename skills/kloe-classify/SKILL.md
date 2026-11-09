---
name: kloe-classify
description: KLOE L1 분류. work/queue/classify 의 배치 하나를 가져와 조문마다 혜택 조항인지 판정하고 work/out/classify 에 결과를 쓴다.
version: 0.1
---

# kloe-classify v0.1

너는 KLOE 파이프라인의 L1 분류 단계다. 조문 하나씩 보고 **경제적 혜택을 주는 조항인지**만 판정한다.
DB나 다른 파일은 건드리지 않는다. 배치 파일에 없는 정보를 지어내지 않는다.

## 작업 순서

1. `work/queue/classify/` 에서 이름순으로 **첫 번째** `batch-*.jsonl` 하나를 고른다. 없으면 아무것도 하지 않고 끝낸다.
2. 그 파일을 `work/claimed/classify/` 로 **이동(rename)** 한다. 이동에 실패하면(다른 작업이 먼저 가져감) 다음 파일로 넘어간다.
   이동한 직후 `touch` 로 파일 시각을 갱신한다.
3. 파일의 각 줄(job)을 읽는다. 쓰는 필드는 `job_id`, `law_name`, `article_key`, `text`, `delegations` 뿐이다.
4. job마다 아래 기준으로 판정해서 결과 한 줄을 만든다. **입력 줄 수와 결과 줄 수가 같아야 한다.**
5. 결과를 먼저 `work/out/classify/<같은 파일 이름>.tmp` 에 다 쓰고, 끝나면 `.tmp` 를 뗀 이름으로 rename 한다. 가져오기는 `.tmp` 가 없는 파일만 읽으므로, 중간에 끊겨도 반쯤 쓴 결과가 들어가지 않는다.
6. 배치 하나만 처리하고 끝낸다. 처리한 파일 이름, 줄 수, `is_benefit=true` 개수를 마지막에 보고한다.

## 판정 기준

`is_benefit = true`: 이 조문이 **민간(개인·법인)에게 경제적 이익을 주거나, 그 이익의 크기·대상·요건을 정한다.**

| benefit_type | 뜻 | 원문 신호 예 |
|---|---|---|
| deduction | 소득공제 | "소득금액에서 공제한다" |
| credit | 세액공제 | "세액에서 공제한다" |
| exemption | 세액 감면·면제 | "감면한다", "면제한다" |
| nontaxable | 비과세·과세 제외 | "과세하지 아니한다", "익금에 산입하지 아니한다" |
| deferral | 과세이연·분할납부·납부유예 | "과세를 이연", "나누어 납부" |
| subsidy | 보조금·지원금 | "지원할 수 있다" (금전) |
| loan | 융자 | "융자" |
| guarantee | 보증 | "보증" |
| fee_waiver | 수수료·부담금 감면 | "부담금을 감면" |
| reward | 신고·제보 보상금·포상금 | "포상금을 지급", "보상금을 지급" |

- 시행령·시행규칙 조문이 법률의 혜택 대상 범위, 공제율, 한도를 정하면 `true` 다. 예: "법 제16조제1항에서 \"대통령령으로 정하는 …\"이란 …".
- `false`: 정의만 하는 조문(혜택과 무관), 절차·신청서·서식, 벌칙·가산세, 의무만 정하는 조문, **사후관리·추징·환수**(혜택을 되돌리는 조항), 다른 조문을 단순히 적용 배제하는 조문, `삭제` 조문.
- 적용기한(일몰)이 지났거나 "…까지 적용한다" 같은 기한이 붙은 특례도 혜택 내용이면 `true` 다. 기한·날짜가 지났는지는 판단하지 않는다(추출 단계에서 기록하고 코드가 검증한다).
- 애매하면 `true` 로 두고 `reason` 에 이유를 쓴다. 놓치는 것보다 다음 단계에서 걸러지는 게 낫다.
- 부정수급, 명의 위장, 허위 증빙에 쓰일 수 있는지는 판단하지 않는다. 그건 이 단계의 일이 아니다.

## 결과 한 줄의 형식

```json
{"job_id": "classify:84213:3f9a1c2b4d5e", "extractor": "cowork:haiku:kloe-classify@0.1", "is_benefit": true, "benefit_type": "deduction", "reason": "출자금액의 일정 비율을 종합소득금액에서 공제", "quotes": [{"field": "is_benefit", "quote": "종합소득금액에서 공제"}]}
```

- `job_id`: 입력 줄의 값을 그대로 복사한다.
- `extractor`: `cowork:<모델>:kloe-classify@0.1`. `<모델>`은 지금 너를 돌리는 모델의 짧은 이름(`haiku`, `sonnet`, `opus`)이다.
- `is_benefit`: true / false.
- `benefit_type`: `is_benefit` 이 true 면 위 표의 값 하나, false 면 `null`.
- `reason`: 한 문장.
- `quotes`: `is_benefit` 이 true 면 판정 근거가 되는 구간을 **`text` 에서 글자 그대로 복사**해서 하나 이상 넣는다. 고쳐 쓰거나 요약하거나 말줄임표를 넣으면 검증에서 떨어진다. false 면 빈 배열 `[]` 로 둔다.
- 다른 필드는 넣지 않는다. 한 줄에 JSON 하나, 줄 끝은 개행.

## 하지 않는 것

- `work/queue` 의 다른 배치, `work/done`, `work/failed`, DB, 코드 파일을 건드리지 않는다.
- `kloe` 명령을 실행하지 않는다 (가져오기와 검증은 Mac의 launchd가 한다).
