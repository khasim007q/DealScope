from decimal import Decimal

import pytest

from dealscope.domain.enums import ClaimType, EvidenceKind, ToolRunStatus
from dealscope.domain.models import (
    CaseInput,
    CaseState,
    CompanyProfilePayload,
    EvidenceRecord,
    FindingClaim,
)
from dealscope.persistence.repository import Repository, cache_key, idempotency_key


def make_state(label: str = "improved") -> CaseState:
    case_input = CaseInput(
        target_domain="https://www.target.example/",
        competitor_domains=["peer-a.example", "peer-b.example"],
        deal_thesis="Acquire a developer tooling platform for its engineering team.",
    )
    return CaseState(input=case_input, mode=case_input.mode, credit_budget=Decimal("300"), run_label=label)


def make_evidence(
    case_id: str, dedup_key: str = "company:target.example", domain: str = "target.example"
) -> EvidenceRecord:
    return EvidenceRecord(
        case_id=case_id,
        kind=EvidenceKind.COMPANY_PROFILE,
        subject_domain=domain,
        source_provider="fixture",
        source_endpoint="fixture/company",
        payload=CompanyProfilePayload(domain=domain, total_headcount=120),
        dedup_key=dedup_key,
        independence_group="fixture",
        synthetic=True,
        credit_estimate=Decimal("2"),
    )


@pytest.fixture
def repo():
    r = Repository(":memory:")
    yield r
    r.close()


def test_case_roundtrip_and_save(repo):
    state = make_state()
    repo.create_case(state)
    loaded = repo.load_case(state.case_id)
    assert loaded is not None
    assert loaded.case_id == state.case_id
    assert loaded.input.target_domain == "target.example"
    assert loaded.credit_budget == Decimal("300")
    assert loaded.latest_checkpoint_id is not None  # initial checkpoint written on creation

    state.iteration_count = 3
    state.credit_estimated_used = Decimal("12.34")
    state.finish_reason = "budget"
    repo.save_case(state)
    again = repo.load_case(state.case_id)
    assert again.iteration_count == 3
    assert again.credit_estimated_used == Decimal("12.34")
    assert repo.load_case("nope") is None

    rows = repo.list_cases()
    assert len(rows) == 1
    assert rows[0]["case_id"] == state.case_id
    assert rows[0]["target"] == "target.example"
    assert rows[0]["finish_reason"] == "budget"
    assert rows[0]["mode"] == "synthetic"
    assert rows[0]["run_label"] == "improved"


def test_save_unknown_case_raises(repo):
    with pytest.raises(KeyError):
        repo.save_case(make_state())


def test_checkpoints_increment_and_latest(repo):
    state = make_state()
    repo.create_case(state)
    cp0 = state.latest_checkpoint_id
    state.iteration_count = 1
    cp1 = repo.checkpoint(state, "after-tool-1")
    state.iteration_count = 2
    cp2 = repo.checkpoint(state, "after-tool-2")
    assert cp0 < cp1 < cp2
    assert state.latest_checkpoint_id == cp2
    latest = repo.latest_checkpoint(state.case_id)
    assert latest.iteration_count == 2
    assert latest.latest_checkpoint_id == cp2
    assert repo.load_case(state.case_id).latest_checkpoint_id == cp2
    assert repo.latest_checkpoint("missing") is None


def test_evidence_dedup_returns_existing_id(repo):
    state = make_state()
    repo.create_case(state)
    first = make_evidence(state.case_id)
    dup = make_evidence(state.case_id)  # same dedup_key, new evidence_id
    other = make_evidence(state.case_id, dedup_key="company:peer-a.example", domain="peer-a.example")
    ids = repo.add_evidence([first, dup, other])
    assert ids == [first.evidence_id, first.evidence_id, other.evidence_id]
    assert len(repo.get_evidence(state.case_id)) == 2

    detailed = repo.add_evidence_detailed([make_evidence(state.case_id), make_evidence(state.case_id, "k2")])
    assert detailed[0] == (first.evidence_id, False)
    assert detailed[1][1] is True

    got = repo.get_evidence_by_ids([other.evidence_id, first.evidence_id, "missing"])
    assert [g.evidence_id for g in got] == [other.evidence_id, first.evidence_id]
    assert got[0].payload.domain == "peer-a.example"
    assert got[0].synthetic is True
    assert repo.get_evidence_by_ids([]) == []


def test_evidence_dedup_is_per_case(repo):
    s1, s2 = make_state(), make_state()
    repo.create_case(s1)
    repo.create_case(s2)
    a = make_evidence(s1.case_id)
    b = make_evidence(s2.case_id)
    assert repo.add_evidence([a]) == [a.evidence_id]
    assert repo.add_evidence([b]) == [b.evidence_id]


def test_tool_run_lifecycle(repo):
    state = make_state()
    repo.create_case(state)
    key = idempotency_key(
        state.case_id, "crustdata", "/company/enrich", {"domain": "target.example"}, "2025-11-01", "live"
    )
    run_id = repo.start_tool_run(state.case_id, "enrich_company", key, "fp1", Decimal("2"))
    assert repo.find_successful_tool_run(state.case_id, key) is None
    assert [r["tool_run_id"] for r in repo.find_unresolved_tool_runs(state.case_id)] == [run_id]

    repo.finish_tool_run(run_id, ToolRunStatus.SUCCEEDED, result_count=1, cost_actual=Decimal("2"))
    found = repo.find_successful_tool_run(state.case_id, key)
    assert found["tool_run_id"] == run_id
    assert found["result_count"] == 1
    assert found["cost_estimate"] == Decimal("2")
    assert found["cost_actual"] == Decimal("2")
    assert found["finished_at"] is not None
    assert repo.find_unresolved_tool_runs(state.case_id) == []
    assert repo.find_successful_tool_run("other-case", key) is None

    failed = repo.start_tool_run(state.case_id, "search_people", "k2", "fp2", Decimal("3"))
    repo.finish_tool_run(failed, "failed", error_code="HTTP_500", error_message="boom", attempt_count=3)
    runs = repo.list_tool_runs(state.case_id)
    assert [r["tool_run_id"] for r in runs] == [run_id, failed]
    assert runs[1]["attempt_count"] == 3
    assert runs[1]["error_code"] == "HTTP_500"
    assert repo.find_successful_tool_run(state.case_id, "k2") is None
    with pytest.raises(KeyError):
        repo.finish_tool_run("tr-missing", "failed")


def test_unresolved_runs_include_unknown_outcome(repo):
    state = make_state()
    repo.create_case(state)
    a = repo.start_tool_run(state.case_id, "search_jobs", "ka", "fa", Decimal("1"))
    b = repo.start_tool_run(state.case_id, "search_jobs", "kb", "fb", Decimal("1"))
    c = repo.start_tool_run(state.case_id, "search_jobs", "kc", "fc", Decimal("1"))
    repo.finish_tool_run(a, ToolRunStatus.UNKNOWN_OUTCOME, error_code="TIMEOUT")
    repo.finish_tool_run(b, ToolRunStatus.CACHED, result_count=2)
    ids = {r["tool_run_id"] for r in repo.find_unresolved_tool_runs(state.case_id)}
    assert ids == {a, c}
    assert repo.find_successful_tool_run(state.case_id, "kb")["tool_run_id"] == b


def test_cache_roundtrip(repo):
    k = cache_key("crustdata", "/company/enrich", {"domain": "t.example"}, "2025-11-01", "2026-10-11")
    assert repo.cache_get(k) is None
    repo.cache_put(k, "/company/enrich", {"data": [{"a": 1}]}, "2025-11-01")
    assert repo.cache_get(k) == {"data": [{"a": 1}]}
    repo.cache_put(k, "/company/enrich", {"data": []}, "2025-11-01")
    assert repo.cache_get(k) == {"data": []}


def test_key_helpers_deterministic():
    body1 = {"b": 1, "a": [1, 2]}
    body2 = {"a": [1, 2], "b": 1}
    k1 = idempotency_key("c1", "crustdata", "/x", body1, "v1", "live")
    assert k1 == idempotency_key("c1", "crustdata", "/x", body2, "v1", "live")
    assert k1 != idempotency_key("c2", "crustdata", "/x", body1, "v1", "live")
    assert k1 != idempotency_key("c1", "crustdata", "/x", body1, "v1", "synthetic")
    assert len(k1) == 64
    c1 = cache_key("crustdata", "/x", body1, "v1", "2026-10-11")
    assert c1 == cache_key("crustdata", "/x", body2, "v1", "2026-10-11")
    assert c1 != cache_key("crustdata", "/x", body1, "v1", "2026-10-12")


def test_save_report_and_latest(repo):
    state = make_state()
    repo.create_case(state)
    assert repo.latest_report(state.case_id) is None
    claim = FindingClaim(text="Engineering headcount grew.", claim_type=ClaimType.OBSERVATION, evidence_ids=["ev-1"])
    second = FindingClaim(text="Second claim.", claim_type=ClaimType.QUESTION)
    r1 = repo.save_report(state.case_id, "# v1", {"k": 1}, [claim])
    r2 = repo.save_report(state.case_id, "# v2", {"k": 2}, [claim, second])
    assert r2 > r1
    latest = repo.latest_report(state.case_id)
    assert latest["id"] == r2
    assert latest["markdown"] == "# v2"
    assert latest["bundle"] == {"k": 2}
    assert len(latest["claims"]) == 2
    assert latest["claims"][0].claim_id == claim.claim_id


def test_events_ordering(repo):
    state = make_state()
    repo.create_case(state)
    for i in range(5):
        repo.add_event(state.case_id, "step", {"i": i})
    repo.add_event("other", "x", {})
    events = repo.list_events(state.case_id)
    assert [e["payload"]["i"] for e in events] == [0, 1, 2, 3, 4]
    assert all(e["type"] == "step" for e in events)
    after = repo.list_events(state.case_id, after_id=events[2]["id"])
    assert [e["payload"]["i"] for e in after] == [3, 4]


def test_ledger_primitives_and_totals(repo):
    r = repo.ledger_insert("c1", "company_enrich", 1, Decimal("2"))
    s = repo.ledger_insert("c1", "person_search", 10, Decimal("0.3"))
    u = repo.ledger_insert("c2", "company_enrich", 1, Decimal("2"))
    a = repo.ledger_insert("c1", "company_enrich", 1, Decimal("2"))
    rel = repo.ledger_insert("c1", "company_enrich", 1, Decimal("2"))
    repo.ledger_update(s, "settled_estimate")
    repo.ledger_update(u, "unknown", reason="timeout")
    repo.ledger_update(a, "settled_actual", actual=Decimal("1.5"))
    repo.ledger_update(rel, "released", reason="never sent")
    c1 = repo.ledger_totals("c1")
    assert c1["reserved"] == Decimal("2")  # r
    assert c1["estimated_used"] == Decimal("1.8")  # 0.3 settled_estimate + 1.5 settled_actual
    assert c1["actual_used"] == Decimal("1.5")
    assert c1["unknown_count"] == 0
    glob = repo.ledger_totals(None)
    assert glob["unknown_count"] == 1
    assert glob["unknown_estimate"] == Decimal("2")
    assert repo.ledger_totals("c2")["reserved"] == Decimal("0")
    assert repo.ledger_get(r)["status"] == "reserved"
    with pytest.raises(KeyError):
        repo.ledger_update(9999, "released")


def test_durability_across_reopen(tmp_path):
    db = tmp_path / "nested" / "dealscope.sqlite3"
    repo = Repository(db)
    state = make_state()
    repo.create_case(state)
    ev = make_evidence(state.case_id)
    repo.add_evidence([ev])
    state.evidence_ids.append(ev.evidence_id)
    state.iteration_count = 4
    cp = repo.checkpoint(state, "after-tool")
    run_id = repo.start_tool_run(state.case_id, "enrich_company", "kk", "fp", Decimal("2"))
    repo.ledger_insert(state.case_id, "company_enrich", 1, Decimal("2"))
    repo.add_event(state.case_id, "tool_started", {"tool_run_id": run_id})
    repo.close()

    reopened = Repository(db)
    try:
        loaded = reopened.load_case(state.case_id)
        assert loaded.iteration_count == 4
        assert loaded.evidence_ids == [ev.evidence_id]
        assert loaded.latest_checkpoint_id == cp
        assert reopened.latest_checkpoint(state.case_id).iteration_count == 4
        assert [e.evidence_id for e in reopened.get_evidence(state.case_id)] == [ev.evidence_id]
        assert [r["tool_run_id"] for r in reopened.find_unresolved_tool_runs(state.case_id)] == [run_id]
        assert reopened.ledger_totals(state.case_id)["reserved"] == Decimal("2")
        assert len(reopened.list_events(state.case_id)) == 1
        assert [c["case_id"] for c in reopened.list_cases()] == [state.case_id]
    finally:
        reopened.close()


def test_transaction_rolls_back_on_error(repo):
    with pytest.raises(RuntimeError), repo.transaction():
        repo.ledger_insert("c1", "company_enrich", 1, Decimal("2"))
        raise RuntimeError("boom")
    assert repo.ledger_totals("c1")["reserved"] == Decimal("0")
