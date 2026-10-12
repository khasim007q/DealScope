"""Allowlisted diligence tools.

Every external call goes through `ToolExecutor.execute`, which enforces, in order:
argument schema + domain allowlist -> idempotency (no replay of completed or unknown-outcome calls)
-> response cache -> credit reservation (fail closed) -> durable `tool_run` row -> provider call with
bounded retry -> evidence persistence + ledger settlement. Nothing here accepts raw LLM text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from dealscope.analysis.data_quality import sanitize_company
from dealscope.budget.governor import BudgetDenied, CreditGovernor
from dealscope.domain.enums import EvidenceKind, ToolName, ToolRunStatus
from dealscope.domain.models import (
    CaseState,
    CompanyProfilePayload,
    EnrichCompanyArgs,
    EvidenceRecord,
    JobPostingPayload,
    PersonHistoryPayload,
    PlannerAction,
    SearchJobsArgs,
    SearchPeopleArgs,
    normalize_domain,
)
from dealscope.observability import tracing
from dealscope.persistence.repository import Repository, cache_key, idempotency_key
from dealscope.providers.base import (
    AuthError,
    BadRequestError,
    DataSource,
    InsufficientCreditsError,
    NormalizedItem,
    ProviderError,
    ProviderResult,
    SchemaError,
    UnknownOutcomeError,
)

log = logging.getLogger(__name__)

OPERATION = {
    ToolName.ENRICH_COMPANY: "company_enrich",
    ToolName.SEARCH_PEOPLE: "person_search",
    ToolName.SEARCH_JOBS: "job_search",
}
ENDPOINT = {
    ToolName.ENRICH_COMPANY: "/company/enrich",
    ToolName.SEARCH_PEOPLE: "/person/search",
    ToolName.SEARCH_JOBS: "/job/search",
}
_PAYLOAD_TYPES = {
    EvidenceKind.COMPANY_PROFILE: CompanyProfilePayload,
    EvidenceKind.PERSON_HISTORY: PersonHistoryPayload,
    EvidenceKind.JOB_POSTING: JobPostingPayload,
}


class ToolRejected(ValueError):
    """Action failed validation before any budget reservation or request."""


@dataclass
class ToolOutcome:
    status: ToolRunStatus
    tool_run_id: str | None = None
    new_evidence_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    reason: str | None = None
    fatal: bool = False  # stop live external calls entirely (auth / out of credits)
    disable_tool: bool = False  # don't offer this tool again in this case
    attempts: int = 0
    credits_estimate: Decimal | None = None
    credits_actual: Decimal | None = None
    result_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.status in (ToolRunStatus.SUCCEEDED, ToolRunStatus.CACHED):
            return self.status.value
        return f"{self.status.value}:{self.reason}"


def quantity_for(action: PlannerAction, settings_max_people: int) -> int:
    args = action.typed_arguments()
    if isinstance(args, EnrichCompanyArgs):
        return 1
    if isinstance(args, SearchPeopleArgs):
        return min(args.limit, settings_max_people)
    if isinstance(args, SearchJobsArgs):
        return args.limit
    return 0


class ToolExecutor:
    def __init__(
        self,
        repo: Repository,
        governor: CreditGovernor,
        source: DataSource,
        *,
        api_version: str,
        max_people_results: int = 100,
        as_of: date | None = None,
    ) -> None:
        self.repo = repo
        self.governor = governor
        self.source = source
        self.api_version = api_version
        self.max_people_results = max_people_results
        self.as_of = as_of
        self._ctx: dict[str, Any] = {}

    # Called by the provider's retry helper (wired by the orchestrator factory).
    def on_retry(self, attempt: int, reason: str, delay: float) -> None:
        case_id = self._ctx.get("case_id")
        span = self._ctx.get("span")
        payload = {"attempt": attempt, "reason": reason, "delay_s": round(delay, 2), "tool": self._ctx.get("tool")}
        if case_id:
            self.repo.add_event(case_id, "retry", payload)
        if span is not None:
            span.add_event("retry", payload)
        self._ctx["retries"] = self._ctx.get("retries", 0) + 1

    # ------------------------------------------------------------------
    def validate(self, state: CaseState, action: PlannerAction) -> dict[str, Any]:
        """Schema + allowlist validation. Returns canonical arguments for the provider."""
        if action.action not in OPERATION:
            raise ToolRejected(f"tool {action.action} is not an external tool")
        try:
            args = action.typed_arguments()
        except Exception as exc:
            raise ToolRejected(f"invalid arguments: {str(exc)[:200]}") from exc
        registered = set(state.input.all_domains())
        if isinstance(args, EnrichCompanyArgs):
            domain = normalize_domain(args.domain)
            if domain not in registered:
                raise ToolRejected(f"domain {domain} is not a registered target/peer")
            return {"domain": domain}
        if isinstance(args, SearchPeopleArgs):
            competitor = None
            if args.competitor_domain:
                competitor = normalize_domain(args.competitor_domain)
                if competitor not in state.input.competitor_domains:
                    raise ToolRejected(f"competitor {competitor} is not user-confirmed")
            return {
                "target_domain": state.input.target_domain,
                "role_group": args.role_group,
                "relationship": args.relationship,
                "competitor_domain": competitor,
                "limit": min(args.limit, self.max_people_results),
            }
        if isinstance(args, SearchJobsArgs):
            domain = normalize_domain(args.domain)
            if domain not in registered:
                raise ToolRejected(f"domain {domain} is not a registered target/peer")
            return {
                "domain": domain,
                "role_terms": sorted(set(args.role_terms)),
                "lookback_days": args.lookback_days,
                "limit": args.limit,
            }
        raise ToolRejected("unsupported tool")

    def estimate(self, action: PlannerAction) -> Decimal:
        """Estimate for planner display; raises BudgetDenied on unknown price."""
        return self.governor.estimate(OPERATION[action.action], quantity_for(action, self.max_people_results))

    # ------------------------------------------------------------------
    def execute(self, state: CaseState, action: PlannerAction) -> ToolOutcome:
        tool = action.action
        canonical = self.validate(state, action)
        mode = state.mode.value
        provider = self.source.provider_name
        idem = idempotency_key(state.case_id, provider, ENDPOINT[tool], canonical, self.api_version, mode)

        prior = self.repo.find_successful_tool_run(state.case_id, idem)
        if prior is not None:
            ids = [
                e.evidence_id for e in self.repo.get_evidence(state.case_id) if e.tool_run_id == prior["tool_run_id"]
            ]
            return ToolOutcome(
                ToolRunStatus.CACHED,
                prior["tool_run_id"],
                [],
                ids,
                reason="already_completed",
                notes=["completed call reused after resume; no new spend"],
            )
        for run in self.repo.find_unresolved_tool_runs(state.case_id):
            if run.get("idempotency_key") == idem:
                return ToolOutcome(
                    ToolRunStatus.BLOCKED,
                    run["tool_run_id"],
                    reason="UNKNOWN_OUTCOME_NOT_REPLAYED",
                    disable_tool=False,
                    notes=["a previous identical call has an unknown billing outcome; not replayed"],
                )

        quantity = quantity_for(action, self.max_people_results)
        operation = OPERATION[tool]
        ckey = cache_key(provider, ENDPOINT[tool], canonical, self.api_version, self._time_bucket())

        with tracing.span(
            f"tool.{tool.value}",
            kind="TOOL",
            case_id=state.case_id,
            tool=tool.value,
            mode=mode,
            operation=operation,
            quantity=quantity,
        ) as span:
            cached = self.repo.cache_get(ckey) if provider != "fixture" else None
            if cached is not None:
                run_id = self.repo.start_tool_run(state.case_id, tool.value, idem, ckey, Decimal("0"))
                result = self._result_from_cache(cached)
                ids, new = self._persist_items(state, result, run_id, None)
                self.repo.finish_tool_run(
                    run_id,
                    ToolRunStatus.CACHED,
                    result_count=result.result_count,
                    cost_actual=Decimal("0"),
                    attempt_count=0,
                )
                span.set_attribute("cache_hit", True)
                return ToolOutcome(
                    ToolRunStatus.CACHED,
                    run_id,
                    new,
                    ids,
                    result_count=result.result_count,
                    credits_actual=Decimal("0"),
                    notes=["served from response cache; no spend"],
                )

            try:
                reservation = self.governor.reserve(state.case_id, state.credit_budget, operation, quantity)
            except BudgetDenied as exc:
                run_id = self.repo.start_tool_run(state.case_id, tool.value, idem, ckey, None)
                self.repo.finish_tool_run(
                    run_id, ToolRunStatus.BLOCKED, error_code=exc.reason, error_message=str(exc)[:300]
                )
                span.set_attribute("blocked_reason", exc.reason)
                return ToolOutcome(
                    ToolRunStatus.BLOCKED,
                    run_id,
                    reason=exc.reason,
                    disable_tool=exc.reason == "UNKNOWN_PRICE_FAIL_CLOSED",
                )

            run_id = self.repo.start_tool_run(state.case_id, tool.value, idem, ckey, reservation.amount)
            self.repo.add_event(
                state.case_id,
                "tool_started",
                {"tool": tool.value, "tool_run_id": run_id, "estimate": str(reservation.amount)},
            )
            span.set_attribute("credit_estimate", float(reservation.amount))
            self._ctx = {"case_id": state.case_id, "span": span, "tool": tool.value, "retries": 0}
            try:
                result = self._call(tool, canonical)
            except UnknownOutcomeError as exc:
                self.governor.mark_unknown(reservation, exc.code)
                self.repo.finish_tool_run(
                    run_id,
                    ToolRunStatus.UNKNOWN_OUTCOME,
                    error_code=exc.code,
                    error_message=str(exc)[:300],
                    attempt_count=self._ctx.get("retries", 0) + 1,
                )
                span.record_exception(exc)
                return ToolOutcome(
                    ToolRunStatus.UNKNOWN_OUTCOME,
                    run_id,
                    reason=exc.code,
                    disable_tool=True,
                    credits_estimate=reservation.amount,
                )
            except ProviderError as exc:
                # A response was received (or retries exhausted): keep the conservative estimate charged.
                self.governor.settle(reservation, None)
                self.repo.finish_tool_run(
                    run_id,
                    ToolRunStatus.FAILED,
                    error_code=exc.code,
                    error_message=str(exc)[:300],
                    attempt_count=self._ctx.get("retries", 0) + 1,
                )
                span.record_exception(exc)
                span.set_attribute("error_code", exc.code)
                fatal = isinstance(exc, AuthError | InsufficientCreditsError)
                disable = fatal or isinstance(exc, BadRequestError | SchemaError)
                return ToolOutcome(
                    ToolRunStatus.FAILED,
                    run_id,
                    reason=exc.code,
                    fatal=fatal,
                    disable_tool=disable,
                    attempts=self._ctx.get("retries", 0) + 1,
                    credits_estimate=reservation.amount,
                )

            actual = result.credits_used if result.provider == "crustdata" else None
            self.governor.settle(reservation, actual)
            ids, new = self._persist_items(state, result, run_id, actual)
            self.repo.finish_tool_run(
                run_id,
                ToolRunStatus.SUCCEEDED,
                result_count=result.result_count,
                cost_actual=actual,
                attempt_count=result.attempts,
            )
            if result.provider == "crustdata":
                self.repo.cache_put(ckey, ENDPOINT[tool], self._result_to_cache(result), self.api_version)
            span.set_attribute("result_count", result.result_count)
            span.set_attribute("attempts", result.attempts)
            span.set_attribute("new_evidence", len(new))
            if actual is not None:
                span.set_attribute("credit_actual", float(actual))
            return ToolOutcome(
                ToolRunStatus.SUCCEEDED,
                run_id,
                new,
                ids,
                attempts=result.attempts,
                credits_estimate=reservation.amount,
                credits_actual=actual,
                result_count=result.result_count,
                notes=list(result.notes),
            )

    # ------------------------------------------------------------------
    def _call(self, tool: ToolName, a: dict[str, Any]) -> ProviderResult:
        if tool == ToolName.ENRICH_COMPANY:
            return self.source.enrich_company(a["domain"])
        if tool == ToolName.SEARCH_PEOPLE:
            return self.source.search_people(
                a["target_domain"], a["role_group"], a["relationship"], a["competitor_domain"], a["limit"]
            )
        since = (self.as_of or date.today()) - timedelta(days=a["lookback_days"])
        return self.source.search_jobs(a["domain"], a["role_terms"], since, a["limit"])

    def _time_bucket(self) -> str:
        return (self.as_of or date.today()).isoformat()

    def _persist_items(
        self, state: CaseState, result: ProviderResult, run_id: str, actual: Decimal | None
    ) -> tuple[list[str], list[str]]:
        records = [self._to_record(state, result, item, run_id) for item in result.items]
        if not records:
            return [], []
        pairs = self.repo.add_evidence_detailed(records)
        ids = [eid for eid, _ in pairs]
        new = [eid for eid, inserted in pairs if inserted]
        for eid in ids:
            if eid not in state.evidence_ids:
                state.evidence_ids.append(eid)
        return ids, new

    @staticmethod
    def _to_record(state: CaseState, result: ProviderResult, item: NormalizedItem, run_id: str) -> EvidenceRecord:
        return EvidenceRecord(
            case_id=state.case_id,
            kind=item.kind,
            subject_domain=item.subject_domain,
            source_provider=result.provider,
            source_endpoint=result.endpoint,
            source_url=item.source_url,
            source_record_id=item.source_record_id,
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            field_coverage=list(item.field_coverage),
            payload=sanitize_company(item.payload) if isinstance(item.payload, CompanyProfilePayload) else item.payload,
            raw_hash=item.raw_hash,
            dedup_key=item.dedup_key,
            tool_run_id=run_id,
            independence_group=item.independence_group,
            synthetic=result.provider == "fixture",
        )

    @staticmethod
    def _result_to_cache(result: ProviderResult) -> dict[str, Any]:
        return {
            "provider": result.provider,
            "endpoint": result.endpoint,
            "request_body": result.request_body,
            "result_count": result.result_count,
            "notes": result.notes,
            "items": [
                {
                    "kind": i.kind.value,
                    "subject_domain": i.subject_domain,
                    "payload": i.payload.model_dump(),
                    "source_url": i.source_url,
                    "source_record_id": i.source_record_id,
                    "valid_from": i.valid_from,
                    "valid_to": i.valid_to,
                    "field_coverage": i.field_coverage,
                    "raw_hash": i.raw_hash,
                    "dedup_key": i.dedup_key,
                    "independence_group": i.independence_group,
                }
                for i in result.items
            ],
        }

    @staticmethod
    def _result_from_cache(obj: Any) -> ProviderResult:
        data = obj if isinstance(obj, dict) else json.loads(obj)
        items = []
        for i in data["items"]:
            kind = EvidenceKind(i["kind"])
            items.append(
                NormalizedItem(
                    kind=kind,
                    subject_domain=i["subject_domain"],
                    payload=_PAYLOAD_TYPES[kind].model_validate(i["payload"]),
                    source_url=i["source_url"],
                    source_record_id=i["source_record_id"],
                    valid_from=i["valid_from"],
                    valid_to=i["valid_to"],
                    field_coverage=i["field_coverage"],
                    raw_hash=i["raw_hash"],
                    dedup_key=i["dedup_key"],
                    independence_group=i["independence_group"],
                )
            )
        return ProviderResult(
            provider=data["provider"],
            endpoint=data["endpoint"],
            request_body=data["request_body"],
            items=items,
            result_count=data["result_count"],
            credits_used=Decimal("0"),
            request_id=None,
            attempts=0,
            notes=[*data.get("notes", []), "cache"],
        )
