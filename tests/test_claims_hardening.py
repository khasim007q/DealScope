"""Regression tests for the claim-verifier hardening (kind-aware numbers, metric pairing, causal connectives,
number-word counts, company/person names, vague quantities)."""

from __future__ import annotations

import pytest

from dealscope.domain.enums import ClaimType, VerificationStatus
from dealscope.domain.models import CaseInput, FindingClaim
from dealscope.verification.claims import verify_claims
from tests.test_claims import APEX, CEDAR, ORBIT, TARGET, build_evidence

ALL = ("ev-syn-001", "ev-syn-003", "ev-syn-007")


def verify(text, ids=ALL, ctype=ClaimType.OBSERVATION, **kw):
    ci = CaseInput(target_domain=TARGET, competitor_domains=[APEX, CEDAR, ORBIT], deal_thesis="Expand a platform.")
    c = FindingClaim(text=text, claim_type=ctype, evidence_ids=list(ids), **kw)
    res = verify_claims([c], build_evidence(), ci, None)
    out = (res.accepted or res.rejected)[0]
    return out, res.rejection_codes.get(out.claim_id, [])


def accepted(text, **kw):
    return verify(text, **kw)[0].verification_status in (VerificationStatus.VERIFIED, VerificationStatus.QUALIFIED)


def codes(text, **kw):
    return verify(text, **kw)[1]


# --- CRITICAL 1: numbers are matched by kind, signed ----------------------------------------------------------------


def test_growth_value_is_not_a_head_count():
    assert "UNSUPPORTED_NUMBER" in codes("11 senior engineers left the target.", ids=("ev-syn-001", "ev-syn-003"))


def test_sign_is_not_dropped_for_growth():
    assert "UNSUPPORTED_NUMBER" in codes("Engineering headcount growth was 4%.", ids=("ev-syn-001",))
    assert "UNSUPPORTED_NUMBER" in codes("Engineering headcount grew 4% over 6m.", ids=("ev-syn-001",))
    assert accepted("Engineering headcount growth was -4% over 6m.", ids=("ev-syn-001",))
    assert accepted("Engineering headcount fell 4% over 6m.", ids=("ev-syn-001",))


def test_percent_must_come_from_a_growth_series_not_a_count():
    # 480 is the headcount (a bare count), not a percentage
    assert "UNSUPPORTED_NUMBER" in codes("Total headcount grew 480% over 6m.", ids=("ev-syn-001",))
    assert accepted("Total headcount was 480 at the last observation.", ids=("ev-syn-001",))


def test_percent_period_must_exist():
    assert "UNSUPPORTED_NUMBER" in codes("Total headcount grew 11% over 12m.", ids=("ev-syn-001",))


# --- CRITICAL 2: metric -> value pairing, negation -------------------------------------------------------------------


def test_swapped_metrics_rejected():
    text = "Total headcount growth was 4% while engineering headcount growth was 11% over 6m."
    assert "UNSUPPORTED_NUMBER" in codes(text, ids=("ev-syn-001",))
    ok = "Total headcount growth was 11% while engineering headcount growth was -4% over 6m."
    assert accepted(ok, ids=("ev-syn-001",))


def test_metric_pairing_for_peers():
    ok = "Observed peers engineering headcount growth ranged from 7% to 8% over 6m."
    assert accepted(ok, ids=("ev-syn-004", "ev-syn-005"))
    bad = "Observed peers engineering headcount growth was 11% over 6m."
    assert "UNSUPPORTED_NUMBER" in codes(bad, ids=("ev-syn-004",))


def test_negated_growth_is_not_a_direction_mismatch():
    assert accepted("Engineering headcount did not grow over 6m; it contracted 4%.", ids=("ev-syn-001",))
    assert accepted("There was no engineering headcount growth over 6m.", ids=("ev-syn-001",))
    # but denying a growth that did happen is wrong
    assert "DIRECTION_MISMATCH" in codes("Total headcount did not grow over 6m.", ids=("ev-syn-001",))


# --- CRITICAL 3: causal connectives ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The CTO departure was likely due to a failed reorganization.",
        "Departures were probably caused by poor engineering culture.",
        "A senior leader moved to a competitor after a dispute with the founders.",
        "Leadership left because of strategy disagreements.",
        "The move happened as a result of the founders conflict.",
    ],
)
def test_causal_connectives_rejected_in_material_claims(text):
    assert "PROHIBITED_CAUSAL_ALLEGATION" in codes(text, ids=("ev-syn-003",))
    assert "PROHIBITED_CAUSAL_ALLEGATION" in codes(text, ids=("ev-syn-003",), ctype=ClaimType.INTERPRETATION)


def test_causal_hypothesis_needs_alternative_but_question_is_allowed():
    text = "The departure may be due to a leadership dispute."
    assert "PROHIBITED_CAUSAL_ALLEGATION" in codes(text, ids=("ev-syn-003",), ctype=ClaimType.HYPOTHESIS)
    ok = verify(
        text,
        ids=("ev-syn-003",),
        ctype=ClaimType.HYPOTHESIS,
        alternative_explanations=["Planned reorganization of the platform group."],
    )[0]
    assert ok.verification_status is not VerificationStatus.REJECTED
    q = "Was the departure due to a leadership dispute or a planned reorganization?"
    assert accepted(q, ids=("ev-syn-003",), ctype=ClaimType.QUESTION)


# --- HIGH: counts with number words / more nouns --------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Three technical leaders left the target.",
        "Twelve observed profiles show target intervals ending.",
        "Fifteen engineers departed.",
        "3 managers are now at a competitor.",
        "A dozen executives left.",
        "Twenty-one people left the target.",
        "Four open positions were observed.",
    ],
)
def test_overstated_counts_rejected(text):
    assert "UNSUPPORTED_NUMBER" in codes(text, ids=("ev-syn-003", "ev-syn-007"))


def test_correct_counts_accepted():
    assert accepted("Two technical leaders left the target.", ids=("ev-syn-003", "ev-syn-007"))
    assert accepted("One observed profile now lists a competitor.", ids=("ev-syn-003", "ev-syn-007"))
    assert accepted("Two peers are cited.", ids=("ev-syn-004", "ev-syn-005"))
    assert "UNSUPPORTED_NUMBER" in codes("Three peers are cited.", ids=("ev-syn-004", "ev-syn-005"))


# --- HIGH: company names and person names ---------------------------------------------------------------------------


def test_competitor_named_without_domain_is_entity_checked():
    c = codes("Cedar Stack engineering headcount grew 7% over 6m.", ids=("ev-syn-004",))
    assert "ENTITY_MISMATCH" in c
    assert accepted("Apex Cloud engineering headcount grew 7% over 6m.", ids=("ev-syn-004",))
    assert accepted("Apex engineering headcount grew 7% over 6m.", ids=("ev-syn-004",))


@pytest.mark.parametrize(
    "text",
    [
        "Jane Doe, the former CTO, left the target.",
        "The former CTO Jane Doe left the target.",
        "The former CTO Jane left the target.",
        "One profile belongs to John Smith.",
    ],
)
def test_person_names_rejected(text):
    assert "UNSUPPORTED_PERSON_NAME" in codes(text, ids=("ev-syn-003",))


def test_company_and_role_titles_are_not_person_names():
    text = "One observed Technical Leadership profile now lists Apex Cloud as current employer."
    assert accepted(text, ids=("ev-syn-003",))


# --- HIGH: vague quantities -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Most of the senior technical leadership departed the target.",
        "Dozens of engineers left the target.",
        "Engineering headcount roughly halved while leadership turned over.",
        "A massive exodus of leaders occurred.",
        "Hiring surged significantly.",
    ],
)
def test_vague_quantities_rejected(text):
    assert "VAGUE_QUANTITY" in codes(text, ids=("ev-syn-001", "ev-syn-003"))


def test_vague_quantity_anchored_by_verified_number_is_accepted():
    assert accepted("Engineering headcount fell significantly by 4% over 6m.", ids=("ev-syn-001",))
    assert "VAGUE_QUANTITY" in codes("Engineering headcount fell significantly by 40% over 6m.", ids=("ev-syn-001",))
    assert accepted("The posting was most recently added 2026-08-01.", ids=("ev-syn-002",))


# --- MEDIUM: false positives ----------------------------------------------------------------------------------------


def test_growth_percent_near_left_word_is_not_attrition():
    text = "Total headcount grew 11% over 6m, and two observed profiles have left."
    assert accepted(text, ids=ALL)
    assert "PROHIBITED_ATTRITION_RATE" in codes("40% of the engineering team left.", ids=ALL)
    assert "PROHIBITED_ATTRITION_RATE" in codes("Attrition reached 40% this year.", ids=ALL)


@pytest.mark.parametrize(
    "text",
    [
        "This memo makes no valuation recommendation; engineering growth was -4% over 6m.",
        "Buy-side diligence should confirm the -4% engineering change over 6m.",
        "We found no evidence of technical debt in the cited records.",
    ],
)
def test_safe_uses_of_trigger_words_accepted(text):
    assert accepted(text, ids=("ev-syn-001",))


@pytest.mark.parametrize(
    "text",
    ["A valuation haircut is warranted.", "The team should buy.", "Technical debt is evident.", "The target stole IP."],
)
def test_real_triggers_still_rejected(text):
    assert not accepted(text, ids=("ev-syn-001",))


# --- over-correction fixes --------------------------------------------------------------------------------------------


def _job_evidence():
    from dealscope.domain.enums import EvidenceKind
    from dealscope.domain.models import JobPostingPayload
    from tests.test_claims import make_ev

    titles = [
        ("ev-job-1", "Data Scientist, FX Quantitative Research", "2026-11-02", "Finance"),
        ("ev-job-2", "Data Scientist, Fraud", "2026-08-06", None),
        ("ev-job-3", "Service Infrastructure Engineer", "2026-08-01", "Customer Success"),
    ]
    return [
        make_ev(eid, EvidenceKind.JOB_POSTING, TARGET, JobPostingPayload(title=t, date_added=d, category=cat))
        for eid, t, d, cat in titles
    ]


def verify_with_jobs(text, ids):
    ci = CaseInput(target_domain=TARGET, competitor_domains=[APEX, CEDAR, ORBIT], deal_thesis="Expand a platform.")
    c = FindingClaim(text=text, claim_type=ClaimType.OBSERVATION, evidence_ids=list(ids))
    res = verify_claims([c], [*build_evidence(), *_job_evidence()], ci, None)
    out = (res.accepted or res.rejected)[0]
    return res.rejection_codes.get(out.claim_id, [])


def test_cited_job_titles_are_masked_not_allegations():
    ids = ("ev-job-1", "ev-job-2")
    good = (
        "Data Scientist, FX Quantitative Research was posted on 2026-11-02 and data scientist,  fraud was posted "
        "on 2026-08-06."
    )
    assert verify_with_jobs(good, ids) == []
    # same words not copied from a cited title stay prohibited
    assert "PROHIBITED_CAUSAL_ALLEGATION" in verify_with_jobs("The target committed fraud.", ids)
    assert "PROHIBITED_CAUSAL_ALLEGATION" in verify_with_jobs("The target committed fraud.", ("ev-job-3",))
    # the title is only masked when its posting is cited
    assert "PROHIBITED_CAUSAL_ALLEGATION" in verify_with_jobs(
        "Data Scientist, Fraud was posted 2026-08-06.", ("ev-job-1",)
    )


@pytest.mark.parametrize(
    "text",
    [
        "The Service Infrastructure team was hiring.",
        "The Developer Experience team posted a role.",
        "Customer Success hiring was observed.",
    ],
)
def test_team_names_are_not_person_names(text):
    assert "UNSUPPORTED_PERSON_NAME" not in codes(text, ids=("ev-syn-002",))


@pytest.mark.parametrize(
    "text",
    [
        "Jane Doe, the former CTO, left the target.",
        "The target was led by Alex Rivera.",
        "CEO Pat Morgan was mentioned.",
        "Sam Ortiz is the VP of engineering.",
        "John Smith posted a role.",
    ],
)
def test_name_cues_still_rejected(text):
    assert "UNSUPPORTED_PERSON_NAME" in codes(text, ids=("ev-syn-003",))


@pytest.mark.parametrize(
    "text",
    [
        "Engineering headcount was down 4% over 6m.",
        "Engineering headcount growth over 6m was negative 4%.",
        "Engineering headcount growth over 6m was minus 4%.",
        "Engineering headcount slipped 4% over 6m.",
        "Engineering headcount was lower by 4% over 6m.",
    ],
)
def test_negative_wording_matches_negative_evidence(text):
    assert accepted(text, ids=("ev-syn-001",))


def test_positive_wording_maps_positive():
    assert accepted("Total headcount was up 11% over 6m.", ids=("ev-syn-001",))
    assert accepted("Total headcount was higher by 11% over 6m.", ids=("ev-syn-001",))
    assert "UNSUPPORTED_NUMBER" in codes("Engineering headcount was up 4% over 6m.", ids=("ev-syn-001",))
    assert "UNSUPPORTED_NUMBER" in codes("Total headcount was down 11% over 6m.", ids=("ev-syn-001",))


@pytest.mark.parametrize(
    "text",
    [
        "Because evidence is limited, treat this as directional.",
        "Due to small sample size, confidence is low.",
        "Confidence is low because posting coverage is limited.",
    ],
)
def test_limitation_causal_language_accepted(text):
    assert "PROHIBITED_CAUSAL_ALLEGATION" not in codes(text, ids=("ev-syn-003",))


@pytest.mark.parametrize(
    "text",
    [
        "Because leadership left, hiring slowed.",
        "Hiring slowed due to a strategy disagreement in the data team.",
        "Due to limited trust in management, a leader departed.",
    ],
)
def test_people_causal_language_still_rejected(text):
    assert "PROHIBITED_CAUSAL_ALLEGATION" in codes(text, ids=("ev-syn-003",))


def test_vague_few_handful_several_are_consistent():
    for word in ("A few", "A handful of", "Several"):
        assert "VAGUE_QUANTITY" in codes(f"{word} engineers left the target.", ids=("ev-syn-003", "ev-syn-007")), word
        assert accepted(f"{word} of the two engineers left the target.", ids=("ev-syn-003", "ev-syn-007")), word


def test_fraud_as_a_business_domain_is_not_an_allegation():
    from dealscope.verification.claims import _CAUSAL

    assert not _CAUSAL.search("open roles targeting fraud detection and FX quantitative research")
    assert not _CAUSAL.search("the fraud prevention team is hiring")
    assert _CAUSAL.search("the company committed fraud")
    assert _CAUSAL.search("fraudulent reporting was observed")
