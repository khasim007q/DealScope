"""Regression tests for the audit-confirmed analysis weaknesses (inverse of each probe)."""

from __future__ import annotations

from decimal import Decimal

from dealscope.agent import planner as pl
from dealscope.analysis.signals import (
    build_scorecard,
    compute_scorecard,
    inconclusive_reason,
    is_inconclusive,
    score_s1,
    score_s2,
    score_s3,
    score_s4,
)
from dealscope.domain.enums import EvidenceKind, SignalId, SignalState, ToolName
from dealscope.domain.models import (
    CaseInput,
    CaseState,
    CompanyProfilePayload,
    CompletedAction,
    JobPostingPayload,
    PersonHistoryPayload,
    PlannerAction,
    SignalResult,
)
from tests.test_signals import AS_OF, TARGET, _record, job, person

PEERS = ["peer-one.example", "peer-two.example", "peer-three.example"]


def prof(domain=TARGET, hc=500, tot=None, eng=None):
    p = CompanyProfilePayload(
        domain=domain, total_headcount=hc, total_growth_pct=tot or {}, engineering_growth_pct=eng or {}
    )
    return _record(EvidenceKind.COMPANY_PROFILE, domain, p, f"ev-prof-{domain}")


def case(**kw):
    return CaseInput(target_domain=TARGET, competitor_domains=list(PEERS), **kw)


def sig(sc, sid):
    return next(s for s in sc.signals if s.signal_id == sid)


def state_for(ci, done=()):
    st = CaseState(input=ci, mode=ci.mode, credit_budget=Decimal("100"))
    for a in done:
        st.completed_actions.append(CompletedAction(iteration=1, action=a, tool_run_id=None, outcome="succeeded"))
    return st


def cands(st, ev, jobs=True):
    return pl.candidate_actions(st, ev, None, lambda a: Decimal("1"), jobs)


# ---- 1. sample-size blind coverage / confidence ----------------------------------------------------------------


def test_one_posting_and_one_profile_do_not_publish_a_composite():
    ev = [
        prof(tot={"6m": 5.0}, eng={"6m": 5.0}),
        person("a", end="2026-06", at_target=False),
        job("Senior Eng", url="u"),
    ]
    sc = compute_scorecard(case(), ev, AS_OF)
    assert sc.risk_score is None and sc.risk_band is None
    assert is_inconclusive(sc) and inconclusive_reason(sc) == "insufficient_coverage"
    assert sig(sc, SignalId.S4).state == SignalState.LOW_COVERAGE
    assert sig(sc, SignalId.S4).confidence < 60 and sig(sc, SignalId.S2).confidence < 40


def test_sample_size_scales_confidence():
    one = score_s4(case(), [prof(), job("Senior Eng 0", url="u0")], AS_OF)
    many = score_s4(case(), [prof(), *[job(f"Senior Eng {i}", url=f"u{i}") for i in range(8)]], AS_OF)
    assert many.confidence > one.confidence + 20
    assert many.state == SignalState.SCORABLE


def test_composite_withheld_on_low_weighted_confidence_even_with_coverage():
    def fake(sid, w, conf):
        return SignalResult(
            signal_id=sid, name="x", signal_version="v", state=SignalState.SCORABLE, score=40, weight=w, confidence=conf
        )

    absent = [
        SignalResult(signal_id=sid, name="x", signal_version="v", state=SignalState.NOT_SCORED, weight=w, confidence=0)
        for sid, w in ((SignalId.S3, 0.15), (SignalId.S5, 0.10))
    ]
    sc = build_scorecard([fake(SignalId.S1, 0.3, 30), fake(SignalId.S2, 0.25, 30), fake(SignalId.S4, 0.2, 30), *absent])
    assert sc.coverage_pct == 75.0 and sc.risk_score is None
    assert inconclusive_reason(sc) == "low_evidence_confidence"
    ok = build_scorecard([fake(SignalId.S1, 0.3, 80), fake(SignalId.S2, 0.25, 80), fake(SignalId.S4, 0.2, 80), *absent])
    assert ok.risk_score is not None and not is_inconclusive(ok) and inconclusive_reason(ok) is None


# ---- 2. S2 leavers-only denominator ----------------------------------------------------------------------------


def test_s2_leavers_only_sample_gets_no_share_bonus_and_is_low_coverage():
    ev = [person(f"p{i}", end="2026-06", at_target=False) for i in range(3)]
    s2 = score_s2(case(), ev, AS_OF)
    assert "HIGH_SHARE_OF_OBSERVED_PROFILES" not in s2.reason_codes
    assert "NO_CURRENT_LEADERSHIP_DENOMINATOR" in s2.reason_codes
    # 65 (3 leavers) + 10 (concentration); no +5 share bonus
    assert s2.state == SignalState.LOW_COVERAGE and s2.score == 75.0


def test_s2_share_bonus_applies_with_a_current_sample():
    ev = [person(f"p{i}", end="2026-06", at_target=False) for i in range(3)]
    ev += [person("c0", end=None, at_target=True)]
    s2 = score_s2(case(), ev, AS_OF)
    assert "HIGH_SHARE_OF_OBSERVED_PROFILES" in s2.reason_codes
    assert s2.state == SignalState.SCORABLE and s2.raw_measure["current_leaders_observed"] == 1


def test_planner_offers_current_leadership_query_without_prior_people_evidence():
    out = cands(state_for(case()), [prof(tot={"6m": 5})])
    assert any(
        c.action.action == ToolName.SEARCH_PEOPLE
        and c.action.arguments["relationship"] == "current_target_employment"
        for c in out
    )


def test_planner_picks_current_leaders_after_past_when_no_current_sample():
    ci = case()
    past = PlannerAction(
        action=ToolName.SEARCH_PEOPLE,
        arguments={"role_group": "technical_leadership", "relationship": "past_target_employment", "limit": 25},
        decided_by="deterministic_fallback",
    )
    ev = [
        prof(tot={"6m": 5}),
        _record(
            EvidenceKind.PERSON_HISTORY,
            TARGET,
            PersonHistoryPayload(
                person_ref="p1", role_group="technical_leadership", target_start="2019-01", target_end="2026-05"
            ),
            "ev-p1",
        ),
    ]
    st = state_for(ci, [past])
    choice = pl.deterministic_choice(st, ev, None, cands(st, ev))
    assert choice.action == ToolName.SEARCH_PEOPLE and choice.arguments["relationship"] == "current_target_employment"


# ---- 3 / 4. S1 -------------------------------------------------------------------------------------------------


def test_s1_tiny_overlapping_contraction_is_not_high_severity():
    ev = [prof(tot={"3m": 0.0, "6m": 0.0}, eng={"3m": -0.5, "6m": -0.5})]
    s1 = score_s1(case(), ev, AS_OF)
    assert s1.score is not None and s1.score < 40
    assert "MULTI_PERIOD_TECH_CONTRACTION" not in s1.reason_codes


def test_s1_nested_windows_count_as_one_observation():
    # 6m and 12m both diverge, but the extra 6 months inside 12m show no divergence: one observation, not two.
    ev = [prof(tot={"6m": 5.0, "12m": 5.0}, eng={"6m": -6.0, "12m": -6.0})]
    s1 = score_s1(case(), ev, AS_OF)
    assert "MULTI_PERIOD_TECH_CONTRACTION" not in s1.reason_codes
    assert "OVERLAPPING_WINDOWS_TREATED_AS_ONE" in s1.reason_codes
    assert s1.score is not None and s1.score <= 60


def test_s1_independent_segments_still_count_as_multi_period():
    # the 6 months before the last 6 also show tech trailing total
    ev = [prof(tot={"6m": 11.0, "12m": 18.0}, eng={"6m": -4.0, "12m": -2.0})]
    s1 = score_s1(case(), ev, AS_OF)
    assert "MULTI_PERIOD_TECH_CONTRACTION" in s1.reason_codes and s1.score >= 65


def test_s1_engineering_collapse_in_shrinking_company_scores_high():
    ev = [prof(tot={"6m": -3.0}, eng={"6m": -30.0})]
    s1 = score_s1(case(), ev, AS_OF)
    assert s1.score is not None and s1.score >= 45
    assert "CONTRACTION_CONSISTENT_WITH_TOTAL_6M" not in s1.reason_codes
    assert "TECH_CONTRACTION_EXCEEDS_TOTAL_6M" in s1.reason_codes


def test_s1_contraction_in_line_with_shrinking_company_stays_benign():
    ev = [prof(tot={"6m": -10.0}, eng={"6m": -11.0})]
    s1 = score_s1(case(), ev, AS_OF)
    assert s1.score == 25.0 and "CONTRACTION_CONSISTENT_WITH_TOTAL_6M" in s1.reason_codes


# ---- 5. S4 growth read as risk ---------------------------------------------------------------------------------


def test_s4_hiring_into_growth_at_scale_is_not_pressure():
    ev = [prof(hc=5000, tot={"6m": 25.0}, eng={"6m": 30.0}), *[job(f"Senior Eng {i}", url=f"u{i}") for i in range(6)]]
    s4 = score_s4(case(), ev, AS_OF)
    assert s4.score == 30.0 and "UNUSUAL_CONCENTRATION_OR_PERSISTENCE" not in s4.reason_codes


def test_s4_high_share_is_dampened_when_total_and_engineering_both_grow():
    ev = [prof(hc=60, tot={"6m": 20.0}, eng={"6m": 25.0}), *[job(f"Senior Eng {i}", url=f"u{i}") for i in range(4)]]
    s4 = score_s4(case(), ev, AS_OF)
    assert s4.score == 30.0 and "HIRING_INTO_GROWTH_NOT_PRESSURE" in s4.reason_codes


def test_s4_concentration_is_share_based_when_headcount_known():
    # 4 openings at a 60-person company = 6.7% of headcount: unusual, though below the old absolute count of 6
    ev = [prof(hc=60, tot={"6m": 0.0}, eng={"6m": 0.0}), *[job(f"Senior Eng {i}", url=f"u{i}") for i in range(4)]]
    assert score_s4(case(), ev, AS_OF).score == 50.0


# ---- 6. S4 duplicate inflation ---------------------------------------------------------------------------------


def test_s4_same_role_in_many_locations_counts_once():
    ev = [job("Staff Platform Engineer", url=f"https://j/loc{i}") for i in range(6)]
    s4 = score_s4(case(), ev, AS_OF)
    assert s4.raw_measure["critical_openings_count"] == 1 and s4.score < 50


def test_s4_single_posting_with_many_openings_is_capped():
    s4 = score_s4(case(), [job("Senior Engineer", n=6, url="u")], AS_OF)
    assert s4.raw_measure["critical_openings_count"] == 2 and s4.score < 50
    assert "OPENINGS_CAPPED_PER_POSTING" in s4.reason_codes


def test_s4_same_title_in_different_team_is_a_different_posting():
    a = job("Senior Engineer", url="https://j/a")
    b = job("Senior Engineer", url="https://j/b")
    b = b.model_copy(update={"payload": b.payload.model_copy(update={"category": "Data"})})
    s4 = score_s4(case(), [a, b], AS_OF)
    assert s4.raw_measure["critical_openings_count"] == 2


# ---- 7. free mode / peers / S3 / persistence -------------------------------------------------------------------


def test_s3_open_roles_without_people_evidence_is_no_data():
    s3 = score_s3(case(), [job("Security Engineer", role="security", cap="security", url="u1")], AS_OF)
    assert s3.state == SignalState.NOT_SCORED and s3.score is None
    sec = next(r for r in s3.raw_measure["capability_matrix"] if r["capability"] == "security")
    assert sec["status"] == "no_data" and sec["open_roles"] == 1


def test_s4_uniformly_old_board_is_not_persistent():
    ev = [job(f"Senior Eng {i}", url=f"u{i}", added="2026-08-08") for i in range(5)]  # all 64 days old
    s4 = score_s4(case(), ev, AS_OF)
    assert s4.raw_measure["persistent_or_reposted_critical_postings"] == 0
    assert "UNUSUAL_CONCENTRATION_OR_PERSISTENCE" not in s4.reason_codes


def test_s4_postings_old_relative_to_the_board_are_persistent():
    ev = [job(f"Fresh {i}", url=f"f{i}", added="2026-10-01") for i in range(3)]
    ev += [job(f"Stale {i}", url=f"s{i}", added="2026-07-01") for i in range(2)]
    s4 = score_s4(case(), ev, AS_OF)
    assert s4.raw_measure["persistent_or_reposted_critical_postings"] == 2


def test_planner_offers_peer_job_searches_below_target():
    out = cands(state_for(case()), [prof()])
    job_doms = [c.action.arguments["domain"] for c in out if c.action.action == ToolName.SEARCH_JOBS]
    assert job_doms[0] == TARGET and set(job_doms[1:]) == set(PEERS)


def test_planner_picks_peer_jobs_when_company_and_people_tools_unavailable():
    ci = case()
    st = state_for(ci)
    st.unavailable_tools = {"enrich_company": "NOT_CONFIGURED", "search_people": "NOT_CONFIGURED"}
    first = pl.deterministic_choice(st, [], None, cands(st, []))
    assert first.action == ToolName.SEARCH_JOBS and first.arguments["domain"] == TARGET
    st.completed_actions.append(CompletedAction(iteration=1, action=first, tool_run_id=None, outcome="succeeded"))
    second = pl.deterministic_choice(st, [], None, cands(st, []))
    assert second.action == ToolName.SEARCH_JOBS and second.arguments["domain"] in PEERS


# ---- planner medium items --------------------------------------------------------------------------------------


def test_planner_runs_jobs_when_coverage_thin_instead_of_stopping():
    first = PlannerAction(
        action=ToolName.SEARCH_PEOPLE,
        arguments={"role_group": "technical_leadership", "relationship": "past_target_employment", "limit": 25},
        decided_by="deterministic_fallback",
    )
    st = state_for(case(), [first])
    ev = [
        prof(tot={"6m": 5}),
        _record(
            EvidenceKind.PERSON_HISTORY,
            TARGET,
            PersonHistoryPayload(
                person_ref="p1", role_group="technical_leadership", target_start="2019-01", currently_at_target=True
            ),
            "ev-p1",
        ),
    ]
    choice = pl.deterministic_choice(st, ev, None, cands(st, ev))
    assert choice.action == ToolName.SEARCH_JOBS and choice.arguments["domain"] == TARGET


def test_planner_job_query_uses_case_capabilities_and_lookback():
    ci = case(critical_capabilities=["security"], lookback_months=36)
    j = next(c for c in cands(state_for(ci), [prof()]) if c.action.action == ToolName.SEARCH_JOBS)
    assert j.action.arguments["role_terms"] == ["engineering_leadership", "security"]
    assert j.action.arguments["lookback_days"] == 365
    j.action.typed_arguments()  # still valid against the strict schema


def test_open_questions_are_ordered_by_severity():
    ci = case()
    ev = [person(f"p{i}", end="2026-06", at_target=False) for i in range(3)]
    ev += [person("c0", end=None, at_target=True)]
    sc = compute_scorecard(ci, ev, AS_OF)
    assert sig(sc, SignalId.S2).score >= 65
    qs = pl.refresh_open_questions(state_for(ci), ev, sc)
    idx_s1 = next(i for i, q in enumerate(qs) if q.startswith("Provide internal engineering headcount"))
    idx_s2 = next(i for i, q in enumerate(qs) if q.startswith("Which senior technical leaders left"))
    assert idx_s2 < idx_s1


# ---- memo ------------------------------------------------------------------------------------------------------


def test_memo_job_claim_reuses_the_signals_deduped_critical_set():
    from dealscope.reports.memo import deterministic_claims

    ci = case()
    j1 = _record(
        EvidenceKind.JOB_POSTING,
        TARGET,
        JobPostingPayload(title="Senior Eng", role_group="senior_technical_ic", url="https://j/1"),
        "ev-j1",
    )
    j2 = _record(EvidenceKind.JOB_POSTING, TARGET, j1.payload, "ev-j2")  # re-fetch duplicate
    j3 = _record(
        EvidenceKind.JOB_POSTING,
        TARGET,
        JobPostingPayload(title="Office Manager", role_group="non_technical"),
        "ev-j3",
    )
    ev = [prof(tot={"6m": 5}, eng={"6m": 5}), j1, j2, j3]
    sc = compute_scorecard(ci, ev, AS_OF)
    claims = deterministic_claims(sc, ev, ci)
    claim = next(c for c in claims if SignalId.S4 in c.related_signals)
    assert claim.text.startswith("One current job posting for thesis-relevant technical roles was observed")
    assert len(claim.evidence_ids) == 1 and "ev-j3" not in claim.evidence_ids


def test_exec_headline_names_a_dominant_signal_the_composite_hides():
    from dealscope.reports.memo import _coverage_text

    def fake(sid, w, score):
        return SignalResult(
            signal_id=sid, name="x", signal_version="v", state=SignalState.SCORABLE, score=score, weight=w,
            confidence=80,
        )

    sc = build_scorecard([fake(SignalId.S1, 0.30, 85), fake(SignalId.S2, 0.25, 5), fake(SignalId.S4, 0.20, 5)])
    headline, _ = _coverage_text(sc)
    assert "S1" in headline and "Highest single signal" in headline


def test_exec_headline_explains_confidence_withholding():
    from dealscope.reports.memo import _coverage_text

    def fake(sid, w):
        return SignalResult(
            signal_id=sid, name="x", signal_version="v", state=SignalState.SCORABLE, score=40, weight=w, confidence=20
        )

    sc = build_scorecard([fake(SignalId.S1, 0.30), fake(SignalId.S2, 0.25), fake(SignalId.S4, 0.20)])
    headline, label = _coverage_text(sc)
    assert label == "insufficient_evidence" and "confidence" in headline and "below the 60%" not in headline
