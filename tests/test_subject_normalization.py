"""Drafting contract: subject_domain is constrained to case domains; topic values are repaired defensively."""

from __future__ import annotations

import json
from decimal import Decimal

from dealscope.agent.synthesis import draft_claims, draft_report_schema, normalize_subject_domain
from dealscope.domain.enums import RunMode
from dealscope.domain.models import CaseInput, CaseState
from dealscope.providers.llm import ScriptedProvider, gemini_schema
from dealscope.verification.claims import verify_claims
from tests.test_claims import APEX, CEDAR, ORBIT, TARGET, build_evidence

DOMAINS = [TARGET, APEX, CEDAR, ORBIT]
BY_ID = {e.evidence_id: e for e in build_evidence()}


def norm(subject, ids):
    return normalize_subject_domain(subject, list(ids), BY_ID, TARGET, DOMAINS)


def test_topic_becomes_target_when_all_evidence_is_target():
    subject, note = norm("engineering_hiring", ["ev-syn-001", "ev-syn-002"])
    assert subject == TARGET and "normalised from 'engineering_hiring'" in note


def test_topic_with_target_and_peer_evidence_stays_unchanged():
    # ev-syn-004 is APEX-only, so no single registered domain relates to every cited record.
    assert norm("technical_capability", ["ev-syn-001", "ev-syn-004"]) == ("technical_capability", None)


def test_topic_normalised_to_single_shared_peer():
    assert norm("organizational_structure", ["ev-syn-004"])[0] == APEX


def test_case_domain_and_foreign_real_domain_never_normalised():
    assert norm(APEX, ["ev-syn-001"]) == (APEX, None)
    assert norm("stripe.com", ["ev-syn-001"]) == ("stripe.com", None)
    assert norm(None, ["ev-syn-001"]) == (None, None)


def test_schema_subject_domain_enum_equals_case_domains():
    props = gemini_schema(draft_report_schema(DOMAINS))["properties"]["claims"]["items"]["properties"]
    assert props["subject_domain"]["enum"] == DOMAINS
    assert "$ref" not in json.dumps(props) and "anyOf" not in json.dumps(props)


def test_end_to_end_topic_subjects_now_verify():
    ci = CaseInput(target_domain=TARGET, competitor_domains=[APEX, CEDAR, ORBIT], deal_thesis="Expand platform safely.")
    state = CaseState(input=ci, mode=RunMode.SYNTHETIC, credit_budget=Decimal(10))
    evidence = build_evidence()
    raw = {
        "claims": [
            {
                "text": "A technical leadership departure is recorded for the target in 2026.",
                "claim_type": "observation",
                "subject_domain": "engineering_hiring",
                "evidence_ids": ["ev-syn-003"],
            },
            {
                "text": "Foreign company claim.",
                "claim_type": "observation",
                "subject_domain": "stripe.com",
                "evidence_ids": ["ev-syn-003"],
            },
        ]
    }
    llm = ScriptedProvider([raw])
    claims = draft_claims(llm, state, evidence, None)
    assert claims[0].subject_domain == TARGET and "normalised" in claims[0].verification_notes[0]
    res = verify_claims(claims, evidence, ci, None)
    assert len(res.accepted) == 1 and claims[0].claim_id == res.accepted[0].claim_id
    assert res.rejection_codes[claims[1].claim_id] and "ENTITY_MISMATCH" in res.rejection_codes[claims[1].claim_id]
