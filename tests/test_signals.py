from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from dealscope import SIGNAL_SCORING_VERSION
from dealscope.analysis.signals import (
    SIGNAL_WEIGHTS,
    build_scorecard,
    compute_scorecard,
    coverage_label_for,
    risk_band_for,
    score_s1,
    score_s2,
    score_s3,
    score_s4,
    score_s5,
)
from dealscope.domain.enums import EvidenceKind, SignalId, SignalState
from dealscope.domain.models import (
    CaseInput,
    CompanyProfilePayload,
    EvidenceRecord,
    JobPostingPayload,
    PersonHistoryPayload,
    SignalResult,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_case.json"
AS_OF = date(2026, 10, 11)
TARGET = "northstar-platform.example"


# ---------------------------------------------------------------------------
# Helpers: fixture JSON -> EvidenceRecords
# ---------------------------------------------------------------------------


def _record(kind: EvidenceKind, domain: str, payload, ev_id: str, group: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=ev_id,
        case_id="demo-case-001",
        kind=kind,
        subject_domain=domain,
        source_provider="fixture",
        source_endpoint="fixture",
        retrieved_at=datetime.fromisoformat("2026-10-11T10:00:00+05:30"),
        payload=payload,
        dedup_key=ev_id,
        independence_group=group or f"fixture:{ev_id}",
        synthetic=True,
    )


def load_fixture(
    *, eng_growth: float | None = -4.0, drop_dept: bool = False, drop_dates: bool = False
) -> tuple[CaseInput, list[EvidenceRecord]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    c = data["case"]
    case = CaseInput(
        target_domain=c["target_domain"],
        competitor_domains=c["competitor_domains"],
        deal_thesis=c["deal_thesis"],
        lookback_months=c["lookback_months"],
    )
    out: list[EvidenceRecord] = []
    for e in data["evidence"]:
        n, kind = e["normalized_payload"], e["kind"]
        if kind in ("company_headcount", "peer_headcount"):
            is_target = kind == "company_headcount"
            eng = n.get("engineering_growth_6m_pct")
            if is_target and eng_growth is not None:
                eng = eng_growth
            payload = CompanyProfilePayload(
                domain=e["subject_domain"],
                total_headcount=n.get("total_headcount"),
                total_growth_pct={"6m": n["total_growth_6m_pct"]},
                engineering_growth_pct={} if (drop_dept and is_target) or eng is None else {"6m": eng},
            )
            out.append(_record(EvidenceKind.COMPANY_PROFILE, e["subject_domain"], payload, e["evidence_id"]))
        elif kind == "job_posting":
            # Classification (role group / capability) is the normalizer's job; set it explicitly here.
            payload = JobPostingPayload(
                title=n["title"],
                role_group="senior_technical_ic",
                capability="platform_engineering",
                reposted=n["reposted"],
                number_of_openings=n["number_of_openings"],
                date_added=n["date_added"],
            )
            out.append(_record(EvidenceKind.JOB_POSTING, e["subject_domain"], payload, e["evidence_id"]))
        elif kind == "person_history":
            payload = PersonHistoryPayload(
                person_ref="p-" + e["evidence_id"],
                role_group=n["role_group"],
                target_end=None if drop_dates else n["employment_end_month"],
                current_employer_domain=n["current_employer_domain"],
            )
            out.append(_record(EvidenceKind.PERSON_HISTORY, e["subject_domain"], payload, e["evidence_id"]))
    return case, out


def person(
    ref: str,
    role: str = "technical_leadership",
    *,
    end: str | None = None,
    start: str | None = "2020-01",
    at_target: bool | None = None,
    employer: str | None = None,
    cap: str = "general_engineering",
    ev_id: str | None = None,
    group: str = "crustdata:people",
) -> EvidenceRecord:
    payload = PersonHistoryPayload(
        person_ref=ref,
        role_group=role,
        capability=cap,
        target_start=start,
        target_end=end,
        currently_at_target=at_target,
        current_employer_domain=employer,
    )
    return _record(EvidenceKind.PERSON_HISTORY, TARGET, payload, ev_id or f"ev-{ref}-{end}-{at_target}", group)


def job(
    title: str,
    *,
    role: str = "senior_technical_ic",
    cap: str = "platform_engineering",
    n: int | None = 1,
    reposted: bool | None = False,
    added: str | None = "2026-09-20",
    url: str | None = None,
) -> EvidenceRecord:
    payload = JobPostingPayload(
        title=title,
        role_group=role,
        capability=cap,
        number_of_openings=n,
        reposted=reposted,
        date_added=added,
        url=url,
    )
    return _record(EvidenceKind.JOB_POSTING, TARGET, payload, f"ev-job-{title}-{added}-{url}", "crustdata:jobs")


def by_id(sc, sid: SignalId) -> SignalResult:
    return next(s for s in sc.signals if s.signal_id == sid)


def set_target(ev: list[EvidenceRecord], **update) -> None:
    tgt = next(e for e in ev if e.evidence_id == "ev-syn-001")
    tgt.payload = tgt.payload.model_copy(update=update)


# ---------------------------------------------------------------------------
# Determinism / version / structure
# ---------------------------------------------------------------------------


def test_determinism_same_input_identical_scorecard():
    case, ev = load_fixture()
    a = compute_scorecard(case, ev, AS_OF)
    b = compute_scorecard(case, list(ev), AS_OF)
    assert a.model_dump() == b.model_dump()
    # as_of derived from evidence (no wall clock) is also stable
    assert compute_scorecard(case, ev).model_dump() == compute_scorecard(case, ev).model_dump()


def test_scorecard_structure_version_and_weights():
    case, ev = load_fixture()
    sc = compute_scorecard(case, ev)
    assert sc.signal_version == SIGNAL_SCORING_VERSION
    assert [s.signal_id for s in sc.signals] == list(SignalId)
    assert all(s.signal_version == SIGNAL_SCORING_VERSION for s in sc.signals)
    assert sum(SIGNAL_WEIGHTS.values()) == pytest.approx(1.0)
    assert all(s.weight == SIGNAL_WEIGHTS[s.signal_id] for s in sc.signals)
    assert 0 <= sc.evidence_confidence <= 100


def test_synthetic_limitation_and_evidence_ids_present():
    case, ev = load_fixture()
    sc = compute_scorecard(case, ev)
    known = {e.evidence_id for e in ev}
    for s in sc.signals:
        assert "synthetic fixture data" in s.limitations
        assert set(s.evidence_ids) <= known
        assert 0 <= s.confidence <= 100
        if s.state != SignalState.NOT_SCORED:
            assert s.evidence_ids


# ---------------------------------------------------------------------------
# S1
# ---------------------------------------------------------------------------


def test_s1_fixture_lands_in_41_60_band():
    case, ev = load_fixture()
    s1 = score_s1(case, ev, AS_OF)
    assert s1.state == SignalState.SCORABLE
    assert s1.score is not None and 41 <= s1.score <= 60
    assert s1.raw_measure["tech_growth_6m"] == -4.0
    assert s1.raw_measure["total_growth_6m"] == 11.0
    assert s1.raw_measure["tech_vs_total_gap_6m"] == -15.0
    assert s1.benchmark["6m"]["stats"]["median"] == 7.0  # type: ignore[index]
    assert {"ev-syn-001", "ev-syn-004", "ev-syn-005", "ev-syn-006"} <= set(s1.evidence_ids)


def test_s1_single_period_has_no_trend_language():
    case, ev = load_fixture()
    s1 = score_s1(case, ev, AS_OF)
    assert "SINGLE_PERIOD" in s1.reason_codes
    assert "single returned period; no trend inferred" in s1.limitations
    text = " ".join([*s1.reason_codes, str(s1.raw_measure["summary"])]).lower()
    for word in ("trend", "sustained", "spike", "over time"):
        assert word not in text


def test_s1_changes_when_target_engineering_growth_is_plus_12():
    case, ev = load_fixture()
    high = score_s1(case, ev, AS_OF).score
    case2, ev2 = load_fixture(eng_growth=12.0)
    s1 = score_s1(case2, ev2, AS_OF)
    assert s1.score is not None and high is not None
    assert s1.score <= 20 < 41 <= high
    assert s1.score < high


def test_s1_not_scored_without_department_data():
    case, ev = load_fixture(drop_dept=True)
    s1 = score_s1(case, ev, AS_OF)
    assert s1.state == SignalState.NOT_SCORED and s1.score is None
    assert "NO_DEPARTMENT_DATA" in s1.reason_codes
    assert any("not proof" in lim for lim in s1.limitations)
    assert s1.raw_measure["total_growth_pct"] == {"6m": 11.0}  # overall growth only as context


def test_s1_requires_identical_period():
    case, ev = load_fixture()
    set_target(ev, engineering_growth_pct={"12m": -4.0})
    s1 = score_s1(case, ev, AS_OF)
    assert s1.state == SignalState.NOT_SCORED
    assert "NO_SHARED_PERIOD" in s1.reason_codes


def test_s1_weak_benchmark_with_two_peers_lowers_confidence():
    case, ev = load_fixture()
    full = score_s1(case, ev, AS_OF)
    two = score_s1(case, [e for e in ev if e.evidence_id != "ev-syn-006"], AS_OF)
    assert "PEER_BENCHMARK_WEAK" in two.reason_codes
    assert two.confidence < full.confidence
    assert two.confidence_breakdown["peer_comparability"] < full.confidence_breakdown["peer_comparability"]


def test_s1_multi_period_contraction_scores_61_to_80_and_81_needs_corroboration():
    case, ev = load_fixture()
    set_target(
        ev,
        total_growth_pct={"6m": 11.0, "12m": 15.0},
        engineering_growth_pct={"6m": -4.0, "12m": -6.0},
    )
    s1 = score_s1(case, ev, AS_OF)
    assert s1.score is not None and 61 <= s1.score <= 80
    assert "MULTI_PERIOD_TECH_CONTRACTION" in s1.reason_codes
    # add independent supporting evidence (3 critical openings) -> 81+ allowed
    extra = [job(f"Platform Engineer {i}", added=f"2026-09-{10 + i}") for i in range(3)]
    s1b = score_s1(case, [*ev, *extra], AS_OF)
    assert s1b.score is not None and s1b.score >= 81
    assert "CORROBORATED_BY_CRITICAL_VACANCIES" in s1b.reason_codes


def test_s1_never_81_from_one_period_percentage_alone():
    case, ev = load_fixture(eng_growth=-60.0)
    s1 = score_s1(case, ev, AS_OF)
    assert s1.score is not None and s1.score <= 60


# ---------------------------------------------------------------------------
# S2
# ---------------------------------------------------------------------------


def test_s2_counts_departure_in_window_low_coverage_for_one_profile():
    case, ev = load_fixture()
    s2 = score_s2(case, ev, AS_OF)
    assert s2.state == SignalState.LOW_COVERAGE and s2.score is not None
    assert "DEPARTURES_IN_WINDOW_1" in s2.reason_codes
    assert s2.raw_measure["observed_eligible_profiles"] == 1
    assert "1 of 1 observed" in str(s2.raw_measure["summary"])
    assert "attrition rate" in str(s2.raw_measure["summary"])


def test_s2_missing_target_end_is_not_a_departure():
    case, _ = load_fixture()
    ev = [
        person("a", end=None, at_target=None),
        person("b", end=None, start="2019-05"),
        person("c", end=None, at_target=True),
    ]
    s2 = score_s2(case, ev, AS_OF)
    assert s2.raw_measure["departures_in_window"] == 0
    assert "NO_DEPARTURES_OBSERVED" in s2.reason_codes
    assert "MISSING_END_DATE_NOT_COUNTED" in s2.reason_codes
    assert s2.score is not None and s2.score < 25


def test_s2_distinct_people_dedupe_and_window():
    case, _ = load_fixture()
    ev = [
        person("a", end="2026-05", ev_id="e1"),
        person("a", end="2026-05", ev_id="e2"),  # same person, duplicate profile event
        person("b", "security", end="2026-03", ev_id="e3"),
        person("c", "senior_technical_ic", end="2024-01", ev_id="e4"),  # before window
        person("d", "other_technical", end="2026-04", ev_id="e5"),  # not a critical role group
        person("e", end="2027-01", ev_id="e6"),  # after as_of: not a departure
    ]
    s2 = score_s2(case, ev, AS_OF)
    assert s2.raw_measure["departures_in_window"] == 2
    assert s2.raw_measure["observed_eligible_profiles"] == 4  # a, b, c, e
    assert "DEPARTURES_IN_WINDOW_2" in s2.reason_codes
    assert "DUPLICATE_PROFILES_MERGED" in s2.reason_codes
    assert {d["person_ref"] for d in s2.raw_measure["departed"]} == {"a", "b"}  # type: ignore[union-attr]


def test_s2_more_departures_score_higher_and_seniority_weighted():
    case, _ = load_fixture()

    def run(role: str, n: int) -> float:
        ev = [person(f"p{i}", role, end="2026-04") for i in range(n)] + [person("stay", at_target=True)]
        return score_s2(case, ev, AS_OF).score or 0.0

    assert run("technical_leadership", 3) > run("technical_leadership", 1)
    assert run("technical_leadership", 2) > run("senior_technical_ic", 2)


def test_s2_not_scored_without_person_or_dates():
    case, ev = load_fixture()
    no_people = score_s2(case, [e for e in ev if e.kind != EvidenceKind.PERSON_HISTORY], AS_OF)
    assert no_people.reason_codes == ["NO_PERSON_DATA"]
    case2, ev2 = load_fixture(drop_dates=True)
    s2 = score_s2(case2, ev2, AS_OF)
    assert s2.state == SignalState.NOT_SCORED and s2.score is None
    assert "NO_DATED_EMPLOYMENT" in s2.reason_codes


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def test_s3_matrix_statuses_and_gap_rule():
    case, _ = load_fixture()
    ev = [
        person("lead1", cap="platform_engineering", at_target=True, end=None),
        person("lead2", cap="platform_engineering", at_target=True, end=None),
        person("sec-gone", "security", cap="security", end="2026-04"),
        job("Head of Security", role="security", cap="security"),
        job("ML Engineer", role="data_ml", cap="data_ml"),
    ]
    s3 = score_s3(case, ev, AS_OF)
    rows = {r["capability"]: r for r in s3.raw_measure["capability_matrix"]}  # type: ignore[union-attr]
    assert rows["platform_engineering"]["status"] == "observed"
    assert rows["security"]["status"] == "open_role_only"
    assert rows["security"]["departures_in_window"] == 1
    assert rows["data_ml"]["status"] == "open_role_only"
    assert rows["reliability"]["status"] == "no_data"
    assert s3.score is not None and s3.score >= 61  # open roles + departure + no observed coverage
    assert s3.state == SignalState.LOW_COVERAGE


def test_s3_all_no_data_is_not_scored_and_no_profile_is_not_a_gap():
    case, ev = load_fixture()
    ev = [e for e in ev if e.kind != EvidenceKind.JOB_POSTING]  # person records carry no critical capability tag
    s3 = score_s3(case, ev, AS_OF)
    assert s3.state == SignalState.NOT_SCORED and s3.score is None
    assert "ALL_CAPABILITIES_NO_DATA" in s3.reason_codes
    assert all(r["status"] == "no_data" for r in s3.raw_measure["capability_matrix"])  # type: ignore[union-attr]


def test_s3_conflicting_records_flagged():
    case, _ = load_fixture()
    ev = [
        person("x", cap="security", at_target=True, ev_id="c1"),
        person("x", cap="security", end="2026-02", ev_id="c2"),
    ]
    s3 = score_s3(case, ev, AS_OF)
    rows = {r["capability"]: r for r in s3.raw_measure["capability_matrix"]}  # type: ignore[union-attr]
    assert rows["security"]["status"] == "conflicting"
    assert s3.state == SignalState.CONFLICTING and s3.score is None


# ---------------------------------------------------------------------------
# S4
# ---------------------------------------------------------------------------


def test_s4_no_job_data_is_not_scored_not_zero():
    case, ev = load_fixture()
    s4 = score_s4(case, [e for e in ev if e.kind != EvidenceKind.JOB_POSTING], AS_OF)
    assert s4.state == SignalState.NOT_SCORED and s4.score is None
    assert s4.reason_codes == ["NO_JOB_DATA"]
    assert any("no hiring" in lim for lim in s4.limitations)


def test_s4_fixture_low_band_with_reposted_role():
    case, ev = load_fixture()
    s4 = score_s4(case, ev, AS_OF)
    assert s4.state == SignalState.SCORABLE
    assert s4.raw_measure["critical_openings_count"] == 1
    assert s4.raw_measure["reposted_critical_postings"] == 1
    assert s4.raw_measure["critical_posting_share"] == pytest.approx(1 / 480, abs=1e-4)
    assert s4.score is not None and s4.score <= 20


def test_s4_dedupes_postings_and_sums_openings():
    case, _ = load_fixture()
    ev = [
        job("Staff SRE", url="https://x.example/j/1", n=2),
        job("Staff SRE (dup)", url="https://x.example/j/1", n=2, added="2026-09-21"),  # same URL
        job("Security Lead", role="security", cap="security", n=None, added="2026-09-01"),
        job("Security Lead", role="security", cap="security", n=None, added="2026-09-01", url=None),  # dup
        job("Office Manager", role="non_technical", cap="other"),
    ]
    # the second Security Lead has an identical id -> make it distinct but keep title+date identical
    ev[3] = ev[3].model_copy(update={"evidence_id": "ev-job-security-dup"})
    s4 = score_s4(case, ev, AS_OF)
    assert s4.raw_measure["critical_openings_count"] == 3  # 2 + 1 (None -> 1); non_technical excluded
    assert s4.raw_measure["duplicate_records_removed"] == 2
    assert s4.raw_measure["critical_posting_share"] is None  # no target profile -> no denominator
    assert "NO_HEADCOUNT_DENOMINATOR" in s4.reason_codes


def test_s4_61_plus_requires_corroboration():
    cluster = [job(f"Eng {i}", added=f"2026-09-{10 + i}") for i in range(4)]
    # no S1 concern (eng +12%) and no people evidence -> no corroboration
    case, ev = load_fixture(eng_growth=12.0)
    base = [e for e in ev if e.kind not in (EvidenceKind.JOB_POSTING, EvidenceKind.PERSON_HISTORY)]
    s4a = score_s4(case, [*base, *cluster], AS_OF)
    assert s4a.score is not None and s4a.score < 61
    # fixture S1 concern (-4% engineering) + job cluster -> corroborated
    case2, ev2 = load_fixture()
    ev2 = [e for e in ev2 if e.kind != EvidenceKind.JOB_POSTING] + cluster
    s4b = score_s4(case2, ev2, AS_OF)
    assert s4b.score is not None and 61 <= s4b.score <= 80
    assert "CORROBORATED_BY_ENGINEERING_CONTRACTION_SIGNAL" in s4b.reason_codes


# ---------------------------------------------------------------------------
# S5
# ---------------------------------------------------------------------------


def test_s5_competitor_match_counts_and_non_competitor_ignored():
    case, _ = load_fixture()
    ev = [
        person("a", end="2026-05", employer="apex-cloud.example"),
        person("a", end="2026-05", employer="www.Apex-Cloud.example", ev_id="dup-a"),  # same person, normalized
        person("b", "security", end="2026-04", employer="https://cedar-stack.example/careers"),
        person("c", end="2026-03", employer="unrelated-corp.example"),
        person("d", end="2026-03", employer="apex-cloud.example.evil.example"),  # not an exact domain match
    ]
    s5 = score_s5(case, ev, AS_OF)
    assert s5.raw_measure["competitor_moves_in_window"] == 2
    assert s5.raw_measure["moves_by_competitor"] == {"apex-cloud.example": 1, "cedar-stack.example": 1}
    none = score_s5(case, [person("c", end="2026-03", employer="unrelated-corp.example")], AS_OF)
    assert none.raw_measure["competitor_moves_in_window"] == 0
    assert none.score is not None and none.score < 10


def test_s5_fixture_wording_and_not_scored():
    case, ev = load_fixture()
    s5 = score_s5(case, ev, AS_OF)
    assert s5.raw_measure["competitor_moves_in_window"] == 1
    blob = json.dumps(s5.model_dump(mode="json")).lower()
    assert "trade secret" not in blob and "intellectual property" not in blob and " ip " not in blob
    case2, ev2 = load_fixture(drop_dates=True)
    s5b = score_s5(case2, ev2, AS_OF)
    assert s5b.state == SignalState.NOT_SCORED and s5b.score is None
    no_people = score_s5(case, [e for e in ev if e.kind != EvidenceKind.PERSON_HISTORY], AS_OF)
    assert no_people.state == SignalState.NOT_SCORED


def test_s5_requires_completed_interval_not_missing_end():
    case, _ = load_fixture()
    ev = [
        person("a", end=None, at_target=False, employer="apex-cloud.example"),
        person("b", end="2026-05", employer="apex-cloud.example"),
    ]
    s5 = score_s5(case, ev, AS_OF)
    assert s5.raw_measure["competitor_moves_in_window"] == 1
    assert s5.raw_measure["unconfirmed_timing"] == 1


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def test_t03_missing_data_insufficient_evidence_never_zero():
    case, ev = load_fixture(drop_dept=True, drop_dates=True)
    sc = compute_scorecard(case, ev, AS_OF)
    assert by_id(sc, SignalId.S1).state == SignalState.NOT_SCORED
    assert by_id(sc, SignalId.S2).state == SignalState.NOT_SCORED
    assert sc.coverage_pct < 60
    assert sc.coverage_label == "insufficient_evidence"
    assert sc.risk_score is None and sc.risk_band is None
    # individual scorable signals are still reported
    assert by_id(sc, SignalId.S4).score is not None


def test_fixture_composite_provisional_and_missing_data_lowers_confidence_only():
    case, ev = load_fixture()
    sc = compute_scorecard(case, ev, AS_OF)
    assert sc.coverage_label == "provisional" and 60 <= sc.coverage_pct < 80
    assert sc.risk_score is not None and sc.risk_band is not None
    case2, ev2 = load_fixture(drop_dept=True)
    sc2 = compute_scorecard(case2, ev2, AS_OF)
    assert sc2.evidence_confidence < sc.evidence_confidence


def _fake(sid: SignalId, state: SignalState, score: float | None) -> SignalResult:
    return SignalResult(
        signal_id=sid,
        name=sid.value,
        signal_version="t",
        state=state,
        score=score,
        weight=SIGNAL_WEIGHTS[sid],
        confidence=50,
    )


def _fakes(spec: dict[SignalId, tuple[SignalState, float | None]]) -> list[SignalResult]:
    return [_fake(sid, *spec.get(sid, (SignalState.NOT_SCORED, None))) for sid in SignalId]


def test_composite_math_and_coverage_labels():
    full = build_scorecard([_fake(s, SignalState.SCORABLE, 40.0) for s in SignalId])
    assert full.coverage_pct == 100 and full.coverage_label == "coverage_threshold_met"
    assert full.risk_score == 40.0 and full.risk_band == "Watch"

    sc = build_scorecard(
        _fakes(
            {
                SignalId.S1: (SignalState.SCORABLE, 80.0),
                SignalId.S2: (SignalState.SCORABLE, 20.0),
                SignalId.S4: (SignalState.SCORABLE, 50.0),
            }
        )
    )  # coverage 75, weighted risk (24 + 5 + 10) / 0.75 = 52
    assert sc.coverage_pct == 75 and sc.coverage_label == "provisional"
    assert sc.risk_score == 52.0 and sc.risk_band == "Elevated"

    thin = build_scorecard(
        _fakes({SignalId.S1: (SignalState.SCORABLE, 90.0), SignalId.S2: (SignalState.SCORABLE, 90.0)})
    )
    assert thin.coverage_pct == 55 and thin.coverage_label == "insufficient_evidence"
    assert thin.risk_score is None and thin.risk_band is None


def test_low_coverage_signal_counts_half_weight():
    sc = build_scorecard(
        _fakes(
            {
                SignalId.S1: (SignalState.SCORABLE, 60.0),
                SignalId.S2: (SignalState.LOW_COVERAGE, 20.0),
                SignalId.S4: (SignalState.SCORABLE, 60.0),
            }
        )
    )
    assert sc.coverage_pct == pytest.approx(62.5)  # 30 + 12.5 + 20
    assert sc.risk_score == pytest.approx((18 + 2.5 + 12) / 0.625, abs=0.1)


@pytest.mark.parametrize(
    ("cov", "label"),
    [
        (0, "insufficient_evidence"),
        (59.99, "insufficient_evidence"),
        (60, "provisional"),
        (79.99, "provisional"),
        (80, "coverage_threshold_met"),
        (100, "coverage_threshold_met"),
    ],
)
def test_coverage_label_thresholds(cov, label):
    assert coverage_label_for(cov) == label


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (0, "Low signal"),
        (24.9, "Low signal"),
        (25, "Watch"),
        (49.9, "Watch"),
        (50, "Elevated"),
        (69.9, "Elevated"),
        (70, "High signal"),
        (100, "High signal"),
    ],
)
def test_risk_bands(score, band):
    assert risk_band_for(score) == band


def test_evidence_confidence_is_weighted_mean_and_separate_from_risk():
    case, ev = load_fixture()
    sc = compute_scorecard(case, ev, AS_OF)
    expected = sum(s.weight * s.confidence for s in sc.signals) / sum(s.weight for s in sc.signals)
    assert sc.evidence_confidence == pytest.approx(expected, abs=0.1)
    for s in sc.signals:
        keys = set(s.confidence_breakdown)
        assert {"field_completeness", "recency", "independent_corroboration", "identity_resolution"} <= keys
