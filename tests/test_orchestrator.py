"""End-to-end agent loop tests on synthetic fixtures (no network, no credentials)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dealscope.agent.orchestrator import ConfigError, build_orchestrator
from dealscope.agent.tools import ToolExecutor
from dealscope.budget.governor import CreditGovernor
from dealscope.config import Settings
from dealscope.domain.enums import CaseStage, RunMode, ToolName, ToolRunStatus
from dealscope.domain.models import CaseInput, PlannerAction
from dealscope.persistence.repository import Repository
from dealscope.providers.base import ProviderResult
from dealscope.providers.llm import ScriptedProvider

FIX = Path(__file__).resolve().parents[1] / "fixtures"
AS_OF = date(2026, 10, 11)


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def case_input(scenario: str = "scenario_a.json", **kw) -> CaseInput:
    c = json.loads((FIX / scenario).read_text(encoding="utf-8"))["case"]
    return CaseInput(
        target_domain=c["target_domain"],
        competitor_domains=c["competitor_domains"],
        deal_thesis=c["deal_thesis"],
        mode=RunMode.SYNTHETIC,
        **kw,
    )


def make(tmp_path, scenario="scenario_a.json", llm=None, faults=None, db="t.sqlite3", **skw):
    repo = Repository(tmp_path / db)
    orch = build_orchestrator(
        settings(**skw),
        RunMode.SYNTHETIC,
        repo=repo,
        fixture_path=FIX / scenario,
        faults=faults,
        llm=llm,
        as_of=AS_OF,
        sleep=lambda s: None,
    )
    return orch, repo


def plans(repo, case_id):
    return [e["payload"] for e in repo.list_events(case_id) if e["type"] == "plan"]


def test_full_run_produces_verified_memo(tmp_path):
    orch, repo = make(tmp_path)
    state = orch.create_case(case_input())
    result = orch.run(state.case_id)
    assert result.stage in (CaseStage.COMPLETE, CaseStage.PARTIAL)
    final = repo.load_case(state.case_id)
    assert final.scorecard is not None and final.tool_call_count <= 12 and final.iteration_count <= 8
    report = repo.latest_report(state.case_id)
    assert "SYNTHETIC DEMO DATA" in report["markdown"]
    assert report["bundle"]["mode"] == "synthetic"
    for claim in report["bundle"]["report"]["claims"]:
        if claim["claim_type"] in ("observation", "interpretation"):
            assert claim["evidence_ids"]


def test_t02_adaptive_branch_differs_between_scenarios(tmp_path):
    orch_a, repo_a = make(tmp_path, "scenario_a.json", db="a.sqlite3")
    a = orch_a.create_case(case_input("scenario_a.json"))
    orch_a.run(a.case_id)
    orch_b, repo_b = make(tmp_path, "scenario_b.json", db="b.sqlite3")
    b = orch_b.create_case(case_input("scenario_b.json"))
    orch_b.run(b.case_id)
    first_a, first_b = plans(repo_a, a.case_id)[0], plans(repo_b, b.case_id)[0]
    assert (first_a["action"], first_a["arguments"]) != (first_b["action"], first_b["arguments"])
    assert first_a["action"] == "search_jobs" and "trails total headcount" in first_a["why"]
    assert first_b["action"] == "search_people" and "No engineering-vs-total divergence" in first_b["why"]
    # Scenario B's undated histories lead to a coverage-broadening follow-up that A never needs.
    b_actions = [
        (p["action"], p["arguments"].get("role_group"), p["arguments"].get("relationship"))
        for p in plans(repo_b, b.case_id)
    ]
    assert ("search_people", "senior_technical_ic", "past_target_employment") in b_actions


def test_llm_planner_choice_is_used_and_malformed_output_falls_back(tmp_path):
    good = {
        "candidate_index": 0,
        "question": "Q?",
        "why_this_action": "LLM reason",
        "expected_information_gain": "high",
    }
    llm = ScriptedProvider(
        [
            "not json at all",
            {"candidate_index": 99, "question": "", "why_this_action": "", "expected_information_gain": "high"},
            good,
        ]
        + [{"candidate_index": -1, "question": "", "why_this_action": "enough", "expected_information_gain": "low"}]
        * 10
        + ['{"claims": []}']
    )
    orch, repo = make(tmp_path, llm=llm)
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    p = plans(repo, state.case_id)
    assert p[0]["decided_by"] == "deterministic_fallback" and len(p[0]["rejected"]) == 2  # 2 bad outputs -> fallback
    assert p[1]["decided_by"] == "llm" and p[1]["why"] == "LLM reason"


def test_llm_cannot_invent_actions(tmp_path):
    bad = {"candidate_index": 0, "question": "x", "why_this_action": "x", "expected_information_gain": "high"}
    orch, _ = make(tmp_path, llm=ScriptedProvider([bad]))
    from dealscope.agent.planner import Planner

    with pytest.raises(ValidationError):
        PlannerAction(action="fetch_url", arguments={"url": "http://evil"})  # not in the allowlisted enum
    assert isinstance(orch.planner, Planner)


def test_t06_retry_then_success_persisted(tmp_path):
    orch, repo = make(tmp_path, faults={"enrich_company": [503, 503]})
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    retries = [e for e in repo.list_events(state.case_id) if e["type"] == "retry"]
    assert len(retries) == 2
    runs = repo.list_tool_runs(state.case_id)
    first = runs[0]
    assert first["status"] == ToolRunStatus.SUCCEEDED.value and first["attempt_count"] == 3


def test_t10_retry_exhausted_then_resume_without_repeating_calls(tmp_path):
    orch, repo = make(tmp_path, faults={"enrich_company": [503, 503, 503]})
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    after_first = repo.load_case(state.case_id)
    failed = [c for c in after_first.completed_actions if c.outcome.startswith("failed:")]
    assert failed, "first enrichment should fail after bounded retries"
    assert after_first.stage == CaseStage.PARTIAL and "failed_actions" in after_first.finish_reason
    succeeded_before = {r["idempotency_key"] for r in repo.list_tool_runs(state.case_id) if r["status"] == "succeeded"}
    evidence_before = {e.evidence_id for e in repo.get_evidence(state.case_id)}

    # Simulate a process restart: brand-new repository + orchestrator on the same DB file, no faults.
    repo.close()
    orch2, repo2 = make(tmp_path)
    result = orch2.run(state.case_id, resume=True)
    assert result.stage in (CaseStage.COMPLETE, CaseStage.PARTIAL)
    runs = repo2.list_tool_runs(state.case_id)
    keys = [r["idempotency_key"] for r in runs if r["status"] == "succeeded"]
    assert len(keys) == len(set(keys)), "a completed metered call was repeated"
    assert succeeded_before <= set(keys)
    assert evidence_before <= {e.evidence_id for e in repo2.get_evidence(state.case_id)}
    assert any(e["type"] == "resume" for e in repo2.list_events(state.case_id))


def test_t07_auth_failure_stops_without_fixture_fallback(tmp_path):
    orch, repo = make(tmp_path, faults={"enrich_company": [401]})
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    final = repo.load_case(state.case_id)
    assert final.finish_reason.startswith("fatal:")
    assert len(repo.list_tool_runs(state.case_id)) == 1
    assert final.stage == CaseStage.PARTIAL


def test_live_mode_requires_key_and_never_uses_fixtures(tmp_path):
    with pytest.raises(ConfigError):
        build_orchestrator(settings(), RunMode.LIVE, repo=Repository(tmp_path / "x.sqlite3"))


class _ExplodingSource:
    provider_name = "crustdata"

    def __getattr__(self, name):
        raise AssertionError("provider must not be called")


def test_t08_unknown_job_price_blocked_before_http(tmp_path):
    repo = Repository(tmp_path / "j.sqlite3")
    s = settings()  # CRUSTDATA_JOB_COST_PER_RESULT not configured
    gov = CreditGovernor(repo, s, pool="live")
    ex = ToolExecutor(repo, gov, _ExplodingSource(), api_version="2025-11-01", as_of=AS_OF)
    orch = build_orchestrator(s, RunMode.SYNTHETIC, repo=repo, fixture_path=FIX / "scenario_a.json", llm=None)
    state = orch.create_case(case_input())
    act = PlannerAction(
        action=ToolName.SEARCH_JOBS,
        arguments={"domain": state.input.target_domain, "role_terms": ["security"], "limit": 10},
    )
    outcome = ex.execute(state, act)
    assert outcome.status == ToolRunStatus.BLOCKED and outcome.reason == "UNKNOWN_PRICE_FAIL_CLOSED"
    assert outcome.disable_tool


def test_t09_budget_exhaustion_blocks_and_reports_partial(tmp_path):
    orch, repo = make(tmp_path)
    state = orch.create_case(case_input(max_case_credits=Decimal("5")))  # only 2 enrichments (2 credits each)
    orch.run(state.case_id)
    runs = repo.list_tool_runs(state.case_id)
    assert any(r["status"] == "blocked" and r["error_code"] == "PER_CASE_BUDGET_EXCEEDED" for r in runs)
    summary = CreditGovernor(repo, orch.settings, pool="synthetic").case_summary(state.case_id, Decimal("5"))
    assert summary["estimated_used"] <= Decimal("5")
    assert repo.latest_report(state.case_id) is not None


def test_synthetic_runs_do_not_touch_live_budget(tmp_path):
    orch, repo = make(tmp_path)
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    assert CreditGovernor(repo, orch.settings, pool="live").global_summary()["estimated_used"] == Decimal("0")


def test_completed_call_not_repeated_on_rerun(tmp_path):
    orch, repo = make(tmp_path)
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    n = len(repo.list_tool_runs(state.case_id))
    orch.run(state.case_id, resume=True)
    runs = repo.list_tool_runs(state.case_id)
    assert all(r["status"] != "succeeded" for r in runs[n:]), "resume must not re-execute completed calls"


def test_unsupported_llm_claims_are_rejected_from_memo(tmp_path):
    claims = {
        "claims": [
            {
                "text": "40% of the engineering team left in 2026.",
                "claim_type": "observation",
                "severity": "high",
                "evidence_ids": ["ev-fake-1"],
            },
            {
                "text": "The target leaked IP because an engineer joined a competitor.",
                "claim_type": "interpretation",
                "severity": "high",
                "evidence_ids": [],
            },
            {
                "text": "Investors should apply a 20% valuation haircut.",
                "claim_type": "interpretation",
                "severity": "high",
                "evidence_ids": [],
            },
        ]
    }
    stop = {"candidate_index": -1, "question": "", "why_this_action": "stop", "expected_information_gain": "low"}
    llm = ScriptedProvider([stop, json.dumps(claims)])
    orch, repo = make(tmp_path, llm=llm)
    state = orch.create_case(case_input())
    orch.run(state.case_id)
    report = repo.latest_report(state.case_id)
    md = report["markdown"]
    assert "leaked IP" not in md and "valuation haircut" not in md and "40% of the engineering" not in md
    assert report["bundle"]["verification"]["draft_metrics"]["rejected"] == 3


def test_provider_result_contract_shape():
    assert {"provider", "endpoint", "items", "credits_used", "attempts"} <= set(ProviderResult.__dataclass_fields__)
