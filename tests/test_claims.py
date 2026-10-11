from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dealscope.domain.enums import ClaimType, EvidenceKind, SignalId, VerificationStatus
from dealscope.domain.models import (
    CaseInput,
    CompanyProfilePayload,
    EvidenceRecord,
    FindingClaim,
    JobPostingPayload,
    PersonHistoryPayload,
)
from dealscope.verification.claims import DEFAULT_ALTERNATIVE, REWRITE_HINTS, verify_claims

TARGET = "northstar-platform.example"
APEX = "apex-cloud.example"
CEDAR = "cedar-stack.example"
ORBIT = "orbit-data.example"
RETRIEVED = datetime(2026, 10, 11, 4, 30, tzinfo=UTC)


def make_ev(eid, kind, subject, payload, group=None, synthetic=True):
    return EvidenceRecord(
        evidence_id=eid,
        case_id="demo-case-001",
        kind=kind,
        subject_domain=subject,
        source_provider="fixture" if synthetic else "crustdata",
        source_endpoint="fixture:/synthetic",
        retrieved_at=RETRIEVED,
        payload=payload,
        dedup_key=eid,
        independence_group=group or f"grp-{eid}",
        synthetic=synthetic,
    )


def build_evidence() -> list[EvidenceRecord]:
    prof = EvidenceKind.COMPANY_PROFILE
    return [
        make_ev(
            "ev-syn-001", prof, TARGET,
            CompanyProfilePayload(
                domain=TARGET, total_headcount=480, total_growth_pct={"6m": 11}, engineering_growth_pct={"6m": -4}
            ),
        ),
        make_ev(
            "ev-syn-002", EvidenceKind.JOB_POSTING, TARGET,
            JobPostingPayload(
                title="Principal Platform Engineer", reposted=True, number_of_openings=1, date_added="2026-08-01"
            ),
        ),
        make_ev(
            "ev-syn-003", EvidenceKind.PERSON_HISTORY, TARGET,
            PersonHistoryPayload(
                person_ref="p-syn-001", role_group="technical_leadership", target_end="2026-05",
                current_employer_domain=APEX,
            ),
        ),
        make_ev(
            "ev-syn-004", prof, APEX,
            CompanyProfilePayload(domain=APEX, total_growth_pct={"6m": 8}, engineering_growth_pct={"6m": 7}),
        ),
        make_ev(
            "ev-syn-005", prof, CEDAR,
            CompanyProfilePayload(domain=CEDAR, total_growth_pct={"6m": 9}, engineering_growth_pct={"6m": 8}),
        ),
        make_ev(
            "ev-syn-006", prof, ORBIT,
            CompanyProfilePayload(domain=ORBIT, total_growth_pct={"6m": 4}, engineering_growth_pct={"6m": 3}),
        ),
        # second person history of the same target, plus a restructuring-style counter record
        make_ev(
            "ev-syn-007", EvidenceKind.PERSON_HISTORY, TARGET,
            PersonHistoryPayload(
                person_ref="p-syn-002", role_group="technical_leadership", target_end="2026-04",
                current_employer_domain=None,
            ),
        ),
    ]


@pytest.fixture
def evidence():
    return build_evidence()


@pytest.fixture
def case_input():
    return CaseInput(
        target_domain=TARGET,
        competitor_domains=[APEX, CEDAR, ORBIT],
        deal_thesis="Expand an enterprise workflow platform while maintaining reliability.",
    )


def claim(text, ids=("ev-syn-001",), ctype=ClaimType.OBSERVATION, **kw):
    return FindingClaim(text=text, claim_type=ctype, evidence_ids=list(ids), **kw)


def run(c, evidence, case_input):
    res = verify_claims([c], evidence, case_input, None)
    if res.rejected:
        return res.rejected[0], res
    return res.accepted[0], res


def codes(c, res):
    return res.rejection_codes[c.claim_id]


def test_fabricated_evidence_id_rejected(evidence, case_input):
    c, res = run(claim("Target headcount was observed.", ids=("ev-fake-999",)), evidence, case_input)
    assert c.verification_status is VerificationStatus.REJECTED
    assert "UNKNOWN_EVIDENCE_ID" in codes(c, res)


def test_unknown_counter_evidence_id_rejected(evidence, case_input):
    cl = claim("Target engineering headcount growth over 6m was -4%.", counter_evidence_ids=["ev-nope"])
    c, res = run(cl, evidence, case_input)
    assert "UNKNOWN_EVIDENCE_ID" in codes(c, res)


def test_material_claim_without_evidence_rejected(evidence, case_input):
    c, res = run(claim("Something was observed.", ids=()), evidence, case_input)
    assert "NO_EVIDENCE" in codes(c, res)


def test_hypothesis_and_question_may_have_no_evidence(evidence, case_input):
    h = claim("Engineering capacity may be constrained.", ids=(), ctype=ClaimType.HYPOTHESIS)
    q = claim("Is there a succession plan for platform leadership?", ids=(), ctype=ClaimType.QUESTION)
    res = verify_claims([h, q], evidence, case_input, None)
    assert len(res.accepted) == 2 and not res.rejected


def test_hypothesis_with_unknown_id_rejected(evidence, case_input):
    h = claim("Engineering capacity may be constrained.", ids=("ev-zzz",), ctype=ClaimType.HYPOTHESIS)
    res = verify_claims([h], evidence, case_input, None)
    assert res.rejected and "UNKNOWN_EVIDENCE_ID" in res.rejection_codes[h.claim_id]


def test_wrong_company_citation_rejected(evidence, case_input):
    cl = claim(f"{CEDAR} engineering headcount growth over 6m was 8%.", ids=("ev-syn-004",))
    c, res = run(cl, evidence, case_input)
    assert "ENTITY_MISMATCH" in codes(c, res)


def test_subject_domain_mismatch_rejected(evidence, case_input):
    cl = claim("Engineering headcount growth over 6m was 7%.", ids=("ev-syn-004",), subject_domain=TARGET)
    c, res = run(cl, evidence, case_input)
    assert "ENTITY_MISMATCH" in codes(c, res)


def test_subject_domain_matches_via_current_employer(evidence, case_input):
    cl = claim("One observed technical-leadership profile now lists a peer as current employer.",
               ids=("ev-syn-003",), subject_domain=APEX)
    c, _ = run(cl, evidence, case_input)
    assert c.verification_status is VerificationStatus.VERIFIED


def test_t04_overstated_attrition_rejected_and_safe_rewrite_accepted(evidence, case_input):
    bad, res = run(claim("40% of the engineering team left.", ids=("ev-syn-003", "ev-syn-007")), evidence, case_input)
    assert bad.verification_status is VerificationStatus.REJECTED
    assert "PROHIBITED_ATTRITION_RATE" in codes(bad, res)
    assert "UNSUPPORTED_NUMBER" in codes(bad, res)
    assert "company-wide attrition" in bad.verification_notes[-1] or any(
        "company-wide attrition" in n for n in bad.verification_notes
    )
    good, _ = run(
        claim(
            "Two observed profiles have target-company employment intervals ending in the period; "
            "profile coverage does not establish company-wide attrition.",
            ids=("ev-syn-003", "ev-syn-007"),
        ),
        evidence,
        case_input,
    )
    assert good.verification_status in {VerificationStatus.VERIFIED, VerificationStatus.QUALIFIED}


def test_attrition_rate_phrase_rejected_but_negated_allowed(evidence, case_input):
    bad, res = run(claim("The attrition rate is elevated.", ids=("ev-syn-003",)), evidence, case_input)
    assert "PROHIBITED_ATTRITION_RATE" in codes(bad, res)
    ok, _ = run(claim("One observed profile does not establish an attrition rate.", ids=("ev-syn-003",)),
                evidence, case_input)
    assert ok.verification_status is not VerificationStatus.REJECTED


def test_overstated_count_of_profiles_rejected(evidence, case_input):
    c, res = run(claim("Three observed profiles have intervals ending in the period.",
                       ids=("ev-syn-003", "ev-syn-007")), evidence, case_input)
    assert "UNSUPPORTED_NUMBER" in codes(c, res)


def test_t05_causal_allegation_rejected_and_observed_move_accepted(evidence, case_input):
    bad, res = run(claim("The target leaked IP because an engineer joined a competitor.", ids=("ev-syn-003",)),
                   evidence, case_input)
    assert "PROHIBITED_CAUSAL_ALLEGATION" in codes(bad, res)
    good, _ = run(
        claim(
            f"One observed technical-leadership profile now lists {APEX} as current employer.",
            ids=("ev-syn-003",),
        ),
        evidence,
        case_input,
    )
    assert good.verification_status is VerificationStatus.VERIFIED


@pytest.mark.parametrize("text", [
    "A valuation haircut of 10% is warranted.",
    "We should not invest in the target.",
    "The buyer should pass on the deal.",
])
def test_valuation_recommendations_rejected(text, evidence, case_input):
    c, res = run(claim(text), evidence, case_input)
    assert "PROHIBITED_VALUATION" in codes(c, res)


@pytest.mark.parametrize("text", ["Technical debt is proven.", "The target committed fraud."])
def test_other_prohibited_causal_words(text, evidence, case_input):
    c, res = run(claim(text), evidence, case_input)
    assert "PROHIBITED_CAUSAL_ALLEGATION" in codes(c, res)


def test_direction_mismatch_rejected(evidence, case_input):
    c, res = run(claim("Target engineering headcount grew over 6m."), evidence, case_input)
    assert "DIRECTION_MISMATCH" in codes(c, res)
    c2, res2 = run(claim("Total headcount declined over 6m."), evidence, case_input)
    assert "DIRECTION_MISMATCH" in codes(c2, res2)


def test_correct_direction_accepted(evidence, case_input):
    c, _ = run(claim("Target engineering headcount contracted while total headcount grew over 6m."),
               evidence, case_input)
    assert c.verification_status is VerificationStatus.VERIFIED


def test_unsupported_number_rejected(evidence, case_input):
    c, res = run(claim("Target engineering headcount growth over 6m was -9% versus total of 11%."),
                 evidence, case_input)
    assert "UNSUPPORTED_NUMBER" in codes(c, res)


@pytest.mark.parametrize("text", [
    "Target engineering headcount growth over 6m was -4% versus total headcount growth of 11%.",
    "Target engineering headcount growth was -4.0% versus total headcount growth of +11%.",
    "The gap between total and engineering growth over 6m was 15 points.",
])
def test_number_formatting_and_derivations_accepted(text, evidence, case_input):
    c, _ = run(claim(text), evidence, case_input)
    assert c.verification_status is VerificationStatus.VERIFIED


def test_unsupported_date_rejected(evidence, case_input):
    c, res = run(claim("One observed profile has a target interval ending 2024-01.", ids=("ev-syn-003",)),
                 evidence, case_input)
    assert "UNSUPPORTED_DATE" in codes(c, res)
    ok, _ = run(claim("One observed profile has a target interval ending 2026-05.", ids=("ev-syn-003",)),
                evidence, case_input)
    assert ok.verification_status is VerificationStatus.VERIFIED
    bad_year, res3 = run(claim("The job was added in 2025.", ids=("ev-syn-002",)), evidence, case_input)
    assert "UNSUPPORTED_DATE" in codes(bad_year, res3)


def test_t11_counter_evidence_kept_and_qualified(evidence, case_input):
    cl = FindingClaim(
        text="Observed departures of technical leaders may indicate a continuity risk.",
        claim_type=ClaimType.INTERPRETATION,
        evidence_ids=["ev-syn-003", "ev-syn-007"],
        counter_evidence_ids=["ev-syn-001"],
        alternative_explanations=["Planned reorganization of the platform group."],
        subject_domain=TARGET,
    )
    res = verify_claims([cl], evidence, case_input, None)
    assert not res.rejected
    out = res.accepted[0]
    assert out.verification_status is VerificationStatus.QUALIFIED
    assert out.evidence_ids == ["ev-syn-003", "ev-syn-007"] and out.counter_evidence_ids == ["ev-syn-001"]
    assert any("counter-evidence" in n for n in out.verification_notes)
    assert "synthetic fixture evidence" in out.verification_notes


def test_single_source_interpretation_qualified_and_default_alternative_added(evidence, case_input):
    cl = FindingClaim(
        text="Observed departures may indicate a continuity risk in platform engineering.",
        claim_type=ClaimType.INTERPRETATION,
        evidence_ids=["ev-syn-003"],
    )
    res = verify_claims([cl], evidence, case_input, None)
    out = res.accepted[0]
    assert out.verification_status is VerificationStatus.QUALIFIED
    assert any("single-source; not independently corroborated" in n for n in out.verification_notes)
    assert DEFAULT_ALTERNATIVE in out.alternative_explanations
    assert cl.alternative_explanations == []  # input untouched
    assert cl.verification_status is None


def test_duplicate_independence_group_is_not_corroboration(case_input):
    ev = [
        make_ev("e1", EvidenceKind.PERSON_HISTORY, TARGET,
                PersonHistoryPayload(person_ref="a", role_group="security", target_end="2026-05"), group="same"),
        make_ev("e2", EvidenceKind.PERSON_HISTORY, TARGET,
                PersonHistoryPayload(person_ref="b", role_group="security", target_end="2026-04"), group="same"),
        make_ev("e3", EvidenceKind.JOB_POSTING, TARGET, JobPostingPayload(title="Security Lead"), group="other"),
    ]
    cl = FindingClaim(text="Security leadership coverage appears thin.", claim_type=ClaimType.INTERPRETATION,
                      evidence_ids=["e1", "e2"])
    out = verify_claims([cl], ev, case_input, None).accepted[0]
    assert out.verification_status is VerificationStatus.QUALIFIED
    assert any("independence group" in n for n in out.verification_notes)
    cl2 = cl.model_copy(update={"evidence_ids": ["e1", "e3"], "claim_id": "x2"})
    out2 = verify_claims([cl2], ev, case_input, None).accepted[0]
    assert out2.verification_status is VerificationStatus.VERIFIED


def test_metrics(evidence, case_input):
    good = claim("Target engineering headcount growth over 6m was -4% versus total headcount growth of 11%.")
    bad = claim("The target leaked IP.")
    fake = claim("Observed.", ids=("nope",))
    q = claim("Is there a plan?", ids=(), ctype=ClaimType.QUESTION)
    res = verify_claims([good, bad, fake, q], evidence, case_input, None)
    m = res.metrics
    assert m["total"] == 4 and m["rejected"] == 2 and m["verified"] == 2
    assert m["material_total"] == 3
    assert m["grounded_claim_rate"] == pytest.approx(1 / 3)
    assert m["unsupported_material_claims"] == 2
    assert m["rejection_reasons"]["PROHIBITED_CAUSAL_ALLEGATION"] == 1
    assert m["rejection_reasons"]["UNKNOWN_EVIDENCE_ID"] == 1


def test_rewrite_hints_cover_all_codes():
    assert "does not establish company-wide attrition" in REWRITE_HINTS["PROHIBITED_ATTRITION_RATE"]
    for code in ("NO_EVIDENCE", "UNKNOWN_EVIDENCE_ID", "ENTITY_MISMATCH", "UNSUPPORTED_NUMBER",
                 "DIRECTION_MISMATCH", "UNSUPPORTED_DATE", "PROHIBITED_VALUATION",
                 "PROHIBITED_CAUSAL_ALLEGATION"):
        assert REWRITE_HINTS[code]


def test_related_signal_numbers_allowed(evidence, case_input):
    from dealscope.domain.enums import SignalState
    from dealscope.domain.models import Scorecard, SignalResult

    sc = Scorecard(
        signals=[SignalResult(signal_id=SignalId.S1, name="x", signal_version="v1", state=SignalState.SCORABLE,
                              score=55, weight=0.3, raw_measure={"gap_pts": 15.0, "peer_median": 7.0},
                              confidence=60)],
        risk_score=55, coverage_pct=30, coverage_label="insufficient_evidence", risk_band="Elevated",
        evidence_confidence=50, signal_version="v1",
    )
    cl = claim("The S1 engineering gap versus total was 15 points and the S1 score was 55.",
               related_signals=[SignalId.S1])
    res = verify_claims([cl], evidence, case_input, sc)
    assert res.accepted
