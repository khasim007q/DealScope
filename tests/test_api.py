"""Web API tests on synthetic fixtures (no network, no real keys)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from dealscope.api import server
from dealscope.config import Settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, dealscope_db_path=tmp_path / "api.sqlite3", data_provider="crustdata")
    monkeypatch.setattr(server, "_settings", lambda: settings)
    monkeypatch.setattr("dealscope.agent.orchestrator.time.sleep", lambda s: None, raising=False)
    return TestClient(server.app)


def wait_done(client, case_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/cases/{case_id}").json()
        if not view["running"] and view["status_label"] != "Not started":
            return view
        time.sleep(0.1)
    raise AssertionError("case did not finish")


def test_status_without_keys(client):
    body = client.get("/api/status").json()
    assert body["live_available"] is False
    assert {p["key"] for p in body["providers"]} == {"crustdata", "llm", "jobs_pricing"}


def test_synthetic_case_produces_plain_language_view(client):
    scenarios = client.get("/api/scenarios").json()
    a = next(s for s in scenarios if s["id"] == "scenario_a")
    r = client.post(
        "/api/cases",
        json={
            "target_domain": a["target_domain"],
            "competitor_domains": a["competitor_domains"],
            "deal_thesis": a["deal_thesis"],
            "mode": "synthetic",
            "scenario_id": "scenario_a",
        },
    )
    assert r.status_code == 200
    view = wait_done(client, r.json()["case_id"])
    assert view["synthetic"] and view["status_label"] == "Complete"
    assert view["assessment"]["headline"] and view["assessment"]["explainer"]
    assert len(view["signals"]) == 5 and all(s["finding"] for s in view["signals"])
    assert not any("_" in s["finding"] for s in view["signals"]), "raw reason codes leaked into finding text"
    assert view["steps"] and any(s["actor"] in ("Rule-based planner", "AI planner") for s in view["steps"])
    assert view["companies"] and view["jobs"] and view["people"]
    assert view["verification"]["published"] > 0
    assert "plan_comparison" not in view
    assert client.get(f"/api/cases/{view['case_id']}/report.md").status_code == 200
    items = client.get("/api/cases").json()
    assert items[0]["case_id"] == view["case_id"]


def test_failure_then_resume_via_api(client):
    a = next(s for s in client.get("/api/scenarios").json() if s["id"] == "scenario_b")
    r = client.post(
        "/api/cases",
        json={
            "target_domain": a["target_domain"],
            "competitor_domains": a["competitor_domains"],
            "deal_thesis": a["deal_thesis"],
            "mode": "synthetic",
            "scenario_id": "scenario_b",
            "fault_id": "retry_exhausted",
        },
    )
    cid = r.json()["case_id"]
    view = wait_done(client, cid)
    assert view["can_resume"] and view["status_label"].startswith("Partial")
    assert any(s["kind"] == "retry" for s in view["steps"])
    assert client.post(f"/api/cases/{cid}/resume").status_code == 200
    time.sleep(0.2)
    view = wait_done(client, cid)
    assert view["status_label"] == "Complete"
    assert any(s["kind"] == "resume" for s in view["steps"])


def test_validation_errors_are_readable(client):
    r = client.post(
        "/api/cases",
        json={
            "target_domain": "localhost",
            "competitor_domains": ["a.example", "b.example"],
            "deal_thesis": "Expand the platform",
            "mode": "synthetic",
        },
    )
    assert r.status_code == 422 and "local" in r.json()["detail"]


def test_live_requires_key(client):
    r = client.post(
        "/api/cases",
        json={
            "target_domain": "acme.example",
            "competitor_domains": ["a.example", "b.example"],
            "deal_thesis": "Expand the platform",
            "mode": "live",
        },
    )
    assert r.status_code == 400
    assert client.post("/api/identity-check", json={"domains": ["acme.example"]}).status_code == 400


def test_unknown_api_paths_404(client):
    r = client.get("/api/evidence/..%2F..%2F.env")
    assert r.status_code == 404 and "CRUSTDATA" not in r.text
    assert client.get("/api/does-not-exist").status_code == 404


def test_cancel_requires_running_case(client):
    assert client.post("/api/cases/case-unknown/cancel").status_code == 409


def test_evidence_summary_reads_committed_evidence(client):
    body = client.get("/api/evidence-summary").json()
    assert set(body) == {"crustdata"} and body["crustdata"]["reserve"] >= 0


def test_featured_round_trip(tmp_path):
    from dealscope.persistence import featured
    from dealscope.persistence.repository import Repository

    src = Repository(tmp_path / "src.sqlite3")
    orch = build_orchestrator_for(src)
    a = orch.create_case(scenario_input())
    orch.run(a.case_id)
    doc = featured.export_case(src, a.case_id, "label", "desc")
    dst = Repository(tmp_path / "dst.sqlite3")
    assert featured.import_case(dst, doc) == a.case_id
    assert featured.import_case(dst, doc) is None  # idempotent
    assert dst.latest_report(a.case_id) is not None
    assert len(dst.get_evidence(a.case_id)) == len(src.get_evidence(a.case_id))
    assert [e["created_at"] for e in dst.list_events(a.case_id)] == [
        e["created_at"] for e in src.list_events(a.case_id)
    ]


def build_orchestrator_for(repo):
    from dealscope.agent.orchestrator import build_orchestrator
    from dealscope.domain.enums import RunMode

    return build_orchestrator(Settings(_env_file=None), RunMode.SYNTHETIC, repo=repo, llm=None, sleep=lambda s: None)


def scenario_input():
    import json
    from pathlib import Path

    from dealscope.domain.models import CaseInput

    c = json.loads((Path(server.FIXTURES) / "scenario_a.json").read_text(encoding="utf-8"))["case"]
    return CaseInput(
        target_domain=c["target_domain"], competitor_domains=c["competitor_domains"], deal_thesis=c["deal_thesis"]
    )


def test_local_trace_recording(tmp_path):
    """The spans of a run are recorded per case ."""
    from dealscope.observability import tracing
    from dealscope.persistence.repository import Repository

    db = tmp_path / "traced.sqlite3"
    tracing.shutdown()
    try:
        tracing.init_tracing(record_to=db)
        repo = Repository(db)
        orch = build_orchestrator_for(repo)
        state = orch.create_case(scenario_input())
        orch.run(state.case_id)
        traces = repo.list_traces(state.case_id)
    finally:
        tracing.shutdown()
    assert len(traces) == 1
    t = traces[0]
    names = [s["name"] for s in t["spans"]]
    assert names[0] == "investigation_workflow" and "verify_claims" in names and "render_memo" in names
    assert any(n.startswith("tool.") for n in names)
    root = t["spans"][0]
    assert root["parent_id"] is None and root["attributes"]["dealscope.case_id"] == state.case_id
    assert all(s["parent_id"] for s in t["spans"][1:])
    assert t["span_count"] == len(t["spans"]) and t["duration_ms"] >= 0


def test_recorder_drops_model_io_text():
    from dealscope.observability.recorder import _clean

    attrs = {
        "dealscope.model": "gemini-3.8-flash",
        "llm.input_messages.1.content": "SNAPSHOT: Head of Engineering ...",
        "gen_ai.completion": "{...}",
        "dealscope.prompt": "SNAPSHOT: ...",
        "dealscope.tool": "search_people",
        "input.value": "prompt text",
    }
    out = _clean(attrs, is_root=False)
    assert out == {"dealscope.model": "gemini-3.8-flash", "dealscope.tool": "search_people"}
    assert _clean({"input.value": "live case x"}, is_root=True) == {"input.value": "live case x"}


def test_llm_span_renders_as_gemini_call(tmp_path):
    import json

    from dealscope.observability import tracing
    from dealscope.persistence.repository import Repository

    db = tmp_path / "llm.sqlite3"
    tracing.shutdown()
    try:
        tracing.init_tracing(record_to=db)
        with tracing.span("investigation_workflow", kind="WORKFLOW", case_id="case-llm"):
            with tracing.span("generate_content", kind="LLM", model="gemini-3.8-flash") as sp:
                sp.set_attribute("total_tokens", 1234)
                sp.set_io("SECRET PROMPT TEXT", "SECRET RESPONSE")
        repo = Repository(db)
        traces = repo.list_traces("case-llm")
    finally:
        tracing.shutdown()
    assert len(traces) == 1
    llm = next(s for s in traces[0]["spans"] if s["kind"] == "LLM")
    assert llm["name"] == "Gemini call (gemini-3.8-flash)"
    assert llm["attributes"]["dealscope.total_tokens"] == 1234
    assert "SECRET" not in json.dumps(llm)


def test_init_tracing_without_store_is_noop():
    from dealscope.observability import tracing

    tracing.shutdown()
    try:
        assert tracing.init_tracing() is False and not tracing.tracing_enabled()
        with tracing.span("x") as sp:
            sp.set_attribute("a", 1)
    finally:
        tracing.shutdown()


def test_init_tracing_with_record_to_persists_case_trace(tmp_path):
    from dealscope.observability import tracing
    from dealscope.persistence.repository import Repository

    db = tmp_path / "t.sqlite3"
    tracing.shutdown()
    try:
        assert tracing.init_tracing(record_to=db) is True and tracing.tracing_enabled()
        with tracing.span("investigation_workflow", kind="WORKFLOW", case_id="case-x"):
            with tracing.span("tool.search", kind="TOOL"):
                pass
        tracing.flush()
        traces = Repository(db).list_traces("case-x")
    finally:
        tracing.shutdown()
    assert len(traces) == 1 and traces[0]["span_count"] == 2


def _scenario_a(client):
    return next(s for s in client.get("/api/scenarios").json() if s["id"] == "scenario_a")


def test_minimal_body_target_only_flow(client):
    a = _scenario_a(client)
    r = client.post("/api/cases", json={"target_domain": a["target_domain"], "mode": "synthetic"})
    assert r.status_code == 200, r.text
    view = wait_done(client, r.json()["case_id"])
    assert view["peers"] == [] and view["thesis_is_default"] is True
    assert view["thesis"] == "General diligence (no thesis given)"
    assert view["status_label"] in ("Complete", "Partial results")
    s5 = next(s for s in view["signals"] if s["id"] == "S5")
    assert not s5["scored"] and "No competitors given" in s5["finding"]
    ans = view["answer"]
    assert set(ans) == {"headline", "level", "tone", "score", "top_questions", "coverage_note", "next_step"}
    assert ans["headline"] and ans["coverage_note"].startswith("Based on ") and ans["next_step"]
    assert len(ans["top_questions"]) <= 3
    assert "No competitors given" in ans["coverage_note"]


def test_answer_block_for_complete_case(client):
    a = _scenario_a(client)
    r = client.post(
        "/api/cases",
        json={
            "target_domain": a["target_domain"],
            "competitor_domains": a["competitor_domains"],
            "deal_thesis": a["deal_thesis"],
            "mode": "synthetic",
        },
    )
    view = wait_done(client, r.json()["case_id"])
    ans = view["answer"]
    assert ans["level"] == view["assessment"]["risk_band"] and ans["score"] == view["assessment"]["risk_score"]
    assert ans["tone"] == view["assessment"]["risk_tone"]
    assert ans["top_questions"] and all(isinstance(q, str) for q in ans["top_questions"])
    assert view["thesis_is_default"] is False


def test_answer_block_null_safe_while_running():
    from dealscope.api.views import answer_view
    from dealscope.domain.models import CaseInput, CaseState

    inp = CaseInput(target_domain="acme.com")
    state = CaseState.model_construct(input=inp, scorecard=None, claims=[], open_questions=[])
    ans = answer_view(state, True)
    assert ans["headline"] == "Investigating..." and ans["score"] is None and ans["level"] == "Investigating"
    assert ans["top_questions"] == []


def _free_client(tmp_path, monkeypatch, **kw):
    settings = Settings(_env_file=None, dealscope_db_path=tmp_path / "f.sqlite3", data_provider="free", **kw)
    monkeypatch.setattr(server, "_settings", lambda: settings)
    return TestClient(server.app)


def test_free_status_is_live_available_without_keys(tmp_path, monkeypatch):
    body = _free_client(tmp_path, monkeypatch).get("/api/status").json()
    assert body["data_provider"] == "free" and body["live_available"] is True
    rows = {p["key"]: p for p in body["providers"]}
    assert rows["job_boards"]["connected"] and rows["job_boards"]["label"] == "Public job boards (free)"
    assert not rows["pdl"]["connected"] and "not set" in rows["pdl"]["detail"]
    assert rows["crustdata"]["optional"] and "jobs_pricing" not in rows


def test_free_status_with_pdl_key(tmp_path, monkeypatch):
    body = _free_client(tmp_path, monkeypatch, pdl_api_key="k").get("/api/status").json()
    assert {p["key"]: p for p in body["providers"]}["pdl"]["connected"] is True


def test_free_identity_check_unverified_without_pdl_key(tmp_path, monkeypatch):
    c = _free_client(tmp_path, monkeypatch)
    r = c.post("/api/identity-check", json={"domains": ["https://www.linear.app/", "height.app"]})
    assert r.status_code == 200
    out = r.json()
    assert [o["domain"] for o in out] == ["linear.app", "height.app"]
    assert all(
        o["ok"] is True
        and o["status"] == "unverified"
        and o["resolved_name"] is None
        and o["match_count"] == 0
        and o["candidates"] == []
        and o["message"] == "Not verified: no company-data key set. Public job boards only."
        for o in out
    )


def test_resume_refused_when_data_provider_changed(tmp_path, monkeypatch):
    from dealscope.agent.orchestrator import build_orchestrator
    from dealscope.domain.enums import RunMode
    from dealscope.domain.models import CaseInput
    from dealscope.persistence.repository import Repository

    c = _free_client(tmp_path, monkeypatch)
    free = server._settings()
    repo = Repository(free.dealscope_db_path)
    orch = build_orchestrator(free, RunMode.LIVE, repo=repo, llm=None)
    try:
        state = orch.create_case(CaseInput(target_domain="acme.com", mode=RunMode.LIVE, max_case_credits=10))
    finally:
        orch.close()
    created = next(e for e in repo.list_events(state.case_id) if e["type"] == "case_created")
    assert created["payload"]["provider"] == "free"
    repo.close()

    paid = free.model_copy(update={"data_provider": "crustdata"})
    monkeypatch.setattr(server, "_settings", lambda: paid)
    r = c.post(f"/api/cases/{state.case_id}/resume")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "free (public job boards)" in detail and "Crustdata" in detail and "start a new investigation" in detail
