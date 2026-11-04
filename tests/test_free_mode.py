"""LIVE mode with DATA_PROVIDER=free: wiring, zero-credit accounting and a full run on mocked HTTP."""

from __future__ import annotations

import httpx
import pytest

from dealscope.agent.orchestrator import build_orchestrator
from dealscope.budget.governor import JOB_SEARCH, CreditGovernor
from dealscope.config import Settings
from dealscope.domain.enums import CaseStage, RunMode
from dealscope.domain.models import CaseInput
from dealscope.persistence.repository import Repository
from dealscope.providers.free_source import FREE_PRICE_OVERRIDES, FreeDataSource


def _settings(tmp_path, **kw) -> Settings:
    return Settings(
        _env_file=None,
        data_provider="free",
        dealscope_db_path=tmp_path / "f.sqlite3",
        pdl_usage_path=tmp_path / "pdl.json",
        **kw,
    )


def _jobs(prefix: str, n: int) -> dict:
    titles = ["Staff Platform Engineer", "Security Engineer", "Site Reliability Engineer", "ML Engineer"]
    return {
        "jobs": [
            {
                "id": i,
                "title": titles[i % len(titles)],
                "first_published": "2026-09-01",
                "absolute_url": f"https://boards.greenhouse.io/{prefix}/jobs/{i}",
            }
            for i in range(n)
        ]
    }


def _ats(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    for slug, n in (("acme", 6), ("peerone", 3), ("peertwo", 2)):
        if f"greenhouse.io/v1/boards/{slug}/" in url:
            return httpx.Response(200, json=_jobs(slug, n))
    return httpx.Response(404, json={})


def test_build_orchestrator_free_needs_no_keys(tmp_path):
    s = _settings(tmp_path)
    assert s.crustdata_api_key is None and s.pdl_api_key is None
    orch = build_orchestrator(s, RunMode.LIVE, repo=Repository(s.dealscope_db_path), llm=None)
    try:
        assert isinstance(orch.executor.source, FreeDataSource)
        assert orch.governor.prices[JOB_SEARCH] == 0
    finally:
        orch.close()


def test_free_governor_adds_no_flat_job_reserve(tmp_path):
    s = _settings(tmp_path, crustdata_job_call_reserve="2")
    gov = CreditGovernor(Repository(s.dealscope_db_path), s, pool="live", price_overrides=FREE_PRICE_OVERRIDES)
    assert gov.estimate(JOB_SEARCH, 50) == 0


def test_crustdata_provider_still_requires_key(tmp_path):
    from dealscope.agent.orchestrator import ConfigError

    s = _settings(tmp_path).model_copy(update={"data_provider": "crustdata"})
    with pytest.raises(ConfigError):
        build_orchestrator(s, RunMode.LIVE, repo=Repository(s.dealscope_db_path), llm=None)


def test_full_live_run_on_mocked_job_boards_uses_zero_credits(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    real = FreeDataSource.from_settings
    monkeypatch.setattr(
        FreeDataSource,
        "from_settings",
        classmethod(lambda cls, settings, **kw: real(settings, ats_transport=httpx.MockTransport(_ats))),
    )
    repo = Repository(s.dealscope_db_path)
    orch = build_orchestrator(s, RunMode.LIVE, repo=repo, llm=None)
    try:
        state = orch.create_case(
            CaseInput(
                target_domain="acme.com",
                competitor_domains=["peerone.com", "peertwo.com"],
                deal_thesis="Platform investment thesis",
                max_case_credits=40,
                mode=RunMode.LIVE,
            )
        )
        result = orch.run(state.case_id)
    finally:
        orch.close()
    final = repo.load_case(state.case_id)
    assert result.stage in (CaseStage.COMPLETE, CaseStage.PARTIAL)
    assert final.credit_estimated_used == 0 and final.credit_actual_used == 0
    evidence = repo.get_evidence(state.case_id)
    jobs = [e for e in evidence if e.kind.value == "job_posting"]
    assert jobs and all(e.source_provider == "free" and not e.synthetic for e in jobs)
    report = repo.latest_report(state.case_id)
    assert report is not None
    assert any(e.source_endpoint.startswith("ats:greenhouse:acme") for e in jobs)
    assert "LIVE FREE SOURCES" in report["markdown"]
    assert "Credits consumed: 0 (free sources" in report["markdown"]
    assert "Crustdata" not in report["markdown"]


# ---------------------------------------------------------------------------
# No PDL key: unconfigured tools are skipped, not failed
# ---------------------------------------------------------------------------


def _run_free_without_pdl(tmp_path, monkeypatch, peers=("peerone.com",)):
    s = _settings(tmp_path)
    real = FreeDataSource.from_settings
    monkeypatch.setattr(
        FreeDataSource,
        "from_settings",
        classmethod(lambda cls, settings, **kw: real(settings, ats_transport=httpx.MockTransport(_ats))),
    )
    repo = Repository(s.dealscope_db_path)
    orch = build_orchestrator(s, RunMode.LIVE, repo=repo, llm=None)
    try:
        state = orch.create_case(
            CaseInput(target_domain="acme.com", competitor_domains=list(peers), max_case_credits=40, mode=RunMode.LIVE)
        )
        orch.run(state.case_id)
    finally:
        orch.close()
    return s, repo, repo.load_case(state.case_id)


def test_no_pdl_key_skips_people_tools_and_finishes_complete_limited_evidence(tmp_path, monkeypatch):
    from dealscope.api import views

    s, repo, final = _run_free_without_pdl(tmp_path, monkeypatch)
    # Thin evidence (no composite) and a skipped source that a key would unlock: resumable, labelled "limited evidence".
    assert final.stage == CaseStage.COMPLETE and final.finish_reason.endswith("limited_evidence"), final.finish_reason
    assert "_failed_actions" not in (final.finish_reason or "")
    tried = {c.action.action.value for c in final.completed_actions}
    assert tried == {"search_jobs"}  # never planned or attempted enrich_company / search_people
    assert not [c for c in final.completed_actions if c.outcome.startswith("failed")]
    events = repo.list_events(final.case_id)
    assert sum(1 for e in events if e["type"] == "tools_skipped") == 1
    steps = views.build_steps(final, events)
    skipped = [x for x in steps if x["title"].startswith("Company and people data skipped")]
    assert len(skipped) == 1 and "no People Data Labs key set" in skipped[0]["detail"].replace("No ", "no ", 1)
    text = " ".join(x["title"] + " " + x["detail"] for x in steps).lower()
    assert "not_configured" not in text and "failed because" not in text
    assert views.status_of(final, False)[0] == "Complete - limited evidence"


def test_resume_after_adding_pdl_key_reenables_people_tools(tmp_path, monkeypatch):
    _, repo, final = _run_free_without_pdl(tmp_path, monkeypatch)
    assert final.unavailable_tools.get("enrich_company") == "NOT_CONFIGURED"
    s2 = _settings(tmp_path, pdl_api_key="k-test")
    orch = build_orchestrator(s2, RunMode.LIVE, repo=repo, llm=None)
    try:
        orch._sync_unconfigured_tools(final)
    finally:
        orch.close()
    assert "enrich_company" not in final.unavailable_tools and "search_people" not in final.unavailable_tools


def test_plain_reason_never_shows_raw_codes():
    from dealscope.api import views

    for code in ("NOT_CONFIGURED", "PDL_MONTHLY_LIMIT", "HTTP_502", "http_503", "SOME_NEW_CODE", "ConnectError"):
        text = views.plain_reason(code)
        assert text and "_" not in text and not text.isupper()
    step_events = [
        {
            "type": "tool_result",
            "created_at": "t",
            "payload": {
                "tool": "enrich_company",
                "arguments": {"domain": "acme.com"},
                "outcome": "failed:NOT_CONFIGURED",
            },
        }
    ]
    state = CaseInput(target_domain="acme.com")
    fake = type("S", (), {"input": state, "mode": RunMode.LIVE})()
    step = views.build_steps(fake, step_events)[0]
    assert "not_configured" not in step["detail"].lower() and "People Data Labs" in step["detail"]


def test_answer_block_reports_what_was_found_and_what_to_do(tmp_path, monkeypatch):
    from dealscope.api import views

    s, repo, final = _run_free_without_pdl(tmp_path, monkeypatch)
    view = views.case_view(
        final,
        repo.get_evidence(final.case_id),
        repo.list_events(final.case_id),
        repo.latest_report(final.case_id),
        {"budget": 40, "estimated_used": 0, "actual_used": 0, "reserved": 0, "remaining": 40, "unknown_count": 0},
        False,
        s,
    )
    ans = view["answer"]
    assert ans["level"] == "Not enough evidence" and ans["score"] is None
    assert ans["headline"].startswith("Not enough evidence for a verdict: found ")
    assert "open technical role" in ans["headline"] and "but no headcount or people data" in ans["headline"]
    assert ans["next_step"] == (
        "Add a free People Data Labs key (PDL_API_KEY) to score headcount, departures and competitor moves."
    )
    note = ans["coverage_note"]
    assert note.startswith("Based on 1 of 5 checks: ") and "Not checked: " in note and "People Data Labs" in note
    # the mocked boards link only to boards.greenhouse.io, so ownership is unconfirmed and must be surfaced
    assert "name only" in note and "acme.com" in note
    assert all(j["board_match"] == "name_only" for j in view["jobs"])


# ---------------------------------------------------------------------------
# Governor prices follow the real source
# ---------------------------------------------------------------------------


class _FakeSource:
    def __init__(self, name):
        self.provider_name = name


def test_injected_paid_source_never_gets_zero_prices(tmp_path):
    from dealscope.agent.orchestrator import ConfigError

    s = _settings(tmp_path)  # DATA_PROVIDER=free
    with pytest.raises(ConfigError):
        build_orchestrator(
            s, RunMode.LIVE, repo=Repository(s.dealscope_db_path), llm=None, source=_FakeSource("crustdata")
        )
    paid = s.model_copy(update={"data_provider": "crustdata"})
    with pytest.raises(ConfigError):
        build_orchestrator(
            paid, RunMode.LIVE, repo=Repository(s.dealscope_db_path), llm=None, source=_FakeSource("free")
        )
    orch = build_orchestrator(
        paid, RunMode.LIVE, repo=Repository(s.dealscope_db_path), llm=None, source=_FakeSource("crustdata")
    )
    assert orch.governor.prices["company_enrich"] > 0
    ok = build_orchestrator(s, RunMode.LIVE, repo=Repository(s.dealscope_db_path), llm=None, source=_FakeSource("free"))
    assert ok.governor.prices[JOB_SEARCH] == 0
