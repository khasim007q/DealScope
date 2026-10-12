from decimal import Decimal

import pytest

from dealscope.budget.governor import BudgetDenied, CreditGovernor
from dealscope.config import Settings
from dealscope.persistence.repository import Repository


def make_settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.fixture
def repo():
    r = Repository(":memory:")
    yield r
    r.close()


def gov(repo, **kw) -> CreditGovernor:
    return CreditGovernor(repo, make_settings(**kw))


def test_known_prices(repo):
    g = gov(repo)
    assert g.estimate("company_enrich", 4) == Decimal("8")
    assert g.estimate("company_search", 100) == Decimal("3.00")
    assert g.estimate("person_search", 100) == Decimal("23.00")
    assert g.estimate("person_enrich_cached", 20) == Decimal("20")
    assert g.estimate("company_enrich", 0) == Decimal("0")


def test_price_overrides_and_multiplier(repo):
    g = CreditGovernor(
        repo, make_settings(), price_overrides={"company_enrich": Decimal("3")}, safety_multiplier=Decimal("1.5")
    )
    assert g.estimate("company_enrich", 2) == Decimal("9.0")
    with pytest.raises(ValueError):
        CreditGovernor(repo, make_settings(), safety_multiplier=Decimal("0.5"))


def test_unknown_job_price_fails_closed(repo):
    g = gov(repo)
    with pytest.raises(BudgetDenied) as exc:
        g.estimate("job_search", 10)
    assert exc.value.reason == "UNKNOWN_PRICE_FAIL_CLOSED"
    with pytest.raises(BudgetDenied) as exc:
        g.reserve("c1", Decimal("300"), "job_search", 10)
    assert exc.value.reason == "UNKNOWN_PRICE_FAIL_CLOSED"
    assert repo.ledger_totals("c1")["reserved"] == Decimal("0")


def test_unknown_operation_fails_closed(repo):
    with pytest.raises(BudgetDenied) as exc:
        gov(repo).estimate("mystery_op", 1)
    assert exc.value.reason == "UNKNOWN_PRICE_FAIL_CLOSED"


def test_configured_job_price(repo):
    g = gov(repo, crustdata_job_cost_per_result=Decimal("0.1"))
    assert g.estimate("job_search", 25) == Decimal("2.5")
    g2 = gov(repo, crustdata_job_cost_per_result=Decimal("0.1"), crustdata_job_call_reserve=Decimal("5"))
    assert g2.estimate("job_search", 25) == Decimal("7.5")
    assert g2.estimate("job_search", 0) == Decimal("5")
    r = g2.reserve("c1", Decimal("300"), "job_search", 25)
    assert r.amount == Decimal("7.5")


def test_negative_quantity_raises(repo):
    g = gov(repo)
    with pytest.raises(ValueError):
        g.estimate("company_enrich", -1)
    with pytest.raises(ValueError):
        g.reserve("c1", Decimal("300"), "company_enrich", -1)


def test_per_case_cap_blocks(repo):
    g = gov(repo)
    g.reserve("c1", Decimal("10"), "company_enrich", 4)  # 8
    with pytest.raises(BudgetDenied) as exc:
        g.reserve("c1", Decimal("10"), "company_enrich", 2)  # 8 + 4 > 10
    assert exc.value.reason == "PER_CASE_BUDGET_EXCEEDED"
    g.reserve("c1", Decimal("10"), "company_enrich", 1)  # exactly 10 is allowed
    g.reserve("c2", Decimal("10"), "company_enrich", 1)  # another case is unaffected


def test_settings_case_cap_overrides_larger_request(repo):
    g = gov(repo, crustdata_max_case_credits=Decimal("5"))
    with pytest.raises(BudgetDenied) as exc:
        g.reserve("c1", Decimal("1000"), "company_enrich", 3)  # 6 > min(1000, 5)
    assert exc.value.reason == "PER_CASE_BUDGET_EXCEEDED"
    assert g.case_summary("c1", Decimal("1000"))["budget"] == Decimal("5")


def test_global_reserve_blocks(repo):
    g = gov(repo, crustdata_total_credits=Decimal("5000"), crustdata_global_reserve_credits=Decimal("1000"))
    # pre-existing spend by other cases: 3,998 credits settled
    repo.ledger_insert("old", "company_enrich", 1999, Decimal("3998"), status="settled_estimate")
    g.reserve("c1", Decimal("300"), "company_enrich", 1)  # 3998 + 2 = 4000, exactly the spendable limit
    with pytest.raises(BudgetDenied) as exc:
        g.reserve("c1", Decimal("300"), "person_search", 1)  # +0.23 over limit
    assert exc.value.reason == "GLOBAL_SPENDABLE_BUDGET_EXCEEDED"


def test_unknown_counts_against_global_and_case(repo):
    g = gov(repo, crustdata_total_credits=Decimal("10"), crustdata_global_reserve_credits=Decimal("0"))
    res = g.reserve("c1", Decimal("300"), "company_enrich", 4)  # 8
    g.mark_unknown(res, "timeout")
    assert repo.ledger_totals(None)["unknown_count"] == 1
    with pytest.raises(BudgetDenied) as exc:
        g.reserve("c2", Decimal("300"), "company_enrich", 2)  # 8 unknown + 4 > 10
    assert exc.value.reason == "GLOBAL_SPENDABLE_BUDGET_EXCEEDED"
    s = g.case_summary("c1", Decimal("300"))
    assert s["unknown_count"] == 1
    assert s["remaining"] == Decimal("292")


def test_reserve_then_settle_accounting(repo):
    g = gov(repo)
    res = g.reserve("c1", Decimal("300"), "company_enrich", 3)
    assert res.amount == Decimal("6")
    s = g.case_summary("c1", Decimal("300"))
    assert s["reserved"] == Decimal("6")
    assert s["estimated_used"] == Decimal("0")
    assert s["remaining"] == Decimal("294")
    g.settle(res, None)  # actual unknown => conservative estimate retained
    s = g.case_summary("c1", Decimal("300"))
    assert s["reserved"] == Decimal("0")
    assert s["estimated_used"] == Decimal("6")
    assert s["actual_used"] == Decimal("0")
    assert repo.ledger_get(res.ledger_id)["status"] == "settled_estimate"
    with pytest.raises(ValueError):
        g.settle(res, None)  # already settled


def test_settle_with_actual(repo):
    g = gov(repo)
    res = g.reserve("c1", Decimal("300"), "company_enrich", 3)
    g.settle(res, Decimal("4"))
    s = g.case_summary("c1", Decimal("300"))
    assert s["estimated_used"] == Decimal("4")
    assert s["actual_used"] == Decimal("4")
    assert s["reserved"] == Decimal("0")
    assert s["remaining"] == Decimal("296")
    assert repo.ledger_get(res.ledger_id)["status"] == "settled_actual"
    with pytest.raises(ValueError):
        g.settle(g.reserve("c1", Decimal("300"), "company_enrich", 1), Decimal("-1"))


def test_release_frees_reservation(repo):
    g = gov(repo)
    res = g.reserve("c1", Decimal("300"), "company_enrich", 5)
    assert g.case_summary("c1", Decimal("300"))["reserved"] == Decimal("10")
    g.release(res, "validation failed before send")
    s = g.case_summary("c1", Decimal("300"))
    assert s["reserved"] == Decimal("0")
    assert s["remaining"] == Decimal("300")
    row = repo.ledger_get(res.ledger_id)
    assert row["status"] == "released"
    assert row["reason"] == "validation failed before send"
    with pytest.raises(ValueError):
        g.release(res, "again")


def test_unknown_can_be_resolved_by_settle(repo):
    g = gov(repo)
    res = g.reserve("c1", Decimal("300"), "company_enrich", 1)
    g.mark_unknown(res, "connection reset")
    assert repo.ledger_totals("c1")["unknown_count"] == 1
    g.settle(res, Decimal("0"))  # usage ledger later confirmed nothing was billed
    t = repo.ledger_totals("c1")
    assert t["unknown_count"] == 0
    assert t["estimated_used"] == Decimal("0")
    with pytest.raises(ValueError):
        g.release(res, "x")


def test_reservation_persisted_before_return(repo):
    g = gov(repo)
    res = g.reserve("c1", Decimal("300"), "person_search", 100, tool_run_id="tr-1")
    row = repo.ledger_get(res.ledger_id)
    assert row["status"] == "reserved"
    assert row["tool_run_id"] == "tr-1"
    assert row["estimate"] == Decimal("23.00")
    assert row["quantity"] == 100


def test_global_summary(repo):
    g = gov(repo)
    g.settle(g.reserve("c1", Decimal("300"), "company_enrich", 1), None)
    gs = g.global_summary()
    assert gs["spendable"] == Decimal("4000")
    assert gs["estimated_used"] == Decimal("2")
    assert gs["remaining"] == Decimal("3998")


def test_synthetic_pool_never_consumes_live_budget(repo):
    live = gov(repo, crustdata_total_credits=Decimal("10"), crustdata_global_reserve_credits=Decimal("0"))
    sim = CreditGovernor(repo, live.settings, pool="synthetic")
    sim.settle(sim.reserve("syn", Decimal("300"), "company_enrich", 5), None)  # 10 simulated credits
    assert live.global_summary()["estimated_used"] == Decimal("0")
    live.reserve("c1", Decimal("300"), "company_enrich", 5)  # full live budget still available


def test_synthetic_pool_has_no_global_cap(repo):
    sim = CreditGovernor(
        repo,
        Settings(_env_file=None, crustdata_total_credits=Decimal("10"), crustdata_global_reserve_credits=Decimal("0")),
        pool="synthetic",
    )
    for i in range(5):  # 5 demo cases x 4 credits = 20 simulated credits > 10 "spendable"
        sim.settle(sim.reserve(f"demo-{i}", Decimal("300"), "company_enrich", 2), None)
    with pytest.raises(BudgetDenied) as exc:  # the per-case cap still applies
        sim.reserve("demo-x", Decimal("3"), "company_enrich", 2)
    assert exc.value.reason == "PER_CASE_BUDGET_EXCEEDED"
