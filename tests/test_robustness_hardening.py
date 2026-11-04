"""Regression tests for the robustness / safety audit (run lifecycle, ledger, cache, LLM output, API access)."""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from dealscope.agent.orchestrator import build_orchestrator
from dealscope.agent.synthesis import MAX_DRAFT_CLAIMS, draft_claims
from dealscope.agent.tools import ToolExecutor
from dealscope.api import server
from dealscope.budget.governor import CreditGovernor
from dealscope.config import Settings
from dealscope.domain.enums import CaseStage, RunMode, ToolName, ToolRunStatus
from dealscope.domain.models import CaseInput, CaseState, PlannerAction
from dealscope.persistence.repository import Repository
from dealscope.providers.ats_jobs import AtsJobSource
from dealscope.providers.free_source import FREE_PRICE_OVERRIDES, FreeDataSource
from dealscope.providers.llm import LLMUnavailable, ScriptedProvider

ROOT = Path(__file__).resolve().parents[1]


def mk(tmp_path, **kw) -> Settings:
    kw.setdefault("dealscope_db_path", tmp_path / "p.sqlite3")
    kw.setdefault("pdl_usage_path", tmp_path / "pdl.json")
    return Settings(_env_file=None, **kw)


def api(tmp_path, monkeypatch, *, client=("127.0.0.1", 50000), host="localhost", **kw):
    s = mk(tmp_path, **kw)
    monkeypatch.setattr(server, "_settings", lambda: s)
    return TestClient(server.app, base_url=f"http://{host}", client=client, raise_server_exceptions=False), s


def seed_case(s: Settings, stage=CaseStage.CREATED, mode=RunMode.LIVE) -> str:
    repo = Repository(s.dealscope_db_path)
    st = CaseState(
        input=CaseInput(target_domain="acme.com", mode=mode), mode=mode, credit_budget=Decimal(40), stage=stage
    )
    repo.create_case(st)
    repo.close()
    return st.case_id


def _crust_state():
    return CaseState(
        input=CaseInput(target_domain="acme.com", mode=RunMode.LIVE), mode=RunMode.LIVE, credit_budget=Decimal(40)
    )


# ---------------------------------------------------------------- H1: one worker per case


def test_concurrent_resume_starts_one_run_and_rejects_the_other_with_409(tmp_path, monkeypatch):
    _, s = api(tmp_path, monkeypatch)
    cid = seed_case(s)
    lock, release = threading.Lock(), threading.Event()
    stats = {"active": 0, "peak": 0}

    class FakeOrch:
        cancel_event = None

        def run(self, case_id, resume=False):
            with lock:
                stats["active"] += 1
                stats["peak"] = max(stats["peak"], stats["active"])
            release.wait(5)
            with lock:
                stats["active"] -= 1

        def close(self):
            pass

    monkeypatch.setattr(server, "build_orchestrator", lambda *a, **k: FakeOrch())
    barrier = threading.Barrier(2)
    orig_running = server._running

    def gated_running(case_id):  # both requests see "not running" before either starts
        v = orig_running(case_id)
        try:
            barrier.wait(3)
        except threading.BrokenBarrierError:
            pass
        return v

    monkeypatch.setattr(server, "_running", gated_running)
    out: list = []

    def call():
        try:
            out.append(server.resume_case(cid))
        except HTTPException as exc:
            out.append(exc)

    ts = [threading.Thread(target=call) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(5) for t in ts]
    time.sleep(0.2)
    release.set()
    assert sorted(type(o).__name__ for o in out) == ["HTTPException", "dict"]
    assert next(o for o in out if isinstance(o, HTTPException)).status_code == 409
    assert stats["peak"] == 1


def test_db_lease_blocks_a_second_process_and_expires_when_stale(tmp_path):
    repo_a, repo_b = Repository(tmp_path / "l.sqlite3"), Repository(tmp_path / "l.sqlite3")
    assert repo_a.acquire_lease("c1", "proc-a", ttl_s=60, now=1000.0)
    assert not repo_b.acquire_lease("c1", "proc-b", ttl_s=60, now=1010.0)  # fresh lease held elsewhere
    repo_a.heartbeat_lease("c1", "proc-a", now=1040.0)
    assert not repo_b.acquire_lease("c1", "proc-b", ttl_s=60, now=1090.0)  # heartbeat kept it alive
    assert repo_b.acquire_lease("c1", "proc-b", ttl_s=60, now=1200.0)  # owner died: stale lease taken over
    repo_a.release_lease("c1", "proc-a")  # a late release by the old owner must not drop the new owner's lease
    assert not repo_a.acquire_lease("c1", "proc-a", ttl_s=60, now=1201.0)


def test_start_thread_returns_409_when_another_process_holds_the_lease(tmp_path, monkeypatch):
    _, s = api(tmp_path, monkeypatch)
    cid = seed_case(s)
    other = Repository(s.dealscope_db_path)
    assert other.acquire_lease(cid, "other-process", ttl_s=3600)
    with pytest.raises(HTTPException) as ei:
        server._start_thread(cid, RunMode.LIVE, None, None, resume=False)
    assert ei.value.status_code == 409


# ---------------------------------------------------------------- H2: worker failures are visible


def test_orchestrator_build_failure_marks_case_failed_with_plain_error_event(tmp_path, monkeypatch):
    client, s = api(tmp_path, monkeypatch, llm_provider="openai", llm_api_key="sk-x")
    r = client.post("/api/cases", json={"target_domain": "acme.com", "mode": "synthetic", "scenario_id": "scenario_a"})
    assert r.status_code == 200
    cid = r.json()["case_id"]
    for _ in range(100):
        if not server._running(cid):
            break
        time.sleep(0.05)
    repo = Repository(s.dealscope_db_path)
    state, events = repo.load_case(cid), repo.list_events(cid)
    repo.close()
    assert state.stage == CaseStage.FAILED and state.finish_reason.startswith("error:")
    err = [e for e in events if e["type"] == "error"]
    assert err and "LLM_PROVIDER" in err[0]["payload"]["message"]
    view = client.get(f"/api/cases/{cid}").json()
    assert view["status_label"] == "Failed" and view["running"] is False


def test_status_surfaces_invalid_llm_configuration(tmp_path, monkeypatch):
    client, _ = api(tmp_path, monkeypatch, llm_provider="openai", llm_api_key="sk-x")
    body = client.get("/api/status").json()
    assert "LLM_PROVIDER" in body["llm_config_error"]
    llm = next(p for p in body["providers"] if p["key"] == "llm")
    assert llm["connected"] is False and "LLM_PROVIDER" in llm["detail"]
    ok, _ = api(tmp_path, monkeypatch, llm_api_key="k")
    assert ok.get("/api/status").json()["llm_config_error"] is None


# ---------------------------------------------------------------- H3: no leaked reservations


def test_unexpected_provider_exception_closes_reservation_and_tool_run(tmp_path):
    s = mk(tmp_path)
    repo = Repository(s.dealscope_db_path)
    gov = CreditGovernor(repo, s, pool="live")

    class Boom:
        provider_name = "crustdata"

        def enrich_company(self, domain):
            raise KeyError("normaliser blew up")

    ex = ToolExecutor(repo, gov, Boom(), api_version="v", as_of=date(2026, 11, 4))
    st = _crust_state()
    repo.create_case(st)
    act = PlannerAction(action=ToolName.ENRICH_COMPANY, arguments={"domain": "acme.com"})
    out = ex.execute(st, act)
    assert out.status == ToolRunStatus.FAILED and out.reason == "UNEXPECTED_ERROR" and out.disable_tool
    assert repo.ledger_totals(st.case_id)["reserved"] == Decimal("0")  # nothing left `reserved`
    assert gov.global_summary()["reserved"] == Decimal("0")
    assert [r["status"] for r in repo.list_tool_runs(st.case_id)] == ["failed"]
    # the request may have been sent, so the estimate stays charged
    assert {r["status"] for r in repo.ledger_rows(st.case_id)} == {"unknown"}


def test_storage_failure_after_a_response_does_not_leave_started_rows(tmp_path, monkeypatch):
    repo, ex = _free_executor(tmp_path, _gh_handler)
    st = _crust_state()
    repo.create_case(st)

    def explode(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repo, "add_evidence_detailed", explode)
    out = ex.execute(st, JOB_ACTION)
    assert out.status == ToolRunStatus.FAILED and out.reason == "PERSIST_ERROR"
    assert [r["status"] for r in repo.list_tool_runs(st.case_id)] == ["failed"]
    assert repo.ledger_totals(st.case_id)["reserved"] == Decimal("0")


# ---------------------------------------------------------------- H4: bad cache rows


GH = {
    "jobs": [{"id": 1, "title": "Platform Engineer", "first_published": "2026-09-01", "absolute_url": "https://acme.com/1"}]
}
JOB_ACTION = PlannerAction(
    action=ToolName.SEARCH_JOBS,
    arguments={"domain": "acme.com", "role_terms": ["platform"], "lookback_days": 90, "limit": 25},
)


def _gh_handler(req):
    return httpx.Response(200, json=GH) if "boards/acme/jobs" in str(req.url) else httpx.Response(404, json={})


def _free_executor(tmp_path, handler):
    s = mk(tmp_path)
    repo = Repository(s.dealscope_db_path)
    gov = CreditGovernor(repo, s, pool="live", price_overrides=FREE_PRICE_OVERRIDES)
    ats = AtsJobSource(transport=httpx.MockTransport(handler), sleep=lambda x: None)
    return repo, ToolExecutor(repo, gov, FreeDataSource(None, ats), api_version="v", as_of=date(2026, 11, 4))


@pytest.mark.parametrize("damage", ["field", "garbage", "old_schema"])
def test_bad_cache_row_is_discarded_and_the_call_goes_live(tmp_path, damage):
    repo, ex = _free_executor(tmp_path, _gh_handler)
    a, b = _crust_state(), _crust_state()
    repo.create_case(a)
    repo.create_case(b)
    assert ex.execute(a, JOB_ACTION).status == ToolRunStatus.SUCCEEDED
    with repo.transaction() as conn:
        if damage == "field":
            conn.execute("UPDATE response_cache SET response_json = replace(response_json, 'independence_group', 'ig')")
        elif damage == "garbage":
            conn.execute("UPDATE response_cache SET response_json = '{not json'")
        else:
            conn.execute(
                "UPDATE response_cache SET response_json = replace(response_json, '\"schema\": 2', '\"schema\": 1')"
            )
    out = ex.execute(b, JOB_ACTION)
    assert out.status == ToolRunStatus.SUCCEEDED  # live call, not a crash
    assert len(repo.get_evidence(b.case_id)) == 1
    assert {r["status"] for r in repo.list_tool_runs(b.case_id)} == {"succeeded"}
    c = _crust_state()
    repo.create_case(c)
    assert ex.execute(c, JOB_ACTION).status == ToolRunStatus.CACHED  # the rewritten row is good again


# ---------------------------------------------------------------- H5: LLM output never fails a run


def _bare_state():
    return CaseState(
        input=CaseInput(target_domain="acme.com", mode=RunMode.LIVE), mode=RunMode.LIVE, credit_budget=Decimal(10)
    )


def test_invalid_claims_are_skipped_individually():
    good = {"text": "Ask management about engineering attrition.", "claim_type": "question"}
    raw = {
        "claims": [
            {"text": "ab", "claim_type": "question"},  # too short
            {"text": "Unknown type of claim", "claim_type": "rumour"},  # invalid enum
            "not an object",
            good,
        ]
    }
    claims = draft_claims(ScriptedProvider([raw]), _bare_state(), [], None)
    assert [c.text for c in claims] == [good["text"]]


def test_more_than_20_claims_are_truncated_not_discarded():
    claims = [{"text": f"question number {i}", "claim_type": "question"} for i in range(MAX_DRAFT_CLAIMS + 5)]
    out = draft_claims(ScriptedProvider([{"claims": claims}]), _bare_state(), [], None)
    assert len(out) == MAX_DRAFT_CLAIMS and out[0].text == "question number 0"


class _BadLLM:
    name = model = "bad"

    def __init__(self, reply=None, exc=None):
        self.reply, self.exc = reply, exc

    def generate_json(self, system, prompt, schema, *, escalate=False):
        if "Planner" in schema.__name__:
            raise LLMUnavailable("x")
        if self.exc:
            raise self.exc
        return json.dumps(self.reply)


@pytest.mark.parametrize(
    "llm",
    [
        _BadLLM({"claims": [{"text": "ab", "claim_type": "question"}]}),
        _BadLLM(exc=RuntimeError("sdk exploded")),
    ],
)
def test_run_completes_with_deterministic_claims_when_model_output_is_bad(tmp_path, llm):
    fix = ROOT / "fixtures" / "scenario_a.json"
    repo = Repository(tmp_path / "bad.sqlite3")
    orch = build_orchestrator(
        mk(tmp_path), RunMode.SYNTHETIC, repo=repo, fixture_path=fix, llm=llm, as_of=date(2026, 10, 11),
        sleep=lambda x: None,
    )
    c = json.loads(fix.read_text(encoding="utf-8"))["case"]
    st = orch.create_case(
        CaseInput(target_domain=c["target_domain"], competitor_domains=c["competitor_domains"], mode=RunMode.SYNTHETIC)
    )
    orch.run(st.case_id)  # must not raise
    final = repo.load_case(st.case_id)
    assert final.stage in (CaseStage.COMPLETE, CaseStage.PARTIAL)
    assert repo.latest_report(st.case_id) is not None and final.claims


# ---------------------------------------------------------------- H6: access control


def test_remote_client_cannot_start_work_without_a_token(tmp_path, monkeypatch):
    client, s = api(
        tmp_path, monkeypatch, client=("203.0.113.9", 4444), data_provider="crustdata", crustdata_api_key="k"
    )
    started = []
    monkeypatch.setattr(server, "_start_thread", lambda *a, **k: started.append(a))
    body = {"target_domain": "acme.com", "mode": "live"}
    assert client.post("/api/cases", json=body).status_code == 403
    assert client.post("/api/cases/x/resume").status_code == 403
    assert client.post("/api/cases/x/cancel").status_code == 403
    assert client.post("/api/identity-check", json={"domains": ["acme.com"]}).status_code == 403
    assert not started
    assert client.get("/api/status").status_code == 200  # read-only routes stay open


def test_loopback_client_is_accepted_without_a_token(tmp_path, monkeypatch):
    client, _ = api(tmp_path, monkeypatch, data_provider="crustdata", crustdata_api_key="k")
    started = []
    monkeypatch.setattr(server, "_start_thread", lambda *a, **k: started.append(a))
    assert client.post("/api/cases", json={"target_domain": "acme.com", "mode": "live"}).status_code == 200
    assert started


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"])
def test_loopback_detection(host):
    assert server._is_loopback(host)
    assert not server._is_loopback("203.0.113.9") and not server._is_loopback("")


def test_token_required_from_every_client_when_configured(tmp_path, monkeypatch):
    for peer in (("127.0.0.1", 1), ("203.0.113.9", 2)):
        client, _ = api(tmp_path, monkeypatch, client=peer, dealscope_api_token="s3cret",
                        data_provider="crustdata", crustdata_api_key="k")
        started: list = []
        monkeypatch.setattr(server, "_start_thread", lambda *a, _s=started, **k: _s.append(a))
        body = {"target_domain": "acme.com", "mode": "live"}
        assert client.post("/api/cases", json=body).status_code == 401
        assert client.post("/api/cases", json=body, headers={"X-DealScope-Token": "wrong"}).status_code == 401
        assert not started
        ok = client.post("/api/cases", json=body, headers={"X-DealScope-Token": "s3cret"})
        assert ok.status_code == 200 and started
        assert client.get("/api/status").json()["auth_required"] is True


def test_untrusted_host_header_is_rejected_unless_allowed(tmp_path, monkeypatch):
    client, _ = api(tmp_path, monkeypatch)
    assert client.get("/api/status", headers={"host": "attacker.example:8000"}).status_code == 400
    assert client.get("/api/status", headers={"host": "127.0.0.1:8000"}).status_code == 200
    assert client.get("/api/status", headers={"host": "[::1]:8000"}).status_code == 200
    client, _ = api(tmp_path, monkeypatch, dealscope_trusted_hosts="dealscope.internal")
    assert client.get("/api/status", headers={"host": "dealscope.internal"}).status_code == 200
    assert client.get("/api/status", headers={"host": "localhost"}).status_code == 400
    client, _ = api(tmp_path, monkeypatch, dealscope_trusted_hosts="*")
    assert client.get("/api/status", headers={"host": "anything.example"}).status_code == 200


# ---------------------------------------------------------------- H7: identity-check quota


def test_identity_check_is_rate_limited_and_capped_per_request(tmp_path, monkeypatch):
    from dealscope.providers import pdl as pdl_mod

    client, s = api(tmp_path, monkeypatch, data_provider="free", pdl_api_key="pdl-k", pdl_monthly_limit=100)
    monkeypatch.setattr(
        pdl_mod.PdlClient,
        "_call",
        lambda self, method, path, params=None, body=None: ({"website": params["website"], "name": "x"}, 1),
    )
    assert client.post("/api/identity-check", json={"domains": [f"d{j}.com" for j in range(7)]}).status_code == 422
    codes = [
        client.post("/api/identity-check", json={"domains": [f"d{i}x{j}.com" for j in range(6)]}).status_code
        for i in range(8)
    ]
    assert codes[:5] == [200] * 5 and codes[5:] == [429] * 3  # 30 domains per minute
    assert pdl_mod.shared_usage_counter(s.pdl_usage_path, 100).remaining() == 70


def test_identity_rate_window_slides():
    assert server._identity_rate_ok("c", 30, now=0.0)
    assert not server._identity_rate_ok("c", 1, now=30.0)
    assert server._identity_rate_ok("c", 1, now=61.0)
    assert server._identity_rate_ok("other-client", 30, now=61.0)


# ---------------------------------------------------------------- inconclusive scorecards


def test_inconclusive_helper_follows_withheld_composite():
    from dealscope.agent.orchestrator import _is_inconclusive

    class SC:
        risk_score = None

    class SC2:
        risk_score = 40.0

    assert _is_inconclusive(None) and _is_inconclusive(SC()) and not _is_inconclusive(SC2())


def test_limited_evidence_status_labels():
    from dealscope.api import views

    st = _bare_state()
    st.finish_reason = "no_candidates_limited_evidence"
    st.stage = CaseStage.COMPLETE
    assert views.status_of(st, False)[0] == "Complete - limited evidence"
    st.stage = CaseStage.PARTIAL
    label, _, _, can_resume = views.status_of(st, False)
    assert label == "Partial - limited evidence" and can_resume


# ---------------------------------------------------------------- cache-key version fallback


def _legacy_setup(tmp_path, monkeypatch):
    from dealscope.agent import tools as tools_mod

    seen: list[tuple] = []
    real = tools_mod.cache_key

    def spy(provider, endpoint, body, api_version, bucket):
        seen.append((provider, endpoint, body, bucket))
        return real(provider, endpoint, body, api_version, bucket)

    monkeypatch.setattr(tools_mod, "cache_key", spy)
    repo, ex = _free_executor(tmp_path, _gh_handler)
    a = _crust_state()
    repo.create_case(a)
    assert ex.execute(a, JOB_ACTION).status == ToolRunStatus.SUCCEEDED
    provider, endpoint, body, bucket = seen[0]
    new_key = real(provider, endpoint, body, "v+cache2", bucket)
    legacy_key = real(provider, endpoint, body, "v", bucket)
    assert repo.cache_get(new_key) is not None
    return repo, ex, new_key, legacy_key


def test_legacy_unversioned_cache_row_is_reused_and_restored(tmp_path, monkeypatch):
    repo, ex, new_key, legacy_key = _legacy_setup(tmp_path, monkeypatch)
    with repo.transaction() as conn:  # simulate a row written before the version suffix existed
        conn.execute("UPDATE response_cache SET cache_key=?", (legacy_key,))
    assert repo.cache_get(new_key) is None
    b = _crust_state()
    repo.create_case(b)
    assert ex.execute(b, JOB_ACTION).status == ToolRunStatus.CACHED  # no new paid call
    assert repo.cache_get(new_key) is not None  # re-stored under the current key


def test_undecodable_legacy_cache_row_is_deleted(tmp_path, monkeypatch):
    repo, ex, new_key, legacy_key = _legacy_setup(tmp_path, monkeypatch)
    with repo.transaction() as conn:
        conn.execute("DELETE FROM response_cache WHERE cache_key=?", (new_key,))
        conn.execute(
            "INSERT INTO response_cache (cache_key, endpoint, response_json, created_at, api_version) "
            "VALUES (?, 'x', '{\"items\": 5}', 'now', 'v')",
            (legacy_key,),
        )
    b = _crust_state()
    repo.create_case(b)
    assert ex.execute(b, JOB_ACTION).status == ToolRunStatus.SUCCEEDED  # went live instead
    assert repo.cache_get(legacy_key) is None


# ---------------------------------------------------------------- cross-site, lease, rate limiter, resume


@pytest.mark.parametrize(
    "headers,ok",
    [
        ({"Origin": "http://localhost:8000"}, True),
        ({"Origin": "http://127.0.0.1:8000"}, True),
        ({"Origin": "http://localhost:5173"}, True),
        ({"Origin": "http://[::1]:5173"}, True),
        ({"Origin": "https://evil.example"}, False),
        ({"Origin": "null"}, False),
        ({"Sec-Fetch-Site": "cross-site"}, False),
        ({"Sec-Fetch-Site": "same-origin"}, True),
        ({}, True),
    ],
)
def test_cancel_cross_site_guard(tmp_path, monkeypatch, headers, ok):
    c, _ = api(tmp_path, monkeypatch)
    r = c.post("/api/cases/nope/cancel", headers=headers)
    assert (r.status_code == 409) if ok else (r.status_code == 403)  # 409 = passed the guard, case not running


def test_cross_site_guard_applies_with_token(tmp_path, monkeypatch):
    from pydantic import SecretStr

    c, _ = api(tmp_path, monkeypatch, dealscope_api_token=SecretStr("t"))
    h = {"X-DealScope-Token": "t"}
    assert c.post("/api/cases/nope/cancel", headers={**h, "Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/cases/nope/cancel", headers=h).status_code == 409


def test_lease_released_when_thread_start_fails(tmp_path, monkeypatch):
    c, s = api(tmp_path, monkeypatch)
    cid = seed_case(s)

    def boom(self):
        raise RuntimeError("cannot start new thread")

    monkeypatch.setattr(threading.Thread, "start", boom)
    with pytest.raises(RuntimeError):
        server._start_thread(cid, RunMode.LIVE, None, None, resume=False)
    monkeypatch.undo()
    monkeypatch.setattr(server, "_settings", lambda: s)
    repo = Repository(s.dealscope_db_path)
    try:
        assert repo.acquire_lease(cid, "someone-else", 60.0)  # not stuck behind the failed start
    finally:
        repo.close()
    assert cid not in server._runs


def test_lease_released_when_worker_cannot_open_repo(tmp_path, monkeypatch):
    c, s = api(tmp_path, monkeypatch)
    cid = seed_case(s)
    real = server._repo
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:  # 1 = lease acquisition, 2 = the worker's own repo
            raise RuntimeError("db unavailable")
        return real()

    monkeypatch.setattr(server, "_repo", flaky)
    server._start_thread(cid, RunMode.LIVE, None, None, resume=False)
    server._runs[cid].join(10)
    repo = Repository(s.dealscope_db_path)
    try:
        assert repo.acquire_lease(cid, "someone-else", 60.0)
    finally:
        repo.close()


def test_identity_rate_limiter_drops_idle_clients():
    server._identity_hits.clear()
    assert server._identity_rate_ok("1.2.3.4", 3, now=0.0)
    assert "1.2.3.4" in server._identity_hits
    assert server._identity_rate_ok("5.6.7.8", 1, now=100.0)  # other client, 100s later
    assert server._identity_rate_ok("1.2.3.4", 1, now=100.0)
    assert len(server._identity_hits["1.2.3.4"]) == 1  # old hits pruned
    assert not server._identity_rate_ok("9.9.9.9", 31, now=100.0)
    assert "9.9.9.9" not in server._identity_hits  # rejected first-time client leaves nothing behind
    # idle client: fully expired, rejected request must not leave an empty deque
    assert not server._identity_rate_ok("1.2.3.4", 31, now=500.0)
    assert "1.2.3.4" not in server._identity_hits
    server._identity_hits.clear()


def test_limited_evidence_complete_offers_resume_only_when_key_now_configured(tmp_path):
    from dealscope.api import views

    st = _bare_state()
    st.stage = CaseStage.COMPLETE
    st.finish_reason = "no_candidates_limited_evidence"
    st.unavailable_tools = {"enrich_company": "NOT_CONFIGURED"}
    assert views.status_of(st, False)[3] is False
    assert views.status_of(st, False, mk(tmp_path))[3] is False  # still no key
    assert views.status_of(st, False, mk(tmp_path, pdl_api_key="k"))[3] is True
    assert views.status_of(st, True, mk(tmp_path, pdl_api_key="k"))[3] is False  # running
    st.unavailable_tools = {}
    assert views.status_of(st, False, mk(tmp_path, pdl_api_key="k"))[3] is False
