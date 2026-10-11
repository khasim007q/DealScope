"""Typed domain contracts. Every untrusted boundary (user input, provider JSON, LLM output)
is validated into one of these models before it is used."""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dealscope.domain.enums import (
    CaseStage,
    ClaimType,
    EvidenceKind,
    RunMode,
    Severity,
    SignalId,
    SignalState,
    ToolName,
    VerificationStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Input hygiene
# ---------------------------------------------------------------------------

_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def normalize_domain(raw: str) -> str:
    """Strip scheme/path/port/www and validate safe public hostname syntax.

    Rejects IPs, localhost, single-label names, file paths and injected schemes."""
    value = (raw or "").strip().lower()
    if not value:
        raise ValueError("domain is empty")
    if "://" in value:
        scheme, _, value = value.partition("://")
        if scheme not in {"http", "https"}:
            raise ValueError(f"unsupported URL scheme: {scheme}")
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in value:
        raise ValueError("credentials in domain are not allowed")
    value = value.split(":", 1)[0].rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("IP addresses are not allowed; provide a company domain")
    if value in _BLOCKED_HOSTS or value.endswith(".local") or value.endswith(".localhost"):
        raise ValueError("local hostnames are not allowed")
    labels = value.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
        raise ValueError(f"invalid domain: {raw!r}")
    if not re.match(r"^[a-z]{2,63}$", labels[-1]):
        raise ValueError(f"invalid top-level domain in {raw!r}")
    return value


Domain = Annotated[str, Field(min_length=3, max_length=253)]


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_domain: Domain
    competitor_domains: list[Domain] = Field(min_length=2, max_length=5)
    deal_thesis: str = Field(min_length=10, max_length=2000)
    lookback_months: int = Field(default=12, ge=3, le=36)
    max_case_credits: Decimal = Field(default=Decimal("300"), gt=0)
    mode: RunMode = RunMode.SYNTHETIC
    # Thesis-critical capabilities (S3). Defaults suit a generic software platform thesis.
    critical_capabilities: list[str] = Field(
        default_factory=lambda: ["platform_engineering", "security", "data_ml", "reliability"]
    )

    @field_validator("target_domain", mode="before")
    @classmethod
    def _norm_target(cls, v: str) -> str:
        return normalize_domain(v)

    @field_validator("competitor_domains", mode="before")
    @classmethod
    def _norm_peers(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in v or []:
            if not str(raw).strip():
                continue
            d = normalize_domain(str(raw))
            if d not in seen:
                seen.append(d)
        return seen

    @field_validator("deal_thesis")
    @classmethod
    def _strip_thesis(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("deal thesis is required (at least 10 characters)")
        return v

    @model_validator(mode="after")
    def _target_not_peer(self) -> CaseInput:
        if self.target_domain in self.competitor_domains:
            raise ValueError("target domain cannot also be listed as a competitor")
        return self

    def all_domains(self) -> list[str]:
        return [self.target_domain, *self.competitor_domains]


# ---------------------------------------------------------------------------
# Evidence (normalized, allowlisted payloads only — no contact data)
# ---------------------------------------------------------------------------

RoleGroup = Literal[
    "technical_leadership", "senior_technical_ic", "security", "data_ml", "other_technical", "non_technical"
]
Capability = Literal["platform_engineering", "security", "data_ml", "reliability", "general_engineering", "other"]


class CompanyProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    domain: str
    total_headcount: int | None = None
    # Growth percentages keyed by the exact period returned by the provider, e.g. {"6m": 11.0, "12m": 18.5}.
    total_growth_pct: dict[str, float] = Field(default_factory=dict)
    engineering_headcount: int | None = None
    engineering_growth_pct: dict[str, float] = Field(default_factory=dict)
    job_openings_count: int | None = None
    funding_total_usd: float | None = None
    industry: str | None = None
    hq_country: str | None = None
    # Provider values dropped as implausible (e.g. 'engineering_growth_pct.3m=303.9 dropped: >100% in <=6m').
    data_quality_flags: list[str] = Field(default_factory=list)


class PersonHistoryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_ref: str  # opaque stable hash of the provider person id/profile URL; no names
    role_group: RoleGroup
    capability: Capability = "general_engineering"
    title_at_target: str | None = None
    seniority: str | None = None
    target_start: str | None = None  # "YYYY-MM" or "YYYY-MM-DD" as returned
    target_end: str | None = None  # None means no completed interval was returned
    currently_at_target: bool | None = None
    current_employer_name: str | None = None
    current_employer_domain: str | None = None
    current_title: str | None = None


class JobPostingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    role_group: RoleGroup = "other_technical"
    capability: Capability = "general_engineering"
    date_added: str | None = None
    date_updated: str | None = None
    reposted: bool | None = None
    number_of_openings: int | None = None
    url: str | None = None
    category: str | None = None


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: new_id("ev"))
    case_id: str
    kind: EvidenceKind
    subject_domain: str
    entity_id: str | None = None
    source_provider: Literal["crustdata", "fixture"]
    source_endpoint: str
    source_url: str | None = None
    source_record_id: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    valid_from: str | None = None
    valid_to: str | None = None
    field_coverage: list[str] = Field(default_factory=list)
    freshness_class: Literal["current", "historical", "unknown"] = "current"
    payload: CompanyProfilePayload | PersonHistoryPayload | JobPostingPayload
    raw_hash: str | None = None
    dedup_key: str
    tool_run_id: str | None = None
    credit_estimate: Decimal | None = None
    credit_actual: Decimal | None = None
    independence_group: str  # records sharing a group are NOT independent corroboration
    synthetic: bool

    @model_validator(mode="after")
    def _synthetic_matches_provider(self) -> EvidenceRecord:
        if self.synthetic != (self.source_provider == "fixture"):
            raise ValueError("synthetic flag must match source_provider (fixture <=> synthetic)")
        expected = {
            EvidenceKind.COMPANY_PROFILE: CompanyProfilePayload,
            EvidenceKind.PERSON_HISTORY: PersonHistoryPayload,
            EvidenceKind.JOB_POSTING: JobPostingPayload,
        }[self.kind]
        if not isinstance(self.payload, expected):
            raise ValueError(f"payload type does not match kind {self.kind}")
        return self


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class SignalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: SignalId
    name: str
    signal_version: str
    state: SignalState
    score: float | None = Field(default=None, ge=0, le=100)
    weight: float
    raw_measure: dict[str, object] = Field(default_factory=dict)
    benchmark: dict[str, object] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=100)
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    calculated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _score_requires_scorable(self) -> SignalResult:
        if self.state in (SignalState.NOT_SCORED,) and self.score is not None:
            raise ValueError("not_scored signals must not carry a score")
        if self.state == SignalState.SCORABLE and self.score is None:
            raise ValueError("scorable signals must carry a score")
        return self


class Scorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[SignalResult]
    risk_score: float | None  # None when no signal is assessable
    coverage_pct: float
    coverage_label: Literal["insufficient_evidence", "provisional", "coverage_threshold_met"]
    risk_band: Literal["Low signal", "Watch", "Elevated", "High signal"] | None
    evidence_confidence: float  # separate metric from risk
    signal_version: str


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


class FindingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(default_factory=lambda: new_id("cl"))
    text: str = Field(min_length=3, max_length=1200)
    claim_type: ClaimType
    severity: Severity = Severity.LOW
    confidence: float = Field(default=50, ge=0, le=100)
    subject_domain: str | None = None
    related_signals: list[SignalId] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus | None = None
    verification_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Planner actions (LLM output — untrusted until validated)
# ---------------------------------------------------------------------------


class EnrichCompanyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str


class SearchPeopleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_group: Literal["technical_leadership", "senior_technical_ic", "security", "data_ml"]
    relationship: Literal["past_target_employment", "current_target_employment"]
    competitor_domain: str | None = None  # restrict current employer to one registered peer
    limit: int = Field(default=25, ge=1, le=100)


class SearchJobsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    role_terms: list[Literal["engineering_leadership", "platform", "security", "data_ml", "reliability"]] = Field(
        min_length=1, max_length=5
    )
    lookback_days: int = Field(default=90, ge=7, le=365)
    limit: int = Field(default=25, ge=1, le=50)


class StopArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolName
    arguments: dict[str, object] = Field(default_factory=dict)
    question: str = Field(default="", max_length=500)
    why_this_action: str = Field(default="", max_length=800)
    expected_information_gain: Literal["low", "medium", "high"] = "medium"
    stop_after_action_if: list[str] = Field(default_factory=list)
    decided_by: Literal["llm", "deterministic_fallback", "baseline"] = "llm"

    def typed_arguments(self) -> EnrichCompanyArgs | SearchPeopleArgs | SearchJobsArgs | StopArgs:
        model = {
            ToolName.ENRICH_COMPANY: EnrichCompanyArgs,
            ToolName.SEARCH_PEOPLE: SearchPeopleArgs,
            ToolName.SEARCH_JOBS: SearchJobsArgs,
            ToolName.STOP: StopArgs,
        }[self.action]
        return model.model_validate(self.arguments)


# ---------------------------------------------------------------------------
# Case state
# ---------------------------------------------------------------------------


class CompletedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int
    action: PlannerAction
    tool_run_id: str | None
    outcome: str  # succeeded | cached | blocked:<reason> | failed:<reason>
    new_evidence_ids: list[str] = Field(default_factory=list)
    at: datetime = Field(default_factory=utcnow)


class CaseState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(default_factory=lambda: new_id("case"))
    input: CaseInput
    mode: RunMode
    stage: CaseStage = CaseStage.CREATED
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    current_question: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    completed_actions: list[CompletedAction] = Field(default_factory=list)
    iteration_count: int = 0
    tool_call_count: int = 0
    runtime_seconds_used: float = 0.0
    credit_budget: Decimal
    credit_reserved: Decimal = Decimal("0")
    credit_estimated_used: Decimal = Decimal("0")
    credit_actual_used: Decimal = Decimal("0")
    credit_unknown_calls: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    scorecard: Scorecard | None = None
    claims: list[FindingClaim] = Field(default_factory=list)
    unavailable_tools: dict[str, str] = Field(default_factory=dict)  # tool -> reason
    latest_checkpoint_id: int | None = None
    finish_reason: str | None = None
    run_label: str = "improved"  # "baseline" | "improved" (eval experiment)
