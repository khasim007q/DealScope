import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from dealscope.domain.enums import EvidenceKind
from dealscope.providers.base import (
    AuthError,
    BadRequestError,
    InsufficientCreditsError,
    RetryExhaustedError,
)
from dealscope.providers.pdl import (
    PdlClient,
    PdlQuotaExhaustedError,
    PdlUsageCounter,
    growth_from_series,
    series_points,
)

KEY = "pdl-SECRET-key-123"

COMPANY = {
    "status": 200,
    "id": "pdl-co-1",
    "name": "linear",
    "display_name": "Linear",
    "website": "linear.app",
    "size": "51-200",
    "employee_count": 120,
    "industry": "computer software",
    "founded": 2019,
    "total_funding_raised": 52000000,
    "location": {"country": "united states", "name": "san francisco, california, united states"},
    "likelihood": 10,
    "employee_count_by_month": {
        "2025-11": 100,
        "2026-02": 105,
        "2026-05": 110,
        "2026-08": 120,
        "2026-10": 120,
        "2026-11": 126,
    },
}


def person(pid, entries, **extra):
    return {
        "id": pid,
        "job_title": "cto",
        "job_company_name": "Other Co",
        "job_company_website": "other.com",
        "experience": entries,
        **extra,
    }


def entry(site, title, start, end=None, levels=None):
    return {
        "company": {"name": site, "website": site},
        "title": {"name": title, "levels": levels or []},
        "start_date": start,
        "end_date": end,
    }


def client(handler, tmp_path=None, limit=100, **kw):
    usage = PdlUsageCounter(tmp_path / "u.json", limit, today=lambda: date(2026, 11, 4)) if tmp_path else None
    return PdlClient(KEY, transport=httpx.MockTransport(handler), sleep=lambda s: None, usage=usage, **kw)


def test_company_mapping_and_headers():
    seen = {}

    def h(req):
        seen["key"] = req.headers["x-api-key"]
        seen["url"] = str(req.url)
        return httpx.Response(200, json=COMPANY)

    r = client(h).enrich_company("https://www.Linear.app/")
    assert seen["key"] == KEY and "website=linear.app" in seen["url"]
    p = r.items[0].payload
    assert r.items[0].kind == EvidenceKind.COMPANY_PROFILE
    assert (p.name, p.domain, p.total_headcount, p.industry, p.hq_country) == (
        "Linear",
        "linear.app",
        120,
        "computer software",
        "United States",
    )
    assert p.funding_total_usd == 52000000.0
    assert p.total_growth_pct["12m"] == 26.0  # 100 -> 126
    assert p.engineering_headcount is None and p.engineering_growth_pct == {}  # never invented
    assert r.credits_used == Decimal("0")
    assert any("no engineering role breakdown" in n for n in r.notes)
    assert KEY not in repr(client(h))


def test_company_engineering_from_role_breakdown():
    data = {
        **COMPANY,
        "employee_count_by_month_by_role": {
            "2026-05": {"engineering": 40, "sales": 10},
            "2026-11": {"engineering": 50, "sales": 12},
        },
    }
    r = client(lambda req: httpx.Response(200, json=data)).enrich_company("linear.app")
    p = r.items[0].payload
    assert p.engineering_headcount == 50 and p.engineering_growth_pct == {"6m": 25.0}


def test_growth_helpers():
    pts = series_points({"2026-11": 126, "2025-11": 100, "bad": 3, "2026-05": "x"})
    assert pts[-1][1] == 126 and growth_from_series(pts) == {"12m": 26.0}
    assert growth_from_series(pts[:1]) == {}


def test_company_404_and_website_mismatch():
    c = client(lambda req: httpx.Response(404, json={"status": 404, "error": {"type": "not_found", "message": "none"}}))
    r = c.enrich_company("nothing.example")
    assert r.items == [] and r.notes[-1] == "no match"
    c2 = client(lambda req: httpx.Response(200, json={**COMPANY, "website": "other.com"}))
    assert c2.enrich_company("linear.app").items == []


@pytest.mark.parametrize(
    "status,exc,code",
    [
        (401, AuthError, "AUTH"),
        (403, AuthError, "PERMISSION"),
        (402, InsufficientCreditsError, "INSUFFICIENT_CREDITS"),
        (400, BadRequestError, "BAD_REQUEST"),
    ],
)
def test_error_mapping(status, exc, code):
    body = {"status": status, "error": {"type": "x", "message": f"bad key {KEY}"}}
    with pytest.raises(exc) as ei:
        client(lambda req: httpx.Response(status, json=body)).enrich_company("linear.app")
    assert ei.value.code == code and KEY not in str(ei.value)


def test_429_retried_then_exhausted():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(429, json={"error": {"type": "rate", "message": "slow"}}, headers={"retry-after": "0"})

    with pytest.raises(RetryExhaustedError):
        client(h, max_retries=2).enrich_company("linear.app")
    assert len(calls) == 3


def test_person_search_mapping_current_and_past():
    captured = {}
    profiles = [
        person(
            "a",
            [entry("linear.app", "VP Engineering", "2021-03", "2024-02", ["vp"]), entry("other.com", "CTO", "2024-03")],
        ),
        person("b", [entry("linear.app", "Senior Engineer", "2020-01", "2021-01")]),
        person("c", [entry("linear.app", "Head of Engineering", "2022-01")]),  # still current: not a past interval
        {"experience": []},  # no id
    ]

    def h(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"status": 200, "data": profiles, "total": 40})

    r = client(h).search_people("linear.app", "technical_leadership", "past_target_employment", "other.com", 50)
    assert captured["size"] == 10  # capped by max_people_results
    q = json.dumps(captured["query"])
    assert '"experience.company.website": "linear.app"' in q and '"job_company_website": "other.com"' in q
    assert '"must_not"' in q
    assert [i.payload.title_at_target for i in r.items] == ["VP Engineering", "Senior Engineer"]
    a = r.items[0].payload
    assert (a.target_start, a.target_end, a.currently_at_target, a.seniority) == ("2021-03", "2024-02", False, "vp")
    assert (a.current_employer_domain, a.current_title, a.role_group) == ("other.com", "cto", "technical_leadership")
    assert a.person_ref.startswith("p-") and r.items[0].valid_to == "2024-02"
    assert any("single page only" in n for n in r.notes) and any("skipped" in n for n in r.notes)

    cur = client(h).search_people("linear.app", "technical_leadership", "current_target_employment", None, 5)
    assert [i.payload.title_at_target for i in cur.items] == ["Head of Engineering"]
    assert cur.items[0].payload.target_end is None and cur.items[0].payload.currently_at_target is True


def test_person_search_404_is_empty_and_bad_args():
    c = client(lambda req: httpx.Response(404, json={"status": 404, "error": {"message": "no records"}}))
    assert c.search_people("linear.app", "security", "past_target_employment", None, 5).items == []
    with pytest.raises(BadRequestError):
        c.search_people("linear.app", "nope", "past_target_employment", None, 5)


def test_identity_shapes():
    ok = client(lambda req: httpx.Response(200, json=COMPANY)).identify_company("linear.app")
    assert (ok.ok, ok.status, ok.resolved_name, ok.match_count) == (True, "ok", "Linear", 1)
    assert set(ok.candidates[0]) >= {"name", "primary_domain", "employee_count_range"}
    assert ok.candidates[0]["employee_count_range"] == "51-200"
    none = client(lambda req: httpx.Response(404, json={"error": {"message": "x"}})).identify_company("zzz.example")
    assert (none.status, none.match_count, none.candidates) == ("no_match", 0, [])
    mm = client(lambda req: httpx.Response(200, json={**COMPANY, "website": "other.com"})).identify_company(
        "linear.app"
    )
    assert mm.status == "mismatch" and not mm.ok


def test_identity_then_enrich_costs_one_record(tmp_path):
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(200, json=COMPANY)

    c = client(h, tmp_path)
    c.identify_company("linear.app")
    c.enrich_company("linear.app")
    assert len(n) == 1 and c.usage.used() == 1


def test_monthly_limit_guard(tmp_path):
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(200, json=COMPANY)

    c = client(h, tmp_path, limit=2)
    c.enrich_company("a.com")
    c.enrich_company("b.com")
    assert c.usage.remaining() == 0
    with pytest.raises(PdlQuotaExhaustedError) as ei:
        c.enrich_company("c.com")
    assert ei.value.code == "PDL_MONTHLY_LIMIT" and "monthly" in str(ei.value)
    assert len(n) == 2  # refused locally, no request sent
    with pytest.raises(PdlQuotaExhaustedError):
        c.search_people("linear.app", "security", "past_target_employment", None, 5)


def test_person_search_size_limited_by_remaining_and_counts_records(tmp_path):
    sizes = []

    def h(req):
        sizes.append(json.loads(req.content)["size"])
        return httpx.Response(200, json={"data": [person("a", [entry("linear.app", "CISO", "2020-01", "2021-01")])]})

    c = client(h, tmp_path, limit=3)
    c.search_people("linear.app", "security", "past_target_employment", None, 10)
    assert sizes == [3] and c.usage.used() == 1


def test_usage_counter_resets_each_month_and_survives_garbage(tmp_path):
    month = [date(2026, 11, 4)]
    u = PdlUsageCounter(tmp_path / "x" / "u.json", 5, today=lambda: month[0])
    u.consume(4)
    assert u.used() == 4 and u.remaining() == 1
    month[0] = date(2026, 12, 1)
    assert u.used() == 0
    month[0] = date(2026, 11, 4)
    (tmp_path / "x" / "u.json").write_text("not json")
    assert u.used() == 5 and u.remaining() == 0  # corrupt file fails closed, never "0 used"


# ---------------------------------------------------------------------------
# Shared quota / cache hardening
# ---------------------------------------------------------------------------


def test_corrupt_usage_file_fails_closed_with_clear_message(tmp_path):
    path = tmp_path / "u.json"
    path.write_text("{ truncated")
    calls = []

    def h(req):
        calls.append(req)
        return httpx.Response(200, json=COMPANY)

    c = PdlClient(
        KEY,
        transport=httpx.MockTransport(h),
        usage=PdlUsageCounter(path, 100, today=lambda: date(2026, 11, 4)),
    )
    with pytest.raises(PdlQuotaExhaustedError) as exc:
        c.enrich_company("linear.app")
    assert "unreadable" in str(exc.value) and not calls
    assert path.read_text() == "{ truncated"  # never overwritten ("healed") silently
    assert PdlUsageCounter(path, 100).consume(1) == 100  # and consume does not rewrite it either


def test_usage_writes_are_atomic_with_unique_temp_files(tmp_path):
    import threading

    path = tmp_path / "u.json"
    u = PdlUsageCounter(path, 1000, today=lambda: date(2026, 11, 4))
    other = PdlUsageCounter(path, 1000, today=lambda: date(2026, 11, 4))  # a second instance on the same file
    threads = [threading.Thread(target=lambda c=c: [c.consume(1) for _ in range(25)]) for c in (u, other) * 2]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert u.used() == 100
    assert sorted(p.name for p in tmp_path.iterdir()) == ["u.json"]  # no stray .tmp files


def test_shared_usage_counter_is_one_instance_per_file(tmp_path):
    from dealscope.providers.pdl import shared_usage_counter

    a = shared_usage_counter(tmp_path / "s.json", 10)
    b = shared_usage_counter(tmp_path / "." / "s.json", 20)
    assert a is b and a.limit == 20


def test_per_case_cap_refuses_further_records(tmp_path):
    def h(req):
        return httpx.Response(200, json={"data": [person("a", [entry("linear.app", "CISO", "2020-01", "2021-01")])]})

    usage = PdlUsageCounter(tmp_path / "u.json", 100, today=lambda: date(2026, 11, 4))
    c = PdlClient(KEY, transport=httpx.MockTransport(h), usage=usage, max_records_per_case=2)
    c.case_id = "case-1"
    c.search_people("linear.app", "security", "past_target_employment", None, 10)
    c.search_people("linear.app", "security", "past_target_employment", None, 10)
    assert usage.case_used("case-1") == 2
    with pytest.raises(PdlQuotaExhaustedError) as exc:
        c.search_people("linear.app", "security", "past_target_employment", None, 10)
    assert "per-case" in str(exc.value)
    c.case_id = "case-2"  # another case still has its own allowance
    c.search_people("linear.app", "security", "past_target_employment", None, 10)
    assert usage.used() == 3


def test_identity_check_and_run_share_one_record_across_clients(tmp_path):
    """The API builds a fresh FreeDataSource for the identity check and another for the run: 1 record total."""
    from dealscope.config import Settings
    from dealscope.providers.free_source import FreeDataSource

    calls = []

    def h(req):
        calls.append(str(req.url))
        return httpx.Response(200, json=COMPANY)

    s = Settings(_env_file=None, pdl_api_key=KEY, pdl_usage_path=tmp_path / "usage.json")
    first = FreeDataSource.from_settings(s, pdl_transport=httpx.MockTransport(h))
    assert first.identify_company("linear.app").ok
    first.close()
    second = FreeDataSource.from_settings(s, pdl_transport=httpx.MockTransport(h))
    r = second.enrich_company("linear.app")
    second.close()
    assert r.items and len(calls) == 1
    assert (tmp_path / "usage.json").exists() and json.loads((tmp_path / "usage.json").read_text())["used"] == 1
