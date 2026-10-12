"""Bounded investigate / recover / stop loop over persisted case state.

State is checkpointed in SQLite at every stage transition and after every tool result, so a crashed or
interrupted run resumes from the last checkpoint without replaying completed metered calls.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from dealscope.agent.planner import (
    Candidate,
    Planner,
    baseline_actions,
    candidate_actions,
    refresh_open_questions,
)
from dealscope.agent.synthesis import Variant, draft_claims
from dealscope.agent.tools import ToolExecutor, ToolOutcome, ToolRejected
from dealscope.analysis.signals import compute_scorecard
from dealscope.budget.governor import BudgetDenied, CreditGovernor
from dealscope.config import Settings
from dealscope.domain.enums import CaseStage, RunMode, ToolName, ToolRunStatus
from dealscope.domain.enums import VerificationStatus as VS
from dealscope.domain.models import CaseInput, CaseState, CompletedAction, PlannerAction, Scorecard
from dealscope.observability import tracing
from dealscope.persistence.repository import Repository
from dealscope.providers.base import DataSource
from dealscope.providers.llm import LLMError, LLMProvider
from dealscope.reports.memo import build_bundle, deterministic_claims, render_memo
from dealscope.verification.claims import verify_claims

log = logging.getLogger(__name__)

TERMINAL = {CaseStage.COMPLETE, CaseStage.FAILED}
# Documented list price (docs/10 §5). Used ONLY to simulate budget accounting for synthetic fixture runs;
# live runs take the job price exclusively from CRUSTDATA_JOB_COST_PER_RESULT (absent => fail closed).
SIMULATED_JOB_PRICE = Decimal("0.03")


class ConfigError(RuntimeError):
    pass


@dataclass
class RunResult:
    case_id: str
    stage: CaseStage
    finish_reason: str | None
    trace_id: str | None
    metrics: dict = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        governor: CreditGovernor,
        executor: ToolExecutor,
        planner: Planner,
        llm: LLMProvider | None,
        *,
        synthesis_variant: Variant = "improved",
        as_of: date | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.governor = governor
        self.executor = executor
        self.planner = planner
        self.llm = llm
        self.synthesis_variant = synthesis_variant
        self.as_of = as_of
        # Set by the API to stop at the next step boundary (never interrupts an in-flight provider request).
        self.cancel_event: threading.Event | None = None

    # ------------------------------------------------------------------
    def create_case(self, case_input: CaseInput, run_label: str | None = None) -> CaseState:
        cap = min(case_input.max_case_credits, self.settings.crustdata_max_case_credits)
        state = CaseState(
            input=case_input, mode=case_input.mode, credit_budget=cap, run_label=run_label or self.synthesis_variant
        )
        state.open_questions = refresh_open_questions(state, [], None)
        self.repo.create_case(state)
        self.repo.add_event(
            state.case_id,
            "case_created",
            {"mode": state.mode.value, "budget": str(cap), "target": case_input.target_domain},
        )
        return state

    def _limits_hit(self, state: CaseState, started: float) -> str | None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return "cancelled_by_user"
        if state.tool_call_count >= self.settings.dealscope_max_tool_calls:
            return "max_tool_calls"
        if state.runtime_seconds_used + (time.monotonic() - started) >= self.settings.dealscope_max_runtime_seconds:
            return "max_runtime"
        return None

    def _transition(self, state: CaseState, stage: CaseStage, span=None) -> None:
        prev = state.stage
        state.stage = stage
        state.updated_at = datetime.now(UTC)
        self.repo.checkpoint(state, f"stage:{stage.value}")
        self.repo.add_event(state.case_id, "stage", {"from": prev.value, "to": stage.value})
        if span is not None:
            span.add_event("state_transition", {"from": prev.value, "to": stage.value})

    def _rescore(self, state: CaseState, span=None) -> Scorecard:
        evidence = self.repo.get_evidence(state.case_id)
        with tracing.span("score_signals", kind="CHAIN", case_id=state.case_id, evidence_count=len(evidence)) as s:
            new = compute_scorecard(state.input, evidence, as_of=self.as_of)
            old = {x.signal_id: (x.state, x.score) for x in state.scorecard.signals} if state.scorecard else {}
            changes = []
            for sig in new.signals:
                before = old.get(sig.signal_id)
                after = (sig.state, sig.score)
                if before != after:
                    changes.append(
                        {
                            "signal": sig.signal_id.value,
                            "from": f"{before[0].value}:{before[1]}" if before else "none",
                            "to": f"{sig.state.value}:{sig.score}",
                        }
                    )
            s.set_attribute("coverage_pct", new.coverage_pct)
            s.set_attribute("risk_score", new.risk_score if new.risk_score is not None else -1)
            s.set_attribute("evidence_confidence", new.evidence_confidence)
            s.set_attribute("score_version", new.signal_version)
            for c in changes:
                s.add_event("score_change", c)
            if changes:
                self.repo.add_event(
                    state.case_id, "score_change", {"changes": changes, "coverage_pct": new.coverage_pct}
                )
        state.scorecard = new
        state.open_questions = refresh_open_questions(state, evidence, new)
        return new

    def _record(self, state: CaseState, action: PlannerAction, outcome: ToolOutcome, iteration: int) -> None:
        state.completed_actions.append(
            CompletedAction(
                iteration=iteration,
                action=action,
                tool_run_id=outcome.tool_run_id,
                outcome=outcome.label,
                new_evidence_ids=outcome.new_evidence_ids,
            )
        )
        # Count only attempts that actually reached the provider.
        if outcome.status in (ToolRunStatus.SUCCEEDED, ToolRunStatus.FAILED, ToolRunStatus.UNKNOWN_OUTCOME):
            state.tool_call_count += 1
        if outcome.disable_tool:
            state.unavailable_tools[action.action.value] = outcome.reason or "disabled"
        if outcome.status == ToolRunStatus.UNKNOWN_OUTCOME:
            state.credit_unknown_calls += 1
        summary = self.governor.case_summary(state.case_id, state.credit_budget)
        state.credit_reserved = summary["reserved"]
        state.credit_estimated_used = summary["estimated_used"]
        state.credit_actual_used = summary["actual_used"]
        self.repo.add_event(
            state.case_id,
            "tool_result",
            {
                "tool": action.action.value,
                "arguments": action.arguments,
                "outcome": outcome.label,
                "new_evidence": len(outcome.new_evidence_ids),
                "attempts": outcome.attempts,
                "estimate": str(outcome.credits_estimate) if outcome.credits_estimate is not None else None,
                "actual": str(outcome.credits_actual) if outcome.credits_actual is not None else None,
                "decided_by": action.decided_by,
                "why": action.why_this_action,
            },
        )
        self.repo.checkpoint(state, f"after:{action.action.value}")

    def _execute(self, state: CaseState, action: PlannerAction, iteration: int) -> ToolOutcome:
        try:
            outcome = self.executor.execute(state, action)
        except ToolRejected as exc:
            outcome = ToolOutcome(ToolRunStatus.BLOCKED, reason=f"REJECTED_ACTION: {str(exc)[:120]}")
        self._record(state, action, outcome, iteration)
        return outcome

    def _candidates(self, state: CaseState, scorecard: Scorecard | None) -> list[Candidate]:
        evidence = self.repo.get_evidence(state.case_id)
        jobs_enabled = True
        try:
            self.governor.estimate("job_search", 1)
        except BudgetDenied as exc:
            jobs_enabled = False
            state.unavailable_tools.setdefault(ToolName.SEARCH_JOBS.value, exc.reason)

        def est(act: PlannerAction) -> Decimal:
            return self.executor.estimate(act)

        cands = candidate_actions(state, evidence, scorecard, est, jobs_enabled)
        remaining = self.governor.case_summary(state.case_id, state.credit_budget)["remaining"]
        affordable = [c for c in cands if c.estimated_credits <= remaining]
        if len(affordable) < len(cands):
            self.repo.add_event(
                state.case_id,
                "budget_filter",
                {"dropped": [c.key for c in cands if c not in affordable], "remaining": str(remaining)},
            )
        return affordable

    # ------------------------------------------------------------------
    def run(self, case_id: str, resume: bool = False) -> RunResult:
        state = self.repo.load_case(case_id)
        if state is None:
            raise KeyError(case_id)
        if state.stage in TERMINAL and not resume:
            return RunResult(case_id, state.stage, state.finish_reason, None)
        started = time.monotonic()
        trace_id = None
        with tracing.span(
            "investigation_workflow",
            kind="WORKFLOW",
            case_id=state.case_id,
            mode=state.mode.value,
            run_label=state.run_label,
            target=state.input.target_domain,
            resume=resume,
        ) as root:
            trace_id = root.trace_id()
            root.set_io(
                input_text=f"{state.mode.value} case {state.case_id}: target {state.input.target_domain}; "
                f"peers {', '.join(state.input.competitor_domains)}; resume={resume}"
            )
            if trace_id:
                self.repo.add_event(state.case_id, "trace", {"trace_id": trace_id})
            if resume:
                self._prepare_resume(state)
            try:
                self._run_inner(state, started, root)
            except Exception as exc:  # persist failure state, then re-raise for visibility
                root.record_exception(exc)
                state.finish_reason = f"error:{type(exc).__name__}"
                state.runtime_seconds_used += time.monotonic() - started
                self._transition(state, CaseStage.FAILED, root)
                raise
            root.set_attribute("finish_reason", state.finish_reason)
            sc = state.scorecard
            risk = "insufficient evidence" if sc is None or sc.risk_score is None else f"{sc.risk_score:.0f}"
            accepted = sum(1 for c in state.claims if c.verification_status in (VS.VERIFIED, VS.QUALIFIED))
            coverage = sc.coverage_pct if sc else 0
            root.set_io(
                output_text=f"{state.stage.value} ({state.finish_reason}); risk {risk}; coverage {coverage:.0f}%; "
                f"tool calls {state.tool_call_count}; verified claims {accepted}"
            )
            root.set_attribute("final_stage", state.stage.value)
            root.set_attribute("tool_calls", state.tool_call_count)
            root.set_attribute("iterations", state.iteration_count)
        tracing.flush()
        report = self.repo.latest_report(state.case_id)
        metrics = (report or {}).get("bundle", {}).get("verification", {}).get("metrics", {}) if report else {}
        return RunResult(case_id, state.stage, state.finish_reason, trace_id, metrics)

    def _prepare_resume(self, state: CaseState) -> None:
        with tracing.span("recover_run", kind="CHAIN", case_id=state.case_id, from_stage=state.stage.value) as s:
            failed = [c for c in state.completed_actions if c.outcome.startswith("failed:")]
            # Failed (non-fatal, retryable) attempts get exactly one more try after an explicit resume.
            state.completed_actions = [c for c in state.completed_actions if not c.outcome.startswith("failed:")]
            for c in failed:
                reason = c.outcome.split(":", 1)[1]
                if state.unavailable_tools.get(c.action.action.value) == reason and reason in {"RETRY_EXHAUSTED"}:
                    state.unavailable_tools.pop(c.action.action.value, None)
            unresolved = self.repo.find_unresolved_tool_runs(state.case_id)
            s.set_attribute("failed_actions_retried", len(failed))
            s.set_attribute("unresolved_runs", len(unresolved))
            s.set_attribute("evidence_restored", len(state.evidence_ids))
            self.repo.add_event(
                state.case_id,
                "resume",
                {
                    "from_stage": state.stage.value,
                    "retrying": len(failed),
                    "unknown_outcome_runs": len(unresolved),
                    "evidence_restored": len(state.evidence_ids),
                },
            )
            if state.stage in TERMINAL or state.stage == CaseStage.PARTIAL:
                state.stage = CaseStage.INVESTIGATING
            state.finish_reason = None

    def _run_inner(self, state: CaseState, started: float, root) -> None:
        # Pending baseline work also runs after a resume (e.g. an enrichment that failed before the restart).
        pending_baseline = baseline_actions(state, self.repo.get_evidence(state.case_id))
        if state.stage in (CaseStage.CREATED, CaseStage.BASELINE) or (
            state.stage == CaseStage.INVESTIGATING and pending_baseline and state.finish_reason is None
        ):
            self._transition(state, CaseStage.BASELINE, root)
            for action in pending_baseline:
                if (hit := self._limits_hit(state, started)) is not None:
                    state.finish_reason = hit
                    break
                outcome = self._execute(state, action, 0)
                if outcome.fatal:
                    state.finish_reason = f"fatal:{outcome.reason}"
                    break
            self._rescore(state, root)
            if state.finish_reason is None:
                self._transition(state, CaseStage.INVESTIGATING, root)

        if state.stage == CaseStage.INVESTIGATING and state.finish_reason is None:
            self._investigate(state, started, root)

        if state.stage in (CaseStage.INVESTIGATING, CaseStage.BASELINE, CaseStage.VERIFYING, CaseStage.REPORTING):
            self._finalize(state, started, root)

    def _investigate(self, state: CaseState, started: float, root) -> None:
        scorecard = state.scorecard or self._rescore(state, root)
        while True:
            if state.iteration_count >= self.settings.dealscope_max_iterations:
                state.finish_reason = "max_iterations"
                break
            if (hit := self._limits_hit(state, started)) is not None:
                state.finish_reason = hit
                break
            candidates = self._candidates(state, scorecard)
            remaining = {
                "planner_turns": self.settings.dealscope_max_iterations - state.iteration_count,
                "tool_calls": self.settings.dealscope_max_tool_calls - state.tool_call_count,
                "credits": str(self.governor.case_summary(state.case_id, state.credit_budget)["remaining"]),
            }
            state.iteration_count += 1
            with tracing.span(
                "plan_next_action",
                kind="AGENT",
                case_id=state.case_id,
                iteration=state.iteration_count,
                candidates=len(candidates),
            ) as ps:
                plan = self.planner.choose(
                    state, self.repo.get_evidence(state.case_id), scorecard, candidates, remaining
                )
                ps.set_attribute("action", plan.action.action.value)
                ps.set_attribute("decided_by", plan.action.decided_by)
                ps.set_attribute("llm_attempts", plan.llm_attempts)
                ps.set_attribute("why", plan.action.why_this_action)
                for r in plan.rejected_reasons:
                    ps.add_event("planner_output_rejected", {"reason": r})
            state.current_question = plan.action.question or None
            self.repo.add_event(
                state.case_id,
                "plan",
                {
                    "iteration": state.iteration_count,
                    "action": plan.action.action.value,
                    "arguments": plan.action.arguments,
                    "question": plan.action.question,
                    "why": plan.action.why_this_action,
                    "gain": plan.action.expected_information_gain,
                    "decided_by": plan.action.decided_by,
                    "rejected": plan.rejected_reasons,
                    "candidates": [c.key for c in candidates],
                },
            )
            if plan.action.action == ToolName.STOP:
                state.finish_reason = "planner_stop" if candidates else "no_candidates"
                self.repo.checkpoint(state, "planner_stop")
                break
            outcome = self._execute(state, plan.action, state.iteration_count)
            if outcome.fatal:
                state.finish_reason = f"fatal:{outcome.reason}"
                break
            scorecard = self._rescore(state, root)
            self.repo.checkpoint(state, f"iteration:{state.iteration_count}")

    def _finalize(self, state: CaseState, started: float, root) -> None:
        self._transition(state, CaseStage.VERIFYING, root)
        evidence = self.repo.get_evidence(state.case_id)
        scorecard = self._rescore(state, root)
        narrative = False
        draft_metrics: dict = {}
        claims = []
        if self.llm is not None and evidence:
            try:
                with tracing.span(
                    "synthesize_findings", kind="CHAIN", case_id=state.case_id, variant=self.synthesis_variant
                ):
                    claims = draft_claims(
                        self.llm,
                        state,
                        evidence,
                        scorecard,
                        self.synthesis_variant,
                        escalate=bool(self.settings.llm_escalation_model),
                    )
                narrative = True
            except LLMError as exc:
                self.repo.add_event(state.case_id, "llm_unavailable", {"error": str(exc)[:200]})
        det = deterministic_claims(scorecard, evidence, state.input)
        with tracing.span("verify_claims", kind="GUARDRAIL", case_id=state.case_id) as vs:
            draft_verification = verify_claims(claims, evidence, state.input, scorecard) if claims else None
            if draft_verification is not None:
                draft_metrics = dict(draft_verification.metrics)
            all_claims = claims + det if self.synthesis_variant == "improved" else (claims or det)
            verification = verify_claims(all_claims, evidence, state.input, scorecard)
            for k, v in verification.metrics.items():
                if isinstance(v, int | float):
                    vs.set_attribute(f"verify.{k}", v)
            for k, v in draft_metrics.items():
                if isinstance(v, int | float):
                    vs.set_attribute(f"draft.{k}", v)
        state.claims = verification.accepted + verification.rejected
        self._transition(state, CaseStage.REPORTING, root)
        limited = state.finish_reason not in (None, "planner_stop", "no_candidates")
        failed = [c for c in state.completed_actions if c.outcome.startswith(("failed:", "unknown_outcome:"))]
        if state.finish_reason is None:
            state.finish_reason = "complete"
        if failed and not limited:
            # Evidence gaps from failed tool calls: report is partial and the case can be resumed.
            limited = True
            state.finish_reason = f"{state.finish_reason}_with_{len(failed)}_failed_actions"
        as_of = datetime.combine(self.as_of, datetime.min.time(), tzinfo=UTC) if self.as_of else datetime.now(UTC)
        with tracing.span("render_memo", kind="CHAIN", case_id=state.case_id):
            memo = render_memo(state, evidence, verification, scorecard, narrative, as_of)
            bundle = build_bundle(state, evidence, verification, scorecard, narrative, as_of)
        bundle.setdefault("verification", {})["draft_metrics"] = draft_metrics
        bundle["run"] = {
            "variant": self.synthesis_variant,
            "tool_calls": state.tool_call_count,
            "iterations": state.iteration_count,
            "finish_reason": state.finish_reason,
            "runtime_seconds": round(state.runtime_seconds_used + time.monotonic() - started, 2),
            "llm_model": getattr(self.llm, "last_model", None) or getattr(self.llm, "model", None),
            "llm_tokens": getattr(self.llm, "tokens_used", None),
            "llm_calls": getattr(self.llm, "calls_made", None),
            "narrative_available": narrative,
        }
        self.repo.save_report(state.case_id, memo, bundle, verification.accepted)
        state.runtime_seconds_used += time.monotonic() - started
        self._transition(state, CaseStage.PARTIAL if limited else CaseStage.COMPLETE, root)


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


def build_orchestrator(
    settings: Settings,
    mode: RunMode,
    *,
    repo: Repository | None = None,
    fixture_path: Path | None = None,
    faults: dict | None = None,
    llm: LLMProvider | None | str = "auto",
    source: DataSource | None = None,
    synthesis_variant: Variant = "improved",
    as_of: date | None = None,
    sleep=time.sleep,
) -> Orchestrator:
    """Wire components. Live mode fails closed without a Crustdata key; it never falls back to fixtures."""
    from dealscope.providers.llm import build_provider

    repo = repo or Repository(settings.dealscope_db_path)
    if mode == RunMode.LIVE:
        if settings.crustdata_api_key is None and source is None:
            raise ConfigError(
                "LIVE mode requires CRUSTDATA_API_KEY; switch to synthetic mode explicitly to use fixtures."
            )
        governor = CreditGovernor(repo, settings, pool="live")
    else:
        governor = CreditGovernor(repo, settings, pool="synthetic", price_overrides={"job_search": SIMULATED_JOB_PRICE})
    executor = ToolExecutor(
        repo,
        governor,
        source=None,  # type: ignore[arg-type]
        api_version=settings.crustdata_api_version,
        max_people_results=settings.crustdata_max_people_search_results,
        as_of=as_of,
    )
    if source is None:
        if mode == RunMode.LIVE:
            from dealscope.providers.crustdata import CrustdataClient

            source = CrustdataClient(
                settings.crustdata_api_key.get_secret_value(),  # type: ignore[union-attr]
                api_version=settings.crustdata_api_version,
                base_url=settings.crustdata_base_url,
                timeout_s=settings.dealscope_http_timeout_seconds,
                max_retries=settings.dealscope_max_retries,
                on_retry=executor.on_retry,
                sleep=sleep,
            )
        else:
            from dealscope.providers.fixture import FixtureDataSource

            path = fixture_path or Path(__file__).resolve().parents[3] / "fixtures" / "scenario_a.json"
            source = FixtureDataSource(
                path, faults=faults, sleep=sleep, max_retries=settings.dealscope_max_retries, on_retry=executor.on_retry
            )
    executor.source = source
    if llm == "auto":
        llm = build_provider(settings)
    return Orchestrator(
        settings,
        repo,
        governor,
        executor,
        Planner(llm),
        llm,  # type: ignore[arg-type]
        synthesis_variant=synthesis_variant,
        as_of=as_of,
    )
