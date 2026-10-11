from datetime import date
from pathlib import Path

import pytest

from dealscope.domain.enums import EvidenceKind
from dealscope.domain.models import EvidenceRecord
from dealscope.providers.base import AuthError, DataSource, RetryExhaustedError, UnknownOutcomeError
from dealscope.providers.fixture import FixtureDataSource

FIX = Path(__file__).resolve().parent.parent / "fixtures"
T = "northstar-platform.example"
APEX, CEDAR, ORBIT = "apex-cloud.example", "cedar-stack.example", "orbit-data.example"
ALL_TERMS = ["engineering_leadership", "platform", "security", "data_ml", "reliability"]
SINCE = date(2026, 7, 13)


def src(name="scenario_a.json", **kw):
    return FixtureDataSource(FIX / name, **kw)


def test_protocol_and_banner():
    s = src()
    assert isinstance(s, DataSource) and s.provider_name == "fixture"
    assert "SYNTHETIC" in s.synthetic_banner and s.case["target_domain"] == T


def test_scenario_a_company_values():
    s = src()
    t = s.enrich_company(T)
    p = t.items[0].payload
    assert t.provider == "fixture" and t.credits_used is None and t.endpoint == "/company/enrich"
    assert p.total_growth_pct == {"6m": 11.0, "12m": 18.0}
    assert p.engineering_growth_pct == {"6m": -4.0, "12m": -2.0}
    assert t.items[0].independence_group == f"fixture:company_enrich:{T}"
    eng6 = {d: s.enrich_company(d).items[0].payload.engineering_growth_pct["6m"] for d in (APEX, CEDAR, ORBIT)}
    assert eng6 == {APEX: 7.0, CEDAR: 8.0, ORBIT: 3.0}
    unknown = s.enrich_company("nobody.example")
    assert unknown.items == [] and "no match" in unknown.notes


def test_scenario_b_has_no_trajectory_concern():
    p = src("scenario_b.json").enrich_company(T).items[0].payload
    assert p.engineering_growth_pct == {"6m": 12.0, "12m": 20.0}
    assert p.total_growth_pct == {"6m": 10.0, "12m": 17.0}


def test_items_convert_to_valid_evidence_records():
    s = src()
    res = s.enrich_company(T)
    item = res.items[0]
    rec = EvidenceRecord(
        case_id="c",
        kind=item.kind,
        subject_domain=item.subject_domain,
        source_provider="fixture",
        source_endpoint=res.endpoint,
        payload=item.payload,
        dedup_key=item.dedup_key,
        independence_group=item.independence_group,
        synthetic=True,
        raw_hash=item.raw_hash,
    )
    assert rec.kind == EvidenceKind.COMPANY_PROFILE and len(item.raw_hash) == 64


def test_people_past_filters_by_group_relationship_and_competitor():
    s = src()
    lead = s.search_people(T, "technical_leadership", "past_target_employment", None, 25)
    assert sorted(i.payload.person_ref for i in lead.items) == ["p-syn-a001", "p-syn-a005"]
    assert lead.request_body["limit"] == 25 and lead.endpoint == "/person/search"
    at_apex = s.search_people(T, "senior_technical_ic", "past_target_employment", APEX, 25)
    assert [i.payload.person_ref for i in at_apex.items] == ["p-syn-a002"]
    at_orbit = s.search_people(T, "data_ml", "past_target_employment", ORBIT, 25)
    assert [i.payload.person_ref for i in at_orbit.items] == ["p-syn-a003"]
    nothing = s.search_people(T, "security", "past_target_employment", None, 25)
    assert nothing.items == [] and "no match" in nothing.notes
    item = lead.items[0]
    assert item.independence_group.startswith("fixture:person:p-syn-a") and item.kind == EvidenceKind.PERSON_HISTORY
    assert item.dedup_key.startswith("person:p-syn-a001") or item.dedup_key.startswith("person:p-syn-a005")


def test_scenario_a_people_shape():
    s = src()
    past = [
        i
        for g in ("technical_leadership", "senior_technical_ic", "data_ml")
        for i in s.search_people(T, g, "past_target_employment", None, 100).items
    ]
    ended = [i for i in past if i.payload.target_end]
    assert len(ended) == 4 and all("2025-10" <= i.payload.target_end <= "2026-10" for i in ended)
    assert sum(1 for i in past if i.payload.target_end is None) == 1
    current = [
        i
        for g in ("technical_leadership", "senior_technical_ic", "data_ml", "security")
        for i in s.search_people(T, g, "current_target_employment", None, 100).items
    ]
    assert len(current) == 3 and {i.payload.capability for i in current} == {"platform_engineering", "data_ml"}
    assert all(i.payload.currently_at_target for i in current)


def test_scenario_b_people_are_incomplete():
    s = src("scenario_b.json")
    past = [
        i
        for g in ("technical_leadership", "senior_technical_ic", "data_ml")
        for i in s.search_people(T, g, "past_target_employment", None, 100).items
    ]
    assert (
        len(past) == 4 and sum(1 for i in past if i.payload.target_start is None and i.payload.target_end is None) == 3
    )
    cur = [
        i
        for g in ("technical_leadership", "senior_technical_ic", "data_ml")
        for i in s.search_people(T, g, "current_target_employment", None, 100).items
    ]
    assert len(cur) == 1


def test_people_limit_applied():
    s = src()
    res = s.search_people(T, "technical_leadership", "past_target_employment", None, 1)
    assert res.result_count == 1 and any("single page" in n for n in res.notes)


def test_jobs_filtering():
    s = src()
    res = s.search_jobs(T, ALL_TERMS, SINCE, 50)
    titles = [i.payload.title for i in res.items]
    assert len(titles) == 5
    dates = [i.payload.date_added for i in res.items]
    assert dates == sorted(dates, reverse=True)
    assert sum(1 for i in res.items if i.payload.reposted) == 2
    assert all(
        i.independence_group == f"fixture:job:{T}" and i.dedup_key.startswith("job:syn-job-a-") for i in res.items
    )
    only_sec = s.search_jobs(T, ["security"], SINCE, 50)
    assert {i.payload.title for i in only_sec.items} == {"Security Engineering Manager", "Head of Security"}
    recent = s.search_jobs(T, ALL_TERMS, date(2026, 9, 1), 50)
    assert len(recent.items) == 2
    limited = s.search_jobs(T, ALL_TERMS, SINCE, 2)
    assert limited.result_count == 2
    peer = s.search_jobs(CEDAR, ALL_TERMS, SINCE, 50)
    assert 1 <= peer.result_count <= 2
    assert s.search_jobs("nobody.example", ALL_TERMS, SINCE, 5).items == []


def test_scenario_b_single_ordinary_job():
    res = src("scenario_b.json").search_jobs(T, ALL_TERMS, SINCE, 50)
    assert [i.payload.title for i in res.items] == ["Backend Engineer"]


def test_legacy_synthetic_case_loads():
    s = src("synthetic_case.json")
    assert s.legacy
    t = s.enrich_company(T)
    p = t.items[0].payload
    assert p.total_headcount == 480 and p.total_growth_pct == {"6m": 11.0} and p.engineering_growth_pct == {"6m": -4.0}
    assert "legacy fixture format converted" in t.notes
    assert s.enrich_company(ORBIT).items[0].payload.engineering_growth_pct == {"6m": 3.0}
    people = s.search_people(T, "technical_leadership", "past_target_employment", APEX, 10)
    assert people.result_count == 1 and people.items[0].payload.target_end == "2026-05"
    jobs = s.search_jobs(T, ["platform"], SINCE, 10)
    assert jobs.items[0].payload.title == "Principal Platform Engineer" and jobs.items[0].payload.reposted is True


def test_fixture_data_is_deterministic():
    a = src().search_people(T, "technical_leadership", "past_target_employment", None, 25)
    b = src().search_people(T, "technical_leadership", "past_target_employment", None, 25)
    assert [i.raw_hash for i in a.items] == [i.raw_hash for i in b.items]


# --------------------------------------------------------------------------- fault injection


def test_faults_503_503_then_success_with_on_retry_called_twice():
    sleeps: list[float] = []
    events: list[tuple] = []
    s = src(faults={"enrich_company": [503, 503]}, sleep=sleeps.append, on_retry=lambda *a: events.append(a))
    res = s.enrich_company(T)
    assert res.attempts == 3 and res.result_count == 1
    assert len(events) == 2 and [e[0] for e in events] == [1, 2] and events[0][1] == "http_503"
    assert len(sleeps) == 2 and all(0 <= d <= 8 for d in sleeps)
    again = s.enrich_company(T)  # queue consumed
    assert again.attempts == 1


def test_faults_are_per_method():
    s = src(faults={"search_jobs": [503]}, sleep=lambda d: None)
    assert s.enrich_company(T).attempts == 1
    assert s.search_jobs(T, ALL_TERMS, SINCE, 5).attempts == 2


def test_fault_401_raises_auth_without_retry():
    sleeps: list[float] = []
    s = src(faults={"enrich_company": [401, 401]}, sleep=sleeps.append)
    with pytest.raises(AuthError) as ei:
        s.enrich_company(T)
    assert ei.value.attempts == 1 and sleeps == []


def test_fault_exhaustion_and_timeout():
    s = src(faults={"search_people": [503, 503, 503]}, sleep=lambda d: None)
    with pytest.raises(RetryExhaustedError):
        s.search_people(T, "security", "past_target_employment", None, 5)
    s2 = src(faults={"enrich_company": ["timeout"]}, sleep=lambda d: None)
    with pytest.raises(UnknownOutcomeError):
        s2.enrich_company(T)
    s3 = src(faults={"enrich_company": ["connect", "429"]}, sleep=lambda d: None)
    assert s3.enrich_company(T).attempts == 3


def test_caller_fault_dict_not_mutated():
    faults = {"enrich_company": [503]}
    src(faults=faults, sleep=lambda d: None).enrich_company(T)
    assert faults == {"enrich_company": [503]}
