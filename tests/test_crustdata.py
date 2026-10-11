import hashlib
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from dealscope.domain.enums import EvidenceKind
from dealscope.providers.base import (
    AuthError,
    BadRequestError,
    DataSource,
    InsufficientCreditsError,
    RetryExhaustedError,
    SchemaError,
    UnknownOutcomeError,
)
from dealscope.providers.crustdata import CrustdataClient, derive_engineering_growth

KEY = "sk-test-SECRET-123456"


def make_client(handler, **kw):
    sleeps: list[float] = []
    events: list[tuple] = []
    client = CrustdataClient(
        KEY,
        api_version="2025-11-01",
        base_url="https://api.crustdata.com",
        timeout_s=5,
        max_retries=kw.pop("max_retries", 2),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        on_retry=lambda *a: events.append(a),
        rng=lambda: 0.5,
        **kw,
    )
    return client, sleeps, events


def recorder(responses):
    """Handler that serves `responses` in order (last repeats) and records requests."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        step = responses[min(len(seen) - 1, len(responses) - 1)]
        if isinstance(step, Exception):
            raise step
        return step

    return handler, seen


def ok(payload, **headers):
    return httpx.Response(200, json=payload, headers=headers)


def err(status, message="boom", **headers):
    return httpx.Response(status, json={"error": {"type": "e", "message": message}}, headers=headers)


def ts(points):
    return [{"date": d + " 00:00:00", "employee_count": n} for d, n in points]


def enrich_payload(domain="serverobotics.com", **overrides):
    company = {
        "crustdata_company_id": 633593,
        "basic_info": {
            "name": "Serve Robotics",
            "primary_domain": domain,
            "all_domains": [domain],
            "industries": ["Robotics", "Delivery"],
        },
        "headcount": {
            "total": 381,
            "growth_percent": {"mom": 3.81, "qoq": 8.24, "six_months": 24.92, "yoy": 94.39, "two_years": 269.9, "x": 1},
            "growth_absolute": {"mom": 14},
            "by_function_timeseries": {
                "CURRENT_FUNCTION": {
                    "Accounting": ts([("2026-09-01", 4)]),
                    "Engineering": ts(
                        [("2025-09-01", 100), ("2026-03-01", 120), ("2026-06-01", 130), ("2026-09-01", 140)]
                    ),
                }
            },
            "by_role_absolute": {"engineering": 99},
        },
        "hiring": {"openings_count": 17},
        "funding": {"total_investment_usd": 123456789.5},
    }
    company.update(overrides)
    return [
        {"matched_on": domain, "match_type": "domain", "matches": [{"confidence_score": 1.0, "company_data": company}]}
    ]


# --------------------------------------------------------------------------- transport / headers


def test_protocol_conformance_and_headers_and_key_never_exposed():
    handler, seen = recorder([ok(enrich_payload(), **{"X-Credits-Used": "2", "X-Request-Id": "req-1"})])
    client, _, _ = make_client(handler)
    assert isinstance(client, DataSource)
    res = client.enrich_company("serverobotics.com")
    req = seen[0]
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["x-api-version"] == "2025-11-01"
    assert req.headers["content-type"] == "application/json"
    assert req.url == "https://api.crustdata.com/company/enrich"
    assert KEY not in repr(client) and KEY not in str(client)
    assert KEY not in json.dumps(res.request_body)
    assert res.credits_used == Decimal("2") and res.request_id == "req-1" and res.provider == "crustdata"


def test_error_messages_never_contain_key():
    handler, _ = recorder([err(401, f"Invalid API key {KEY}")])
    client, _, _ = make_client(handler)
    with pytest.raises(AuthError) as ei:
        client.enrich_company("serverobotics.com")
    assert KEY not in str(ei.value) and KEY not in repr(ei.value)


def test_blank_key_rejected():
    with pytest.raises(ValueError):
        CrustdataClient("", api_version="v", base_url="https://x", timeout_s=1, max_retries=0)


# --------------------------------------------------------------------------- enrich


def test_enrich_normalization():
    handler, seen = recorder([ok(enrich_payload())])
    client, _, _ = make_client(handler)
    res = client.enrich_company("https://www.serverobotics.com/about")
    body = json.loads(seen[0].content)
    assert body == {
        "domains": ["serverobotics.com"],
        "fields": ["basic_info", "headcount", "hiring", "funding"],
        "exact_match": True,
    }
    assert res.request_body == body and res.result_count == 1 and res.attempts == 1
    item = res.items[0]
    p = item.payload
    assert item.kind == EvidenceKind.COMPANY_PROFILE
    assert p.name == "Serve Robotics" and p.domain == "serverobotics.com" and p.total_headcount == 381
    assert p.total_growth_pct == {"1m": 3.81, "3m": 8.24, "6m": 24.92, "12m": 94.39, "24m": 269.9}
    assert p.engineering_headcount == 140
    assert p.engineering_growth_pct == {"3m": 7.69, "6m": 16.67, "12m": 40.0}
    assert p.job_openings_count == 17 and p.funding_total_usd == 123456789.5 and p.industry == "Robotics"
    assert "engineering series key used: 'Engineering' (by_function_timeseries.CURRENT_FUNCTION)" in res.notes
    assert "engineering growth derived from by_function_timeseries" in res.notes
    assert {"name", "domain", "total_headcount", "total_growth_pct", "engineering_growth_pct"} <= set(
        item.field_coverage
    )
    assert "hq_country" not in item.field_coverage
    assert item.dedup_key == "company:serverobotics.com"
    assert item.independence_group == "crustdata:company_enrich:serverobotics.com"
    assert len(item.raw_hash) == 64 and item.source_record_id == "633593"


def test_enrich_skips_null_growth_and_falls_back_to_by_role_absolute():
    data = enrich_payload()
    company = data[0]["matches"][0]["company_data"]
    company["headcount"]["growth_percent"] = {"mom": None, "six_months": 5.0}
    del company["headcount"]["by_function_timeseries"]
    client, _, _ = make_client(recorder([ok(data)])[0])
    res = client.enrich_company("serverobotics.com")
    p = res.items[0].payload
    assert p.total_growth_pct == {"6m": 5.0}
    assert p.engineering_headcount == 99 and p.engineering_growth_pct == {}
    assert any("by_role_absolute key 'engineering'" in n for n in res.notes)


def test_enrich_ignores_non_engineering_function_keys():
    data = enrich_payload()
    company = data[0]["matches"][0]["company_data"]
    company["headcount"]["by_function_timeseries"]["CURRENT_FUNCTION"] = {
        "Information Technology": ts([("2026-09-01", 9)])
    }
    company["headcount"]["by_role_absolute"] = {"Information Technology": 9}
    client, _, _ = make_client(recorder([ok(data)])[0])
    p = client.enrich_company("serverobotics.com").items[0].payload
    assert p.engineering_headcount is None and p.engineering_growth_pct == {}


def test_engineering_growth_needs_baseline_within_tolerance():
    from datetime import date as d

    pts = [(d(2026, 1, 1), 50), (d(2026, 9, 1), 100)]  # 6m target = 2026-03-01; 2026-01-01 is 59 days away
    assert derive_engineering_growth(pts) == {}
    pts = [(d(2026, 2, 1), 50), (d(2026, 9, 1), 100)]  # 28 days before target
    assert derive_engineering_growth(pts) == {"6m": 100.0}
    assert derive_engineering_growth([(d(2026, 3, 1), 0), (d(2026, 9, 1), 10)]) == {}  # base 0 skipped
    assert derive_engineering_growth([]) == {}


def test_enrich_no_match_returns_zero_items():
    empty = [{"matched_on": "nope.example", "match_type": "domain", "matches": []}]
    client, _, _ = make_client(recorder([ok(empty)])[0])
    res = client.enrich_company("nope.example")
    assert res.items == [] and res.result_count == 0 and "no match" in res.notes


def test_enrich_404_treated_as_no_match():
    client, _, _ = make_client(recorder([err(404, "not found")])[0])
    res = client.enrich_company("nope.example")
    assert res.items == [] and "no match" in res.notes


def test_enrich_primary_domain_mismatch_yields_no_item():
    client, _, _ = make_client(recorder([ok(enrich_payload(domain="other.com"))])[0])
    res = client.enrich_company("serverobotics.com")
    assert res.items == [] and any("mismatch" in n for n in res.notes)


def test_enrich_picks_highest_confidence_with_matching_domain():
    good = enrich_payload()[0]["matches"][0]
    good["confidence_score"] = 0.9
    other = enrich_payload(domain="serverobotics.com")[0]["matches"][0]
    other["confidence_score"] = 0.5
    other["company_data"]["basic_info"]["name"] = "Wrong"
    data = [{"matched_on": "serverobotics.com", "matches": [other, good]}]
    client, _, _ = make_client(recorder([ok(data)])[0])
    assert client.enrich_company("serverobotics.com").items[0].payload.name == "Serve Robotics"


def test_invalid_domain_rejected_before_any_request():
    handler, seen = recorder([ok([])])
    client, _, _ = make_client(handler)
    with pytest.raises(BadRequestError):
        client.enrich_company("http://127.0.0.1")
    assert seen == []


# --------------------------------------------------------------------------- failure modes (T06/T07)


def test_t06_503_503_200_succeeds_with_three_attempts():
    handler, seen = recorder([err(503), err(503), ok(enrich_payload())])
    client, sleeps, events = make_client(handler)
    res = client.enrich_company("serverobotics.com")
    assert res.attempts == 3 and len(seen) == 3 and res.result_count == 1
    assert len(sleeps) == 2 and all(0 <= s <= 8 for s in sleeps)
    assert [e[0] for e in events] == [1, 2]


def test_429_reset_header_honored_and_capped():
    handler, seen = recorder([err(429, **{"x-ratelimit-reset": "120"}), ok(enrich_payload())])
    client, sleeps, _ = make_client(handler)
    assert client.enrich_company("serverobotics.com").attempts == 2
    assert sleeps == [8.0]


def test_three_503_exhaust_with_exactly_three_sends():
    handler, seen = recorder([err(503, "upstream down")])
    client, _, _ = make_client(handler)
    with pytest.raises(RetryExhaustedError) as ei:
        client.enrich_company("serverobotics.com")
    assert len(seen) == 3 and ei.value.attempts == 3 and "upstream down" in str(ei.value)


def test_job_search_500_preserves_message_after_retries():
    handler, seen = recorder([err(500, "Unsupported columns in conditions: ['x']")])
    client, _, _ = make_client(handler)
    with pytest.raises(RetryExhaustedError) as ei:
        client.search_jobs("a.example", ["platform"], date(2026, 7, 13), 10)
    assert "Unsupported columns" in str(ei.value) and len(seen) == 3


def test_t07_401_single_send_auth_error():
    handler, seen = recorder([err(401, "Invalid API key in request.")])
    client, sleeps, _ = make_client(handler)
    with pytest.raises(AuthError) as ei:
        client.enrich_company("serverobotics.com")
    assert len(seen) == 1 and sleeps == [] and ei.value.code == "AUTH" and ei.value.status == 401


def test_403_is_permission_error_without_retry():
    handler, seen = recorder([err(403, "Access denied to fields: hiring.recent_openings")])
    client, _, _ = make_client(handler)
    with pytest.raises(AuthError) as ei:
        client.enrich_company("serverobotics.com")
    assert ei.value.code == "PERMISSION" and len(seen) == 1


def test_402_insufficient_credits_no_retry():
    handler, seen = recorder([err(402, "insufficient_credits")])
    client, _, _ = make_client(handler)
    with pytest.raises(InsufficientCreditsError):
        client.enrich_company("serverobotics.com")
    assert len(seen) == 1


def test_400_no_retry():
    handler, seen = recorder([err(400, "Exactly one identifier must be provided")])
    client, _, _ = make_client(handler)
    with pytest.raises(BadRequestError):
        client.enrich_company("serverobotics.com")
    assert len(seen) == 1


def test_read_timeout_unknown_outcome_single_send():
    handler, seen = recorder([httpx.ReadTimeout("slow")])
    client, sleeps, _ = make_client(handler)
    with pytest.raises(UnknownOutcomeError) as ei:
        client.enrich_company("serverobotics.com")
    assert len(seen) == 1 and sleeps == [] and ei.value.billable_unknown is True


def test_connect_error_is_retried():
    handler, seen = recorder([httpx.ConnectError("refused"), ok(enrich_payload())])
    client, _, _ = make_client(handler)
    assert client.enrich_company("serverobotics.com").attempts == 2


@pytest.mark.parametrize(
    "bad_response",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, json={"unexpected": "object"}),
        httpx.Response(200, json=[{"matches": "nope"}]),
        httpx.Response(200, json=[{"matches": [{"confidence_score": 1, "company_data": "x"}]}]),
    ],
)
def test_enrich_schema_errors(bad_response):
    client, _, _ = make_client(recorder([bad_response])[0])
    with pytest.raises(SchemaError):
        client.enrich_company("serverobotics.com")


# --------------------------------------------------------------------------- people


def person_profile(pid=14540, target="northstar.example", title="VP Engineering", end="2026-05-01", with_current=True):
    return {
        "crustdata_person_id": pid,
        "experience": {
            "employment_details": {
                "current": [
                    {
                        "name": "Apex Cloud",
                        "title": "SVP Engineering",
                        "company_website": "https://www.apex-cloud.example/",
                        "start_date": "2026-06-01",
                    }
                ]
                if with_current
                else [],
                "past": [
                    {
                        "name": "Old Co",
                        "title": "Engineer",
                        "company_website": "https://old.example",
                        "end_date": "2019-01-01",
                    },
                    {
                        "name": "Northstar",
                        "title": title,
                        "company_website": f"https://{target}",
                        "start_date": "2021-03-01",
                        "end_date": end,
                        "seniority_level": "Vice President",
                    },
                ],
            }
        },
    }


def people_client(profiles, total=None, **headers):
    body = {"profiles": profiles, "next_cursor": None, "total_count": total if total is not None else len(profiles)}
    handler, seen = recorder([ok(body, **headers)])
    client, _, _ = make_client(handler)
    return client, seen


def test_person_search_body_past_with_competitor():
    client, seen = people_client([])
    res = client.search_people(
        "Northstar.example", "technical_leadership", "past_target_employment", "apex-cloud.example", 500
    )
    body = json.loads(seen[0].content)
    assert res.request_body == body and res.endpoint == "/person/search" and "no match" in res.notes
    assert body["fields"] == [
        "crustdata_person_id",
        "experience.employment_details.current",
        "experience.employment_details.past",
    ]
    assert not any("contact" in f or "basic_profile" in f or "social" in f for f in body["fields"])
    assert body["limit"] == 100 and body["sorts"] == [{"field": "crustdata_person_id", "order": "asc"}]
    assert "cursor" not in body
    flt = body["filters"]
    assert flt["op"] == "all_of"
    same_entry, competitor = flt["conditions"]
    assert same_entry["op"] == "and"
    assert same_entry["conditions"][0] == {
        "field": "experience.employment_details.past.company_website_domain",
        "type": "=",
        "value": "northstar.example",
    }
    titles = same_entry["conditions"][1]["conditions"]
    assert {c["field"] for c in titles} == {"experience.employment_details.past.title"}
    assert {c["type"] for c in titles} == {"[.]"}
    assert {"CTO", "VP Engineering", "Chief Architect"} <= {c["value"] for c in titles}
    assert competitor == {
        "field": "experience.employment_details.current.company_website_domain",
        "type": "=",
        "value": "apex-cloud.example",
    }


def test_person_search_body_current_uses_current_paths_and_no_competitor():
    client, seen = people_client([])
    client.search_people("northstar.example", "security", "current_target_employment", None, 0)
    body = json.loads(seen[0].content)
    assert body["limit"] == 1
    assert len(body["filters"]["conditions"]) == 1
    text = json.dumps(body["filters"])
    assert "employment_details.current.company_website_domain" in text and ".past." not in text
    assert "CISO" in text


def test_person_search_rejects_unknown_group_or_relationship():
    client, seen = people_client([])
    with pytest.raises(BadRequestError):
        client.search_people("a.example", "executives", "past_target_employment", None, 5)
    with pytest.raises(BadRequestError):
        client.search_people("a.example", "security", "friends", None, 5)
    assert seen == []


def test_person_normalization_past():
    client, _ = people_client([person_profile()], total=3, **{"X-Credits-Used": "0.23"})
    res = client.search_people("northstar.example", "technical_leadership", "past_target_employment", None, 25)
    item = res.items[0]
    p = item.payload
    expected_ref = "p-" + hashlib.sha256(b"crustdata:14540").hexdigest()[:16]
    assert p.person_ref == expected_ref
    assert p.role_group == "technical_leadership" and p.title_at_target == "VP Engineering"
    assert p.seniority == "Vice President" and p.target_start == "2021-03-01" and p.target_end == "2026-05-01"
    assert p.currently_at_target is False
    assert p.current_employer_name == "Apex Cloud" and p.current_employer_domain == "apex-cloud.example"
    assert p.current_title == "SVP Engineering"
    assert item.subject_domain == "northstar.example" and item.source_url is None
    assert item.valid_from == "2021-03-01" and item.valid_to == "2026-05-01"
    assert item.independence_group == f"crustdata:person:{expected_ref}"
    assert item.dedup_key.startswith(f"person:{expected_ref}")
    assert res.credits_used == Decimal("0.23")
    assert any("single page only" in n for n in res.notes)
    dumped = json.dumps(p.model_dump())
    assert "Old Co" not in dumped


def test_person_normalization_current_has_no_end():
    prof = person_profile(with_current=False)
    prof["experience"]["employment_details"]["current"] = [
        {
            "name": "Northstar",
            "title": "Staff Platform Engineer",
            "company_website": "https://northstar.example",
            "start_date": "2022-02-01",
        }
    ]
    prof["experience"]["employment_details"]["past"] = []
    client, _ = people_client([prof])
    res = client.search_people("northstar.example", "senior_technical_ic", "current_target_employment", None, 25)
    p = res.items[0].payload
    assert p.currently_at_target is True and p.target_end is None and p.target_start == "2022-02-01"
    assert p.role_group == "senior_technical_ic" and p.capability == "platform_engineering"
    assert p.current_employer_domain == "northstar.example"


def test_person_missing_end_date_kept_as_none():
    client, _ = people_client([person_profile(end=None)])
    res = client.search_people("northstar.example", "technical_leadership", "past_target_employment", None, 25)
    assert res.items[0].payload.target_end is None
    assert "target_end" not in res.items[0].field_coverage


def test_profiles_without_target_entry_are_skipped_not_invented():
    client, _ = people_client([person_profile(target="elsewhere.example"), person_profile(pid=2)])
    res = client.search_people("northstar.example", "technical_leadership", "past_target_employment", None, 25)
    assert res.result_count == 1
    assert any("1 profile(s) skipped" in n for n in res.notes)


def test_people_schema_error():
    client, _ = None, None
    handler, _ = recorder([ok({"nothing": []})])
    client, _, _ = make_client(handler)
    with pytest.raises(SchemaError):
        client.search_people("a.example", "security", "past_target_employment", None, 5)


# --------------------------------------------------------------------------- jobs


def job_listing(jid=41053563, title="Principal Platform Engineer", **kw):
    return {
        "crustdata_job_id": jid,
        "job_details": {
            "title": title,
            "category": "Engineering",
            "url": "https://jobs.example/1",
            "reposted_job": True,
            "number_of_openings": 2,
        },
        "metadata": {"date_added": "2026-08-01T11:37:29", "date_updated": "2026-09-20T01:02:03"},
        **kw,
    }


def test_job_search_body_and_normalization():
    body = {
        "job_listings": [job_listing(), job_listing(), job_listing(jid=2, title="Head of Security")],
        "total_count": 3,
    }
    handler, seen = recorder([ok(body, **{"X-Credits-Used": "0.09"})])
    client, _, _ = make_client(handler)
    res = client.search_jobs("Northstar.example", ["platform", "security"], date(2026, 7, 13), 500)
    sent = json.loads(seen[0].content)
    assert res.request_body == sent and sent["limit"] == 50
    conds = sent["filters"]["conditions"]
    assert conds[0] == {"field": "company.basic_info.primary_domain", "type": "=", "value": "northstar.example"}
    assert conds[1] == {"field": "job_details.category", "type": "=", "value": "Engineering"}
    assert conds[2] == {"field": "metadata.date_added", "type": "=>", "value": "2026-07-13"}
    assert conds[3]["op"] == "or"
    assert {"platform engineer", "security engineer", "security"} <= {c["value"] for c in conds[3]["conditions"]}
    assert {c["type"] for c in conds[3]["conditions"]} == {"(.)"}
    assert sent["sorts"] == [{"field": "metadata.date_added", "order": "desc"}]
    assert "job_details.reposted_job" in sent["fields"] and "metadata.date_updated" in sent["fields"]

    assert res.result_count == 2  # duplicate crustdata_job_id collapsed
    first = res.items[0]
    p = first.payload
    assert p.title == "Principal Platform Engineer" and p.role_group == "senior_technical_ic"
    assert p.capability == "platform_engineering" and p.reposted is True and p.number_of_openings == 2
    assert p.date_added == "2026-08-01" and p.date_updated == "2026-09-20" and p.category == "Engineering"
    assert first.dedup_key == "job:41053563" and first.independence_group == "crustdata:job:northstar.example"
    assert first.source_url == "https://jobs.example/1" and first.valid_from == "2026-08-01"
    assert res.items[1].payload.role_group == "security"
    assert res.credits_used == Decimal("0.09")


def test_job_search_limit_floor_and_bad_terms():
    handler, seen = recorder([ok({"job_listings": []})])
    client, _, _ = make_client(handler)
    res = client.search_jobs("a.example", ["reliability"], date(2026, 7, 13), 0)
    assert json.loads(seen[0].content)["limit"] == 1 and "no match" in res.notes
    with pytest.raises(BadRequestError):
        client.search_jobs("a.example", ["bogus"], date(2026, 7, 13), 5)
    with pytest.raises(BadRequestError):
        client.search_jobs("a.example", [], date(2026, 7, 13), 5)
    assert len(seen) == 1


def test_job_dedup_key_fallbacks_and_missing_title_skipped():
    no_id = job_listing()
    del no_id["crustdata_job_id"]
    no_url = job_listing(jid=None, title="Staff SRE")
    del no_url["crustdata_job_id"]
    no_url["job_details"]["url"] = None
    untitled = job_listing(jid=9)
    untitled["job_details"]["title"] = None
    handler, _ = recorder([ok({"job_listings": [no_id, no_url, untitled]})])
    client, _, _ = make_client(handler)
    res = client.search_jobs("a.example", ["platform", "reliability"], date(2026, 7, 13), 10)
    assert [i.dedup_key for i in res.items] == ["job:https://jobs.example/1", "job:Staff SRE|2026-08-01"]


def test_job_schema_error():
    handler, _ = recorder([ok({"job_listings": None})])
    client, _, _ = make_client(handler)
    with pytest.raises(SchemaError):
        client.search_jobs("a.example", ["platform"], date(2026, 7, 13), 5)


# --------------------------------------------------------------------------- free helpers


def test_account_helpers():
    handler, seen = recorder(
        [ok({"account": {"credits": 9406.5}}), ok({"endpoints": [{"path": "/company/enrich", "base_credits": 2}]})]
    )
    client, _, _ = make_client(handler)
    assert client.account_credits()["account"]["credits"] == 9406.5
    assert client.endpoint_pricing("/company/enrich")["endpoints"][0]["base_credits"] == 2
    assert seen[0].method == "GET" and seen[0].url.path == "/account/credits"
    assert seen[1].url.path == "/account/endpoints" and seen[1].url.params["path"] == "/company/enrich"
    with pytest.raises(BadRequestError):
        client.endpoint_pricing("../etc/passwd")
