# KLOE (Korea Legal Opportunity Engine) — 프로젝트 컨텍스트

> 최종 갱신: 2026-11-12 · 설계 버전: v0.3
> 이 파일 하나로 프로젝트를 이어서 진행할 수 있도록 만든 인계 문서다. 1부는 맥락과 결정 이력, 2부는 설계 전문이다.
> 2026-11-04: 시스템 이름을 LEO에서 **KLOE**로 바꿨다. 본문의 `leo` CLI, `leo/` 경로, `LEO_*` 환경변수는 각각 `kloe`, 저장소 루트, `KLOE_*`로 읽는다.

---

# 1부. 맥락

## 이 파일을 읽는 어시스턴트에게

- 이 문서가 **현재 합의된 설계의 기준(source of truth)**이다. 2부 0절의 결정 사항을 바꾸려면 먼저 사용자에게 묻고, 합의되면 결정 로그에 한 줄 추가한다.
- 답변은 한국어로, 짧고 직접적으로 한다. 사용자는 반말로 편하게 대화한다.
- 법령 조문, 제도명, 세율, 금액, 기한은 **기억으로 단정하지 않는다.** korean-law MCP나 공식 원문으로 확인하고, 확인하지 못했으면 "미확인"이라고 적는다.
- 설계를 바꿀 때는 가장 작은 변경을 택한다. 요청받지 않은 기능, 추상화, 설정은 추가하지 않는다.
- 이 문서의 "미확인 사실" 목록에 있는 항목은 사실로 전제하지 않는다.

## 사용자와 프로젝트

- **사용자:** 1명. 이 도구를 직접 쓰고, CV(포트폴리오) 용도로 만든다. 사업화는 지금 고려하지 않는다.
- **환경:** Claude Max 구독. **API는 쓰지 않는다.** LLM은 앱이 제공하는 기능(Cowork, 예약 작업, 서브에이전트) 안에서만 돌린다.
- **목표:** 한국 법령을 분석해서 경제적 이익이 되는 조항을 **사용자 본인의 상황과 관계없이 전부** 찾는다. 찾은 것을 퀀트나 사용자의 사업에 연결하는 응용은 사용자가 LLM과 대화하며 직접 해보면서(HITL) 배운다.
- **산출물:** 기회 카탈로그, 제도 허점 후보, 매주 나오는 보고서, 그리고 CV에 쓸 평가 지표(재현율·정밀도·처리량).

## 결정 로그

| # | 결정 | 이유 |
|---|---|---|
| 1 | 처음 기획안(v0.1)의 "개인 프로필 기반 적격 판정 + 세후 효과 계산" 방향을 버림 | 사용자의 목표가 "내 상황에 맞는 혜택 계산"이 아니라 "법 전체에서 이익이 되는 것을 다 찾기"로 바뀜 |
| 2 | 시스템은 **기회 발굴·구조화·변경 감지**까지만 자동화하고, 이익 실현은 HITL로 | 자동으로 "이익 창출"까지 하는 건 불가능하고, 사용자가 이 부분을 직접 배우고 싶어 함 |
| 3 | 기회의 단위는 조문이 아니라 **"행위 → 혜택"** | 법률 본문, 위임받은 시행령, 고시가 합쳐져야 기회 하나가 됨 |
| 4 | 트랙을 A(기회 카탈로그), B(제도 허점), C(특정 주체의 부정수급 탐지)로 나누고 **A·B를 동시에** 진행, C는 범위 밖 | C는 주체 단위 외부 데이터가 필요하고, 명예훼손·개인정보·허위신고 리스크가 있으며, 별개의 시스템임. B는 A의 구조화 데이터 위에서 쿼리로 나오므로 같이 가는 게 자연스러움 |
| 5 | 신고포상금·보상금처럼 "민간이 하면 국가가 돈을 주는 제도"는 A의 `benefit_type = reward`로 발굴하고, 사업화 가능성 필드(`reward_terms`, `business_signal`)를 붙임 | 사용자가 미국의 부정수급 탐지·보상 스타트업에서 영감을 받음. 한국에는 qui tam이 없어서 신고 주체, 대리 가능 여부, 지급 시점, 반복 신고 제한 같은 필드가 사업화 가능성을 결정함 |
| 6 | 세액 계산기를 만들지 않음. 혜택 규모는 명목값(율·한도·조세지출 금액)까지만 다룸 | 사용자 결정. 세후 순효과는 HITL 심층 분석에서 다룸 |
| 7 | 규칙 엔진과 판정용 DSL을 만들지 않음. 요건은 **태그가 붙은 텍스트**로 저장 | 적격 판정을 하지 않으므로 실행 가능한 규칙이 필요 없음 |
| 8 | DB는 로컬 PostgreSQL, 원본 파일은 로컬 디스크 | 사용자 결정 |
| 9 | 코드베이스와 Cowork를 함께 쓰고, API는 쓰지 않음. Max 구독에서 남는 토큰을 활용 | 사용자 결정. 앱이 제공하는 기능 안에서만 실행 |
| 10 | **4계층 워크플로**: L0 코드(수집·정규화·검증) → L1 Cowork 하위 모델(분류·fact 추출) → L2 상위 모델(기회 합성) → L3 HITL(창의적 연결) → L4 주간 보고서 | 사용자가 확정. 결정론적인 일은 코드가 하고, LLM 토큰은 판단이 필요한 곳에만 씀 |
| 11 | fact(조문 단위)와 opportunity(기회 단위)를 분리 | fact는 조문끼리 독립적이라 싼 모델로 대량 처리 가능. 상위 모델은 이미 검증된 짧은 fact만 읽으므로 비싼 토큰이 가장 적게 듦 |
| 12 | 에이전트는 DB에 직접 쓰지 않고 **파일 핸드오프**(`work/queue → claimed → out → done/failed`)로만 주고받음 | 에이전트가 검증을 우회할 수 없고, Cowork 실행 환경에서 로컬 DB에 접속할 수 있는지와 무관하게 동작하며, 배치 파일 자체가 재현용 기록이 됨 |
| 13 | 에이전트 지시는 git으로 관리하는 **skill 파일**에 두고, 결과마다 `extractor = cowork:<모델>:<skill 버전>`을 기록 | 구독 모델은 버전이 고정되지 않으므로, 재현성을 skill 버전으로 확보 |
| 14 | 환각 방지는 "인용문이 원문에 글자 그대로 있는가"를 문자열로 확인하는 방식 | 비용이 거의 들지 않고 효과가 큼 |
| 15 | 첫 수집 범위는 조세 법령. 단, 보상 조항은 처음부터 전체 법령에 키워드 필터를 돌림 | 조세는 조세지출예산서라는 정답 셋이 있어서 재현율을 잴 수 있음. 보상 조항은 여러 법에 흩어져 있고 키워드 필터는 비용이 거의 없음 |
| 16 | `kloe` 실행(수집·가져오기·내보내기)은 Mac의 launchd가 맡고, Cowork 예약 작업은 `work/` 파일만 다룬다 (12절 열린 질문 1의 대안 확정) | 2026-11-09 시험: Cowork 셸은 Mac 위 Linux VM이라 macOS용 `.venv`의 `kloe`를 실행하지 못함. KLOE 폴더 읽기·쓰기는 됨 |
| 17 | L1 예약 작업은 Haiku, effort medium으로 돌린다 | 사용자 결정 (2026-11-09). 시험 작업은 기본값 Opus로 돌았음 |
| 18 | 범위를 법령 밖 **지원사업·장학금·창업 공고**로 넓힌다. 첫 소스는 보조금24(정부24 공공서비스, data.go.kr 15113968)와 K-Startup 사업공고(15125364). 기업마당·한국장학재단 CSV는 다음 | 사용자 결정 (2026-11-11). 두 API가 공공데이터포털 키 하나로 되고, 개인 혜택과 창업 공고를 함께 다룸 |
| 19 | 공고는 조문 표(`provision`)에 넣지 않고 `program`·`program_version`·`program_fact`로 따로 둔다. 분류 단계 없이 `program` 단계(`kloe-extract-program`)로 바로 추출하고, 배치 핸드오프와 인용 검증은 그대로 쓴다. 근거법령은 `program_law_basis` 뷰로 모은 법령과 잇는다 | 공고에는 조·항, 시행일, 위임이 없고 대부분 혜택이라 분류가 필요 없음. 본문은 필드를 "이름: 값" 줄로 이은 것이라 인용 검증을 그대로 할 수 있음 |
| 20 | L1 기본 실행은 Mac의 **Claude Code 헤드리스**(`kloe agent` → `claude -p`, Haiku, effort medium)로 한다. Cowork 예약 작업은 예비 | 사용자 결정 (2026-11-09). VM·승인 대기 문제가 없고 병렬로 빠름. 구독 로그인을 그대로 씀. 잠금과 rename은 실행기가 하고 에이전트에게는 Read·Write 도구만 준다 |
| 21 | 분류는 **애매하면 true**로 넘기고, 거르기는 추출 단계에서 한다. 추출은 조문마다 `role`(`benefit`·`condition`·`none`)을 다시 가른다. 일몰된 특례도 분류에서는 true, 기한은 추출에서 기록하고 코드가 검증한다 | 사용자 결정 (2026-11-09, 2026-11-12). 분류에서 false로 빠진 조문은 뒤에서 되살릴 수 없으므로 재현율을 우선함 |
| 22 | `extractor`는 `<실행 환경>:<모델>:<skill>@<버전>`. 실행 환경은 `cowork`(Cowork) 또는 `cc`(Claude Code 헤드리스) | 같은 skill이라도 실행 환경별 결과를 나눠 비교하기 위함 |

## 검토했다가 버린 대안

| 대안 | 버린 이유 |
|---|---|
| 조건식을 JSON DSL로 표현 | 법의 OR·NOT·예외·참조를 담다 보면 결국 열악한 프로그래밍 언어를 하나 만들게 됨. 게다가 판정을 하지 않기로 해서 필요 없어짐 |
| OpenFisca식 규칙 코드 + 세액 계산 | 적격 판정과 세액 계산이 범위에서 빠지면서 불필요해짐 |
| 조특법 원문 전체를 DB에 버전 관리하는 것을 Phase 1의 목표로 | 법제처가 이미 연혁법령을 제공함. 지금은 파이프라인에 필요한 만큼만 저장 |
| 초기부터 pgvector·벡터 검색 | 필요가 증명되기 전까지는 Postgres 전문검색과 `pg_trgm`으로 충분 |
| API Batch와 Haiku API | 사용자가 API를 쓰지 않기로 함. Haiku는 구독 안의 서브에이전트로 쓸 수 있음 |
| 모든 단계를 에이전트가 처리 | 수집·파싱처럼 단순한 작업에서 원문이 컨텍스트를 통과하면서 토큰이 낭비되고, 결과가 결정론적이지 않음 |
| 에이전트가 DB에 직접 쓰기 | 검증을 우회할 수 있고, 실행 환경의 DB 접근 여부에 의존하게 됨 |
| 트랙 C를 지금 시작 | 범위가 너무 크고 법적 리스크가 있음. 나중에 A의 요건을 공공데이터 검사 규칙으로 재사용하는 방식으로 붙일 수 있음 |
| 검토용 CLI 별도 구현 | L3의 Cowork 대화에서 검토 판정을 기록하면 됨 |

## 지켜야 할 원칙 (요약)

- 부정수급, 명의 위장, 허위 증빙, 실질과 다른 거래 설계는 기회로 분류하지 않는다. `form_only`는 위험 표시이지 추천이 아니다.
- 제도 허점(B)은 후보일 뿐이다. 예산낭비신고나 제도개선 제안으로 실제 제출할지는 사용자가 정한다.
- 나중에 트랙 C를 하게 되면: 결과는 로컬에만 저장하고 공개하지 않으며, 공식 신고 채널로만 제출하고, 대상은 법인과 공개 자료로 한정한다.
- LLM 실행은 앱이 제공하는 기능 안에서만 한다. claude.ai를 스크립트로 자동 조작하지 않는다.

## 미확인 사실 (Phase 0에서 확인할 것)

> 2026-11-04 1차 확인 결과는 아래 "Phase 0 확인 메모"에 있다. 1~5는 일부만 확정됐고, 남은 부분은 여전히 미확인이다.

1. 조세특례제한법 제14조와 제16조의 정확한 제목과 내용 (v0.1 기획안에서 벤처투자 특례 예시로 언급됨) → **확인 (2026-11-09, 법제처 API 원문).** 아래 "Phase 1 확인 메모" 참고. 제14조 본문은 아직 안 봄
2. 보상 제도들의 근거 법률, 지급 비율, 상한: 공공재정환수법, 공익신고자 보호법, 부패방지권익위법, 국세기본법(탈세제보 포상금), 보조금법, 고용보험법, 국민건강보험법, 관세법, 국가재정법(예산성과금·예산낭비신고) → **국가재정법만 기관 안내로 확인, 나머지 미확인**
3. 조세지출예산서에 항목별 근거 조문과 금액이 기계 판독 가능한 형식으로 들어 있는가 → **미확인** (재정경제부 게시판에서는 보도자료 HWPX·PDF만 확인)
4. 신고보상 제도를 종합한 공식 목록이 있는가 → **미확인** (찾지 못함)
5. 법제처 Open API의 연혁 조문 범위, 호출 한도, OC 키 발급 절차 → **일부 확인** (OC와 호출 기기 IP 등록 필요, Mac에서 인증 통과. 호출 한도·연혁 조회 방법은 미확인)
6. Cowork 예약 작업이 로컬 폴더를 읽고 쓰고 CLI를 실행할 수 있는가 → **확인 (2026-11-09).** 읽기·쓰기는 됨, `kloe` 실행은 안 됨 (결정 16)
7. 예약 작업에서 모델을 지정하는 방식 → **확인.** Cowork는 지정하지 않으면 Opus로 돎, 설정에서 Haiku를 고른다 (결정 17). 헤드리스는 `--model`로 지정 (결정 20)
8. 최저한세, 소득공제 종합한도, 농어촌특별세가 개별 혜택에 걸리는지 (명목값만 다루더라도 `obligations`·`exclusions`에 기록할 대상)

## Phase 0 확인 메모 (2026-11-04, 1차)

**확인 환경의 한계.** 이번 확인은 클라우드 세션에서 했다. 이 환경은 law.go.kr, 재정경제부, 국회예산정책처에 직접 접속하지 못하고(프록시 403), 웹 조회 도구로만 페이지를 읽었다. 그래서 JS로 본문을 불러오는 법령 페이지(law.go.kr, elaw.klri.re.kr)의 조문 본문과 HWPX·PDF 첨부는 읽지 못했다. korean-law MCP도 이 세션에는 없다. 남은 확인은 korean-law MCP가 있는 Mac의 Cowork에서 하는 게 맞다.

**사실 1. 조특법 제14조·제16조**
- 제목 (한국법제연구원 국문 법령, 공포번호 20617·2024-12-31 기준 판): 제14조 "창업기업 등에의 출자에 대한 과세특례", 제16조 "벤처투자조합 출자 등에 대한 소득공제". 출처: https://elaw.klri.re.kr/kor_service/lawViewTitle.do?hseq=69248
- law.go.kr 현행 표시: 법률 제21467호(2026-03-17 타법개정), 시행 2026-09-18. 현행판에서 제목이 그대로인지와 본문(공제율·한도·요건)은 **미확인**.
- 이 조특법 판의 소관 부처 표기는 "재정경제부"다.

**사실 2. 보상 제도** (상세는 `data/golden/reward_programs.csv`)
- 확인됨 (기관 안내 페이지 기준, 조문 원문 대조 전): 예산낭비신고는 국가재정법 제100조, 같은 법 시행령 제51조, 훈령이 근거. 사례금 20만원 상품권, 장려금 5등급 20만~40만원, 예산성과금 최고 3,900만원. 출처: 재정경제부 예산낭비신고 안내 https://mofe.go.kr/cv/sece/bwst/buwast.do?menuNo=8060100
- 확인됨 (요건만): 청탁금지법 위반신고 보상금·포상금의 지급 요건. 출처: 교육부 안내 https://www.moe.go.kr/sub/info.do?m=011101. 비율·상한은 미확인.
- **변경 진행 중 (언론 보도, 원문 미확인):** 부패방지권익위법·공익신고자 보호법·공공재정환수법 시행령 개정으로 보상금이 "가액 구간별 4~30%"에서 "수입 회복액의 30%"로 통일되고, 부패·공공재정환수 신고의 30억원 상한이 폐지된다고 보도됨. 2026-07-14 입법예고, 2026-09-22 국무회의 의결, "29일부터 시행", 시행 이후 신청분부터 적용. 출처: https://www.kbmaeil.com/article/20260714500081 , https://biz.sbs.co.kr/amp/article/20000336345 . 개정 시행령 원문과 정확한 시행일은 law.go.kr에서 확인해야 한다.
- 탈세제보(국세기본법), 보조금법, 고용보험법, 국민건강보험법, 관세법: 근거 조문·비율·상한 모두 **미확인**. CSV의 법령명도 law.go.kr 정식 명칭과 대조하지 않았다.

**사실 3. 조세지출예산서**
- 소관 부처가 기획재정부에서 **재정경제부**로 바뀌었다 (재정경제부 누리집 mofe.go.kr, 2027년 예산안 보도 기준).
- 최신판은 **2027년도 조세지출예산서**다. 재정경제부가 2026-09-03 국회 제출 예정이라고 보도됨. 보도 수치: 2027년 전망 104조9,307억원, 2026년 전망 87조132억원, 국세감면율 2027년 14.5%(법정한도 16.6%). 출처: https://www.dailian.co.kr/news/view/1684975 , https://taxtimes.co.kr/news/article.html?no=276615 (언론 보도, 원문 미확인)
- 2026년도판은 재정경제부 보도자료 게시판에 "조세지출예산서 보도자료" HWPX·PDF 2개만 첨부돼 있다 (2025-08-29, 조세특례제도과). 출처: https://mofe.go.kr/nw/nes/detailNesDtaView.do?searchBbsId1=MOSFBBS_000000000028&searchNttId1=MOSF_000000000075065&menuNo=4010100
- 예산서 본문(항목별 표에 근거 조문·금액이 있는지)은 **미확인**. 공공데이터포털에서 조세지출 항목별 데이터셋은 찾지 못했다. 본문 PDF는 국회 의안정보시스템이나 국회예산정책처 자료로 구해야 할 수 있다 (미확인).
- 참고: 국회예산정책처 「2026년 조세지출예산서 분석」은 2026년 조세지출을 81.5조원으로 전망(정부 80.5조원). 출처: https://www.nabo.go.kr/ko/notice/releasesView.do?idx=8941

**사실 4. 신고보상 제도 종합 목록**
- 공식 종합 목록은 찾지 못했다 (**미확인**). 국민권익위원회 보호보상 안내 페이지(acrc.go.kr)는 웹 조회가 robots로 막혀 읽지 못했다.

**사실 5. 법제처 Open API**
- `law.go.kr/DRF/lawSearch.do`를 OC 없이 호출하면 "사용자 정보 검증에 실패하였습니다 … 정확한 서버장비의 IP주소 및 도메인주소를 등록해 주세요"라는 오류가 온다. 즉 **OC 키와 함께 호출 서버의 IP/도메인 등록이 필요하다.** 클라우드에서 호출하기 어렵고, 로컬 Mac에서 `leo nightly`가 호출하는 현재 설계와 맞는다.
- 공공데이터포털에 법제처의 "조문 개정 전후 비교" API(LINK, XML, 무료, 자동승인, 연혁 제공)가 등록돼 있다. 출처: https://www.data.go.kr/data/15057041/openapi.do . 일일 호출 한도는 "기관 정책에 따라 다름"으로만 나와 있어 **미확인**.
- 연혁 조문을 어느 시점까지 제공하는지는 **미확인**.

## Phase 1 확인 메모 (2026-11-09)

Mac(`/Users/chris/KLOE`)에서 OC 키로 실제 API를 호출해 확인했다.

**사실 1 갱신. 조특법 제16조**
- 제16조 계열 조문(16-1~16-4, 16의2~16의5) 중 "3천만원"은 16-1에만 있다. 원문 일부: "① 거주자가 다음 각 호의 어느 하나에 해당하는 출자 또는 투자를 하는 경우에는 2028년 12월 31일까지 출자 또는 투자한 금액의 100분의 10(제3호ㆍ제4호 또는 제6호에 해당하는 출자 또는 투자의 경우에는 출자 또는 투자한 금액 중 3천만원 이하분은 100분의 100, 3천만원 초과분부터 5천만원 이하분까지는 100분의 70, 5천만원 초과분은 100분의 30)에 상당하는 금액(해당 과세연도의 종합소득금액의 100분의 50을 한도로 한다)을 …"
- 이 문장을 L1 추출의 스모크 테스트 기준으로 쓴다.

**사실 5 갱신. 법제처 Open API**
- 법령ID: 조세특례제한법 001584, 시행령 004920, 시행규칙 008218 (`config/laws.txt`).
- 본문 XML 태그 이름은 추정과 같았다. 다른 점: 항번호가 없는 `<항>` 래퍼 안에 호가 오는 조문이 있고, 인증 오류 응답 루트는 `<Response>`, 없는 ID는 `<Law>일치하는 법령이 없습니다…</Law>`로 온다. 코드는 이미 반영했다 (PR #2).
- **lawSearch 응답의 법령상세링크에 OC 값이 평문으로 들어 있다.** 검색 응답은 저장소·로그에 남기지 않는다.
- 수집 결과: 조문 법률 1,872 · 시행령 2,699 · 시행규칙 390. 위임 연결 1,652건, 그중 대상 없음(G3 후보) 15건.
- 현행판만 받으므로 기준일 조문 재현은 오늘 기준만 된다. 연혁 조회 방법은 **미확인**. 부칙은 아직 파싱하지 않는다.

**사실 6·7. 예약 작업**
- Claude 앱 Code 탭 예약 작업: 권한 모드를 물려받지 않아 첫 셸 명령에서 승인 대기로 멈춘다. 무인 실행하려면 승인을 작업에 저장하거나 권한 모드를 바꿔야 한다.
- Cowork 예약 작업: Mac 위 Linux VM(aarch64)에서 돌고 KLOE 폴더만 마운트된다. `work/queue` 읽기와 `work/` 쓰기는 됐다. macOS용 `.venv`의 `kloe`는 `bad interpreter`로 실행되지 않는다. VM 시계는 Europe/Berlin 기준이었으므로, 파일 이름·기록의 시각은 UTC로 통일한다.
- 모델: 따로 고르지 않으면 Opus(`claude-opus-5-5`)로 돌았다.
- Cowork가 쓴 파일은 Mac의 같은 폴더에 그대로 보인다 (같은 폴더가 마운트됨). VM 마운트를 거친 rename 잠금은 2026-11-09 첫 classify 배치에서 정상 동작을 확인했다 (아래 Phase 2 메모).

## Phase 2 확인 메모 (2026-11-09 ~ 2026-11-12)

**매일 자동 실행 (launchd)**
- `scripts/install_launchd.sh 3`으로 매일 03:00 `scripts/nightly.sh`를 돌린다. 로그는 `~/Library/Logs/kloe/nightly.log`. OC 키는 실행할 때 `~/.zshrc`에서 값만 읽는다 (키 파일 없음).
- Mac 원격 세션은 다른 세션이 전한 launchd 설치·`claude -p` 실행 지시를 권한 설정 때문에 막는다. 이런 명령은 사용자가 Mac 터미널에서 직접 실행한다.

**분류 (classify) 결과**
- 현행 조문 4,961건 전부 분류·검증 통과 (실패 0). true 2,414 / false 2,547.
- true를 법령별로: 법률 852/1,872, 시행령 1,321/2,699, 시행규칙 241/390. 유형별: exemption 912, credit 467, nontaxable 456, deferral 288, deduction 244, subsidy 45, fee_waiver 2.
- 실행: 첫 배치는 Cowork(Haiku), 대부분은 Cowork 쪽 Haiku 작업, 40건은 `kloe agent` 헤드리스 시험(병렬 2, 배치 20건당 약 40초).
- 샘플 검토 (true 50, false 15, `reports/classify-sample-2026-11-12.md`, 커밋 안 함): true의 대부분은 혜택의 범위·요건·계산·한도를 정하는 시행령·시행규칙 조문이다. 판정이 흔들린 유형은 위임만 하는 조문(true·false가 섞임), 가산세·추징 크기를 정하는 조문 일부, 절차 조문 일부다. 결정 21에 따라 분류 기준은 그대로 두고 추출의 `role=none`으로 거른다. 위임만 하는 조문은 하위 조문이 따로 분류되므로 false로 빠져도 내용은 잃지 않는다.

**헤드리스 실행 (`kloe agent`)**
- Claude Code CLI 2.1.x 옵션 확인: `--model`, `--effort`, `--tools`, `--allowedTools`, `--permission-mode dontAsk`, `--no-session-persistence`. `--max-turns`는 없다. `--bare`는 구독 로그인을 읽지 않으므로 쓰지 않는다.
- nvm으로 설치한 `claude`는 네이티브 바이너리 설치 스크립트가 안 돌면 실행되지 않는다. 다시 설치하고 `claude auth login`(구독)으로 로그인했다. launchd에서 돌릴 때는 `KLOE_CLAUDE_BIN`에 전체 경로를 준다.

## 현재 상태

- 설계 v0.3. 아래 2부가 전문이다. 결정 16~22를 더했다.
- 저장소: GitHub `Cr401/KLOE` (Mac의 `/Users/chris/KLOE`에 clone). DB: Mac Docker의 Postgres 16. 매일 03:00 launchd가 수집·가져오기·내보내기를 돈다.
- **Phase 1 대부분 완료.** 남은 것: 연혁 수집, 부칙 파싱.
- **Phase 2 진행 중.** 분류는 현행 조문 4,961건을 마쳤다 (true 2,414). 추출 skill `kloe-extract` v0.1과 `kloe agent --stage extract`를 만들었고, 2,414건 추출을 돌릴 차례다.
- 공고(보조금24, K-Startup) 수집과 `kloe-extract-program` 추출이 붙었다 (결정 18, 19).
- 다른 작업에서 만든 보고서 `reports/benefits-report-2026-11-12.*`, `reports/benefits-by-target-2026-11-12.*`(Mac, 커밋 안 함)는 검증 파이프라인 밖에서 만든 참고 자료다. DB의 fact는 추출 큐를 거친 것만 쓴다.
- Phase 0 정답 셋은 사용자 몫으로 진행 중이다. `data/golden/reward_programs.csv`는 10개 제도 초안, `data/golden/tax_expenditure_2027.csv`는 헤더만 있다.

## 다음 할 일: Phase 0 체크리스트

- [x] 최신 조세지출예산서 확인: 2027년도판 (재정경제부, 2026-09 국회 제출 보도)
- 정답 셋(아래 두 CSV)은 사용자가 직접 만든다 (2026-11-04 결정). 파이프라인과 독립된 출처여야 하므로 LEO 수집 결과로 목록을 만들지 않는다. 처음 한 번 만들고, 예산서는 새 연도판이 나올 때(매년 9월 무렵) 갱신한다.
- [ ] 2027년도 조세지출예산서 본문 파일 확보 → 형식 확인 (PDF인지, 표 데이터가 있는지). 클라우드에서 받지 못함
- [ ] 예산서 항목을 `data/golden/tax_expenditure_2027.csv`로 정리: `item_name, law_name, article_key, amount_krw, year, note` (헤더만 생성)
- [ ] 보상 제도 목록 `data/golden/reward_programs.csv` 완성: `program_name, law_name, article_key, agency, reporter_scope, payout_basis, source_url, verified_at` (초안 10행. "미확인" 칸을 조문 원문으로 채우고, 개정 시행령 반영)
- [ ] 위 "미확인 사실" 1~5의 남은 부분을 korean-law MCP와 공식 원문으로 확인 (Mac의 Cowork에서)
- [x] 법제처 Open API OC 키 발급 (사용자가 직접). 신청할 때 `leo`를 돌릴 Mac의 IP/도메인도 등록해야 함 (사실 5)
- [x] 미확인 사실 6·7: 간단한 예약 작업 하나로 실제 동작 확인 (2026-11-09)
- [x] Phase 1 착수 전에 저장소 생성 (`Cr401/KLOE`)

---

# 2부. 설계 v0.3 전문

> 2026-11-04 · 개인용 CV 프로젝트 · v0.2를 대체 (v0.2 대비 변경: 4계층 워크플로, 파일 핸드오프, fact/opportunity 분리, 주간 보고서)
> 이 문서는 시스템 설계이며 세무·법률 자문이 아니다. 문서 안의 제도명·조문 번호는 Phase 0에서 원문으로 재확인한다.

## 0. 결정 사항

| 항목 | 결정 |
|---|---|
| 사용자 | 본인 1명. 사업화·세무사법 이슈는 고려하지 않음 |
| 목표 | 한국 법령에서 경제적 이익이 되는 조항을 자동으로 발굴·구조화하고, 상위 모델과 사람이 기회로 엮어 **매주 보고서**로 남김 |
| 트랙 | **A 기회 카탈로그 + B 제도 허점**을 동시에. 보상금 제도는 A의 `reward` 유형으로 발굴 |
| LLM 실행 | **API를 쓰지 않음.** Max 구독 안에서, 앱이 제공하는 기능(Claude Code 헤드리스·Cowork·예약 작업·서브에이전트)으로만 실행 |
| 저장소 | 로컬 PostgreSQL + 원본 파일은 로컬 디스크. **DB에는 코드만 쓴다** |
| 범위 밖 | 트랙 C(특정 주체의 부정수급 탐지), 세액 계산기, 개인 프로필 기반 적격 판정 |

**받아들인 한계**
- 혜택 규모는 명목값(율·한도·조세지출 금액)까지만 다룬다.
- 처리 속도는 구독 사용 한도에 묶인다. 전체 코퍼스를 한 번 훑는 데 수일~수주가 걸릴 수 있다.
- 구독 모델은 버전이 고정되지 않으므로, 결과마다 모델과 skill 버전을 기록해서 재현성을 확보한다.

## 1. 4계층 워크플로

```text
L0  코드 (LLM 없음)          수집 → 정규화 → 위임 연결(정규식) → 배치 파일 내보내기
                              ← 결과 파일 가져오기 → 기계 검증 → gap SQL → 변경 피드
         │ queue/*.jsonl                         ▲ out/*.jsonl
         ▼                                       │
L1  kloe agent → claude -p (하위 모델)   조문 단위: 분류 → fact 추출
         │
         ▼  verified facts
L2  상위 모델 (주 1회)       fact 여러 개 → opportunity 합성, gap 의미 판정, 사업화 신호, 순위
         │
         ▼  카탈로그
L3  너 + LLM 대화 (HITL)     창의적 연결 (퀀트, 내 사업), 아이디어 기록, 검토 판정
         │
         ▼
L4  주간 보고서              reports/YYYY-Www.md
```

| 계층 | 실행 수단 | 모델 | 단위 | 산출물 |
|---|---|---|---|---|
| L0 | `kloe` CLI, launchd 매일 03:00 | 없음 | 법령·조문 | DB 행, 배치 파일, 변경 이벤트 |
| L1 | `kloe agent` (Mac 헤드리스, 결정 20). 예비로 Cowork 예약 작업 | 분류·추출 모두 Haiku, effort medium (결정 17). Sonnet 비교는 나중에 | 조문 1개 | `fact` |
| L2 | Cowork 예약 작업 (주 1회) 또는 직접 실행 | Opus | 위임 체인으로 묶인 fact 묶음 | `opportunity`, `gap` 판정, 순위 근거 |
| L3 | Cowork 대화 | Opus | 자유 | `idea`, `review` |
| L4 | Cowork 예약 작업 (주 1회) | Opus | 한 주 | 보고서 Markdown |

### 1.1 L1과 L2를 나누는 이유

- **L1 fact**는 조문 하나만 보고 알 수 있는 사실이다: 혜택 조항인지, 유형, 율·한도, 요건, 의무, 일몰, 인용 구간. 조문끼리 독립적이라 하위 모델로 대량 병렬 처리해도 된다.
- **L2 opportunity**는 여러 조문을 합쳐야 나온다. 법률 본문 + 위임받은 시행령 + 고시를 묶고, 중복배제·사후관리를 연결하고, 사업화 가능성을 판단한다. 판단 난이도가 높고 건수가 적어서 상위 모델이 맡는다.

이렇게 나누면 비싼 모델은 "이미 검증된 짧은 fact"만 읽게 되므로 상위 모델의 토큰을 가장 적게 쓴다.

### 1.2 파일 핸드오프 (계층 사이의 계약)

LLM 계층은 DB에 직접 쓰지 않는다. 코드가 배치 파일을 내보내고, 에이전트는 결과 파일만 쓰고, 코드가 그 파일을 검증한 뒤 DB에 넣는다.

```text
work/
  queue/{stage}/batch-000123.jsonl          # L0가 생성. 조문 원문까지 포함해서 에이전트가 따로 조회할 필요 없음
  claimed/{stage}/batch-000123.jsonl        # 에이전트가 처리를 시작할 때 이동 (rename = 잠금)
  out/{stage}/batch-000123.jsonl            # 에이전트 결과
  done/{stage}/batch-000123.jsonl           # L0가 가져오기를 마치면 이동
  failed/{stage}/batch-000123.jsonl         # 검증 실패 (사유 파일 동봉)
```

`stage` ∈ `classify`, `extract`, `synthesize`, `report`.

장점:
- 에이전트가 검증을 우회할 수 없다.
- 에이전트 실행 환경이 로컬 Postgres에 접속할 수 있는지 신경 쓸 필요가 없다.
- 중간에 끊겨도 `claimed`에 오래 머무른 파일을 `queue`로 되돌리면 된다 (`kloe requeue --stale 6h`, 매일 nightly 앞에 돈다).
- 배치 파일 자체가 재현용 기록이 된다.

배치 한 줄의 형태:

```json
{"job_id": "extract:84213:3f9a…", "provision_id": 84213, "text_hash": "3f9a…",
 "law_name": "조세특례제한법", "article_key": "16-1", "effective_from": "2026-01-01",
 "text": "…조문 원문…", "delegations": [{"phrase": "대통령령으로 정하는 …", "target_text": "…"}]}
```

결과 한 줄은 skill이 정한 JSON 스키마를 따르고, 반드시 `job_id`와 `extractor`(`<cowork|cc>:<모델>:<skill>@<버전>`, 결정 22)를 담는다.

`kloe agent`로 돌릴 때는 실행기가 `queue → claimed` rename과 `touch`, `.tmp → out` rename을 하고, 에이전트는 배치를 읽고 `.tmp` 하나를 쓰기만 한다. 실패한 배치(종료 코드 오류, 결과 없음, 줄 수 불일치, 시간 초과)는 queue로 돌아간다.

## 2. 일정

| 언제 | 계층 | 하는 일 |
|---|---|---|
| 매일 03:00 | L0 (launchd) | `leo nightly`: 수집 → 정규화 → 위임 연결 → `out/` 가져오기 + 검증 → 새 배치 내보내기 → gap SQL → 변경 피드 |
| 매일 몇 차례 | L1 | `queue/classify`, `queue/extract`에서 배치를 K개 처리 (처리량은 첫 주에 측정해서 정함) |
| 토요일 | L2 | 이번 주 verified fact로 opportunity 합성, G2·G5·G6 판정, 순위 매기기 |
| 주말 아무 때 | L3 | 너와 대화: 카탈로그 탐색, 검토 판정, 연결 아이디어 기록 |
| 일요일 밤 | L4 | `leo export weekly` → 보고서 작성 |

## 3. 데이터 모델

### 3.1 Fact (L1 산출물, 조문 단위)

| 필드 | 내용 |
|---|---|
| `is_benefit` | 혜택 조항인가 (분류 단계는 애매하면 true, 추출 단계에서 다시 판정) |
| `role` | 추출 단계: `benefit`(혜택 본문) · `condition`(다른 조문 혜택의 범위·요건·계산·한도) · `none`(위임만, 가산세·추징, 절차, 배제). none이면 is_benefit=false |
| `parent_ref` / `not_benefit_reason` | condition이면 본문에 적힌 상위 조문 표기 그대로 / none이면 이유 |
| `benefit_type` | `deduction`, `credit`, `exemption`, `nontaxable`, `deferral`, `subsidy`, `loan`, `guarantee`, `fee_waiver`, `reward` |
| `trigger_kind` / `trigger` | 혜택이 생기는 계기와 그 설명 (`invest`, `hire`, `relocate`, `hold`, `found`, `spend`, `report`, `participate`) |
| `beneficiary` | 수혜 주체 |
| `benefit_size` | 원문 + 파싱한 수치 `{raw, rate, cap_krw, unit}` |
| `conditions[]`, `exclusions[]`, `obligations[]` | 태그가 붙은 텍스트 (실행 규칙 아님) |
| `time_window` | 시행일, 일몰, 적용시기(부칙) |
| `reward_terms` | `reward`일 때: `reporter_scope`, `proxy_allowed`, `payout_basis`, `payout_timing`, `exclusions`, `evidence_required` |
| `quotes[]` | 필드별 원문 인용 `{field, quote, start, end}` |
| `uncertain[]` | 판단하지 못한 필드와 이유 |

### 3.2 Opportunity (L2 산출물, "행위 → 혜택")

fact 필드를 기회 단위로 합친 것에 아래를 더한다.

| 필드 | 내용 |
|---|---|
| `fact_ids[]` | 근거 fact (= 근거 조문과 인용) |
| `substance` | `real_activity` / `form_only` / `unclear`. 실질과세원칙 위험 표시 |
| `business_signal[]` | `repeatable`, `scalable`, `needs_entity_data`, `insider_only` |
| `time_signal` | `new`, `sunset_soon`, `extended`, `rate_changed`, `none` |
| `rank_rationale` | 규모·진입장벽·시간 신호를 근거로 한 순위 설명 (근거 없는 확률 금지) |

### 3.3 Gap (트랙 B)

| 코드 | 허점 유형 | 탐지 |
|---|---|---|
| G1 | 혜택은 있는데 사후관리·환수 규정이 없음 | L0 SQL |
| G2 | 같은 행위에 혜택 둘이 걸리는데 중복배제가 없음 | L0 SQL로 후보 → L2 판정 |
| G3 | 위임 공백: 법률이 위임했는데 하위법령에 해당 조문이 없음 | L0 (결정론적) |
| G4 | 만성 특례: 일몰이 반복 연장됨 | L0 (버전 이력) |
| G5 | 요건이 모호함 ("상당한", "등", "필요하다고 인정하는") | L0 키워드 → L2 판정 |
| G6 | 보상 제도가 있는데 신고 주체·증거 요건 때문에 사실상 작동하지 않음 | L2 |

gap은 후보다. 예산낭비신고나 제도개선 제안으로 제출할지는 L3에서 사람이 정한다.

### 3.4 Idea (L3 산출물)

HITL 대화에서 나온 연결 아이디어. 예: "일몰 임박 세액공제 → 해당 섹터 이벤트 데이터", "보상 제도 X → 공개자료 기반 서비스 가능성".

## 4. 스키마 (초안)

```sql
create table source_document (
  id            bigserial primary key,
  law_id        text not null,
  law_name      text not null,
  law_kind      text not null,          -- 법률 / 대통령령 / 총리령·부령 / 고시 / 조례
  version_key   text not null,
  promulgated   date,
  effective     date not null,
  url           text not null,
  file_path     text not null,
  sha256        text not null,
  fetched_at    timestamptz not null default now(),
  unique (law_id, version_key)
);

create table provision (
  id             bigserial primary key,
  document_id    bigint not null references source_document(id),
  article_key    text not null,         -- '16', '16-1-3' (조-항-호)
  heading        text,
  text           text not null,
  text_hash      text not null,
  effective_from date not null,
  effective_to   date,
  unique (document_id, article_key)
);

create table delegation (
  id          bigserial primary key,
  source_id   bigint not null references provision(id),
  target_id   bigint references provision(id),            -- null이면 G3 후보
  phrase      text not null,
  method      text not null check (method in ('regex', 'llm', 'manual'))
);

create table batch (
  id           bigserial primary key,
  stage        text not null check (stage in ('classify', 'extract', 'synthesize', 'report')),
  file_name    text not null unique,
  status       text not null default 'queued',  -- queued / claimed / ingested / failed
  extractor    text,                            -- 결과 파일에서 채움
  exported_at  timestamptz not null default now(),
  ingested_at  timestamptz,
  fail_reason  text
);

create table fact (
  id            bigserial primary key,
  provision_id  bigint not null references provision(id),
  text_hash     text not null,          -- 이 해시 기준으로 추출됨. 조문이 바뀌면 stale
  batch_id      bigint not null references batch(id),
  is_benefit    boolean not null,
  payload       jsonb not null,         -- 3.1 필드 전체
  status        text not null default 'extracted',  -- extracted / verified / rejected / stale
  extractor     text not null,
  created_at    timestamptz not null default now(),
  unique (provision_id, text_hash, extractor)
);

create table opportunity (
  id              bigserial primary key,
  title           text not null,
  fact_ids        bigint[] not null,
  payload         jsonb not null,       -- 3.2 필드 전체
  status          text not null default 'proposed', -- proposed / approved / rejected / needs_recheck
  superseded_by   bigint references opportunity(id),
  extractor       text not null,
  week            text not null,        -- '2026-W45'
  created_at      timestamptz not null default now()
);

create table gap (
  id              bigserial primary key,
  code            text not null,
  opportunity_ids bigint[] not null default '{}',
  provision_ids   bigint[] not null default '{}',
  summary         text not null,
  status          text not null default 'candidate',
  detected_by     text not null,        -- 'sql' 또는 extractor
  created_at      timestamptz not null default now()
);

create table idea (
  id              bigserial primary key,
  week            text not null,
  title           text not null,
  body            text not null,
  opportunity_ids bigint[] not null default '{}',
  tags            text[] not null default '{}',   -- quant / business / report-to-gov …
  created_at      timestamptz not null default now()
);

create table review (
  id          bigserial primary key,
  target_kind text not null check (target_kind in ('fact', 'opportunity', 'gap')),
  target_id   bigint not null,
  verdict     text not null check (verdict in ('approve', 'edit', 'reject')),
  note        text,
  diff        jsonb,
  reviewed_at timestamptz not null default now()
);

create table change_event (
  id              bigserial primary key,
  law_id          text not null,
  article_key     text not null,
  old_provision   bigint references provision(id),
  new_provision   bigint references provision(id),
  kind            text not null,        -- added / amended / repealed
  detected_at     timestamptz not null default now()
);
```

opportunity는 덮어쓰지 않는다. 새 행을 만들고 이전 행의 `superseded_by`에 연결한다. 조문 해시가 바뀌면 그 조문의 fact는 `stale`로, 그 fact를 쓰는 opportunity는 `needs_recheck`로 바뀐다.

## 5. 기계 검증 (L0, 결과 파일을 가져올 때)

- 결과 줄의 `job_id`가 배치에 있는가, 그리고 빠진 줄은 없는가.
- Pydantic 스키마 검증.
- 모든 `quotes[].quote`가 조문 원문 안에 **글자 그대로** 있는가 (공백 정규화 후 부분 문자열).
- 수치 필드가 인용문 안의 숫자와 일치하는가.
- `time_window`가 조문 버전의 유효기간과 정합적인가.
- 추출의 `parent_ref`가 조문 원문 안에 있는가. `role`과 `is_benefit`이 맞물리는가 (스키마).
- L2 결과는 `fact_ids`가 모두 `verified` 상태인가.

통과하면 `verified` 또는 `proposed`, 실패하면 줄 단위로 `failed`에 사유를 남긴다. 배치는 실패한 줄만 모아 한 번 다시 대기열에 넣는다.

## 6. Skills (에이전트 지시문, git 관리)

실제 지시는 skill 파일(`skills/<이름>/SKILL.md`)에 두고, `kloe agent`나 예약 작업 프롬프트는 skill을 가리키기만 한다. skill 버전이 곧 `extractor` 버전이다. `tests/test_skills.py`가 skill 안의 결과 예시를 스키마와 검증에 통과시킨다.

| skill | 계층 | 내용 |
|---|---|---|
| `kloe-classify` (v0.1, 있음) | L1 | 혜택 조항 판정 기준, 유형 정의, 경계 사례 예시 |
| `kloe-extract` (v0.1, 있음) | L1 | role 판정, 3.1 스키마, 인용 규칙, `uncertain` 사용 규칙 |
| `kloe-extract-program` (v0.1, 있음) | L1 | 공고 추출 (결정 19) |
| `kloe-synthesize` (아직) | L2 | fact 묶기 규칙, substance·business_signal·time_signal 기준, G2·G5·G6 판정 기준, 순위 근거 작성법 |
| `kloe-explore` (아직) | L3 | 카탈로그 탐색 방법, 검토 판정과 아이디어를 기록하는 명령 |
| `kloe-weekly-report` (아직) | L4 | 보고서 템플릿과 작성 규칙 |

공통 규칙: 배치 파일에 없는 정보를 지어내지 않는다, 판단 못 한 필드는 `uncertain`에 적는다, 부정수급·명의 위장·허위 증빙·실질과 다른 거래 설계는 기회로 만들지 않는다.

## 7. 주간 보고서 (L4)

`reports/2026-W45.md`

1. **요약**: 이번 주에 가장 중요한 3가지
2. **법령 변경**: 신설·개정·폐지, 영향받는 기회
3. **신규·변경 기회 Top N**: 규모, 시간 신호, 근거 조문 링크
4. **보상 제도와 사업화 신호**
5. **제도 허점 후보**: G1~G6별
6. **HITL 아이디어**: 이번 주 `idea` 기록과 다음 단계
7. **파이프라인 지표**: 처리한 조문·배치 수, 검증 실패율, 재현율, 정밀도, 모델별 처리량
8. **다음 주 할 일**

보고서의 모든 주장은 opportunity·gap ID와 조문 인용으로 연결한다.

## 8. 평가

| 지표 | 정답 출처 | 측정 |
|---|---|---|
| 재현율 (조세) | 조세지출예산서 항목 + 근거 조문 | 항목 중 근거 조문을 공유하는 opportunity가 있는 비율 |
| 재현율 (보상) | 신고보상 제도 목록 (Phase 0에서 출처 확인) | 위와 같음 |
| 깔때기 손실 | 위 정답 셋 | 키워드 필터·분류 단계에서 정답 조문이 몇 개 빠졌나 |
| 정밀도 | `review` | approve / (approve + reject) |
| 필드 정확도 | `review`의 edit diff | 필드별 수정 비율 |
| 모델 계층 비교 | 같은 배치를 Haiku·Sonnet으로 추출 | 검증 통과율, 필드 정확도 차이 |
| 처리량 | `batch` 로그 | 실행당 배치 수, 주간 처리 조문 수 |

"모델 계층 비교"는 같은 일을 어느 수준의 모델까지 내려서 할 수 있는지 보여주는 결과라서 CV에서 내세울 만하다.

## 9. 코드 구조

```text
KLOE/
  pyproject.toml
  docker-compose.yml          # postgres
  migrations/                 # 0001_init.sql 등
  config/laws.txt             # 수집할 법령 ID
  skills/                     # 6절 skill 파일
  scripts/                    # nightly.sh, install_launchd.sh, launchd/ 템플릿
  src/kloe/
    cli.py                    # migrate / fetch / load / link / export / ingest / requeue / agent / show / nightly / 공고 명령
    collect/law_api.py        # 법제처 Open API, 원본 저장
    normalize/parse.py        # XML → provision
    link/delegation.py        # 정규식 위임 연결
    queue/export.py           # 배치 파일 생성
    queue/ingest.py           # 결과 파일 가져오기 + 검증
    queue/runner.py           # kloe agent: claude -p 헤드리스 실행기
    verify.py                 # 5절
    schema.py                 # fact / program Pydantic 모델
    db.py                     # Postgres 적재
  work/                       # 파일 핸드오프 (gitignore)
  data/raw/                   # 원본 (gitignore)
  data/golden/                # 정답 셋 CSV
  reports/                    # 보고서
  tests/                      # fixtures/ (합성 XML + 실제 발췌), agent_sim.py (가짜 에이전트)
```

아직 없는 것: `gaps.py`(G1·G3·G4 SQL), `feed.py`(변경 이벤트 피드), `eval.py`(8절 리포트), review·idea 명령.

테스트 대상: 파서, 위임 연결 정규식, 인용 검증, 배치 내보내기/가져오기 왕복, `requeue`. LLM 계층은 고정된 결과 파일 샘플로 ingest 경로만 테스트한다.

## 10. 로드맵

| Phase | 내용 | 완료 기준 |
|---|---|---|
| 0 | 정답 셋: 조세지출예산서 항목·근거 조문·금액, 신고보상 제도 목록. 이 문서의 사실 관계 확인 (Cowork + korean-law MCP) | `data/golden/*.csv`, 확인 메모 |
| 1 | L0: 조세 법령 수집 → 정규화 → 위임 연결 → 배치 내보내기/가져오기 (완료. 연혁·부칙 남음) | 기준일 조문 재현, 배치 왕복 테스트 통과 |
| 2 | L1: `kloe-classify`, `kloe-extract` + `kloe agent` + 검증 (진행 중: 분류 완료, 추출 준비됨) | 첫 재현율·검증 실패율·처리량 수치 |
| 3 | L2·L4: `kloe-synthesize`, gap 쿼리, `kloe-weekly-report` | 첫 주간 보고서 |
| 4 | L3 정착: `kloe-explore`로 검토와 아이디어 기록 반복 | 정밀도 수치, idea 누적 |
| 5 | 보상 조항: 전체 법령 키워드 스윕 → L1·L2 | `reward` 카탈로그 |
| 6 | 보조금·고시·조례로 확장 (보조금24·K-Startup 공고는 먼저 붙음, 결정 18) | 영역별 재현율 |

## 11. 원칙

1. 모든 필드는 원문 인용과 조문 버전에 연결한다.
2. 공포일·시행일·적용시기(부칙)·일몰을 구분한다.
3. 법률·시행령·고시·해석례의 효력을 구분한다.
4. DB에는 코드만 쓴다. LLM 결과는 검증을 통과해야 들어간다.
5. 모르면 `uncertain`으로 남긴다. 추측으로 채우지 않는다.
6. 법령 개정이나 모델·skill 변경 때 평가를 다시 돌린다.
7. 부정수급, 명의 위장, 허위 증빙, 실질과 다른 거래 설계는 기회로 분류하지 않는다. `form_only`는 위험 표시이지 추천이 아니다.
8. LLM 실행은 구독 안에서 앱이 제공하는 기능(Claude Code 헤드리스 포함)으로만 한다.

## 12. 열린 질문

1. ~~Cowork 예약 작업이 이 저장소 폴더를 읽고 쓰고 `leo` CLI를 실행할 수 있는가.~~ 해결: 읽기·쓰기는 되고 CLI는 안 된다. `kloe` 실행은 launchd가 맡고, 에이전트는 `work/` 파일만 다룬다 (결정 16).
2. ~~예약 작업에서 모델을 지정하는 방식.~~ 해결: 헤드리스는 `claude -p --model`로 지정한다 (결정 20). Cowork는 설정에서 Haiku를 고른다 (결정 17).
3. 실행당 처리 가능한 배치 수와 구독 한도 소모. 헤드리스 병렬 2에서 배치(20건)당 약 40초 (2026-11-12). 한도 소모는 미측정.
4. 조세지출예산서가 기계 판독 가능한 형식인가.
5. 신고보상 제도를 종합한 공식 목록이 있는가.
6. 법제처 Open API의 연혁 조문 범위와 호출 한도.
