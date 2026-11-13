"""L1 결과 줄의 Pydantic 스키마 (설계 3.1절). skill 파일이 이 스키마를 따른다."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BenefitType = Literal[
    "deduction", "credit", "exemption", "nontaxable", "deferral",
    "subsidy", "loan", "guarantee", "fee_waiver", "reward",
]
Role = Literal["benefit", "condition", "none"]  # 혜택 본문 / 혜택의 요건·범위·계산·한도 / 혜택 아님
TriggerKind = Literal["invest", "hire", "relocate", "hold", "found", "spend", "report", "participate"]

EXTRACTOR_PATTERN = r"^(cowork|cc):[^:\s]+:[^:\s]+$"  # <실행 환경 cowork|cc>:<모델>:<skill 버전>


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quote(_Strict):
    field: str
    quote: str = Field(min_length=1)
    start: int | None = None
    end: int | None = None


class BenefitSize(_Strict):
    raw: str
    rate: float | None = Field(default=None, ge=0, le=1)  # 0.1 = 10%
    cap_krw: int | None = Field(default=None, ge=0)
    unit: str | None = None


class TaggedText(_Strict):
    tag: str
    text: str


class TimeWindow(_Strict):
    effective_from: date | None = None
    sunset: date | None = None
    applies_from: date | None = None
    note: str | None = None


class RewardTerms(_Strict):
    reporter_scope: str | None = None
    proxy_allowed: bool | None = None
    payout_basis: str | None = None
    payout_timing: str | None = None
    exclusions: list[str] = []
    evidence_required: str | None = None


class Uncertain(_Strict):
    field: str
    reason: str


class FactPayload(_Strict):
    is_benefit: bool
    role: Role | None = None
    parent_ref: str | None = None  # condition이면 본문에 적힌 상위 조문 표기 그대로 (예: "법 제29조의4제1항")
    not_benefit_reason: str | None = None  # role=none 일 때 이유
    benefit_type: BenefitType | None = None
    trigger_kind: TriggerKind | None = None
    trigger: str | None = None
    beneficiary: str | None = None
    benefit_size: BenefitSize | None = None
    conditions: list[TaggedText] = []
    exclusions: list[TaggedText] = []
    obligations: list[TaggedText] = []
    time_window: TimeWindow | None = None
    reward_terms: RewardTerms | None = None
    quotes: list[Quote] = []
    uncertain: list[Uncertain] = []

    @model_validator(mode="after")
    def _benefit_fields(self) -> FactPayload:
        unsure = {u.field for u in self.uncertain}
        if self.role == "none" and self.is_benefit:
            raise ValueError("role=none인데 is_benefit=true")
        if self.role in ("benefit", "condition") and not self.is_benefit:
            raise ValueError(f"role={self.role}인데 is_benefit=false")
        if self.role == "none" and not self.not_benefit_reason:
            raise ValueError("role=none이면 not_benefit_reason이 있어야 한다")
        if self.is_benefit:
            if self.benefit_type is None and "benefit_type" not in unsure:
                raise ValueError("혜택 조항인데 benefit_type이 없고 uncertain에도 없다")
            if not self.quotes:
                raise ValueError("혜택 조항인데 인용(quotes)이 없다")
        if self.benefit_type == "reward" and self.reward_terms is None and "reward_terms" not in unsure:
            raise ValueError("reward인데 reward_terms가 없고 uncertain에도 없다")
        return self


class ClassifyResult(_Strict):
    job_id: str
    extractor: str = Field(pattern=EXTRACTOR_PATTERN)
    is_benefit: bool
    benefit_type: BenefitType | None = None
    reason: str | None = None
    quotes: list[Quote] = []


class ExtractResult(_Strict):
    job_id: str
    extractor: str = Field(pattern=EXTRACTOR_PATTERN)
    fact: FactPayload


Applicant = Literal["individual", "student", "business", "startup", "sme", "nonprofit", "institution", "other"]


class Eligibility(_Strict):
    applicant: list[Applicant] = []
    age_min: int | None = Field(default=None, ge=0)
    age_max: int | None = Field(default=None, ge=0)
    regions: list[str] = []
    business_age_max_years: float | None = Field(default=None, ge=0)  # 창업 N년 이내
    income: str | None = None
    other: list[TaggedText] = []


class ProgramPayload(_Strict):
    """공고 하나에서 뽑은 혜택 (kloe-extract-program). 공고는 거의 다 혜택이라 분류 단계 없이 바로 추출한다."""

    is_benefit: bool
    benefit_type: BenefitType | None = None
    beneficiary: str | None = None
    summary: str | None = None
    eligibility: Eligibility | None = None
    benefit_size: BenefitSize | None = None
    apply_start: date | None = None
    apply_end: date | None = None
    apply_method: str | None = None
    legal_basis: list[str] = []  # 원문에 적힌 근거 법령 이름·조문 그대로
    quotes: list[Quote] = []
    uncertain: list[Uncertain] = []

    @model_validator(mode="after")
    def _benefit_fields(self) -> ProgramPayload:
        unsure = {u.field for u in self.uncertain}
        if self.is_benefit:
            if self.benefit_type is None and "benefit_type" not in unsure:
                raise ValueError("혜택 공고인데 benefit_type이 없고 uncertain에도 없다")
            if not self.quotes:
                raise ValueError("혜택 공고인데 인용(quotes)이 없다")
        if self.apply_start and self.apply_end and self.apply_end < self.apply_start:
            raise ValueError("apply_end가 apply_start보다 앞섬")
        e = self.eligibility
        if e and e.age_min is not None and e.age_max is not None and e.age_max < e.age_min:
            raise ValueError("eligibility.age_max가 age_min보다 작음")
        return self


class ProgramResult(_Strict):
    job_id: str
    extractor: str = Field(pattern=EXTRACTOR_PATTERN)
    fact: ProgramPayload


# ---------- 추출 감사 (kloe-audit) ----------
# 정답 셋이 없으므로, 상위 모델이 추출 표본을 원문과 다시 대조해 계통 오류를 찾는다. fact는 고치지 않는다.
AuditDirection = Literal["lost", "wrong", "extra"]  # lost: 혜택·요건·한도를 놓침 / wrong: 값·분류가 틀림 / extra: 원문에 없는 것을 넣음


class AuditIssue(_Strict):
    field: str  # FactPayload 필드 이름. 하위 필드는 점 표기 (benefit_size.rate)
    direction: AuditDirection
    problem: str = Field(min_length=1)
    quote: str = Field(min_length=1)  # 지적의 근거가 되는 조문 원문 구간 (글자 그대로)
    suggested: str | None = None


class AuditResult(_Strict):
    job_id: str
    extractor: str = Field(pattern=EXTRACTOR_PATTERN)
    ok: bool
    issues: list[AuditIssue] = []

    @model_validator(mode="after")
    def _ok_matches_issues(self) -> AuditResult:
        if self.ok and self.issues:
            raise ValueError("ok=true인데 issues가 있다")
        if not self.ok and not self.issues:
            raise ValueError("ok=false인데 issues가 없다")
        return self


RESULT_MODELS: dict[str, type[BaseModel]] = {"classify": ClassifyResult, "extract": ExtractResult, "program": ProgramResult,
                                             "audit": AuditResult}
