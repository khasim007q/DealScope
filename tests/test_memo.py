from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from dealscope.domain.enums import ClaimType, RunMode, SignalId, SignalState
from dealscope.domain.models import CaseInput, CaseState, FindingClaim, Scorecard, SignalResult
from dealscope.reports.memo import SYNTHETIC_BANNER, build_bundle, deterministic_claims, render_memo
from dealscope.verification.claims import verify_claims
from tests.test_claims import APEX, CEDAR, ORBIT, TARGET, build_evidence

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_report", ROOT / "scripts" / "validate_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.validate


def make_scorecard(coverage=70.0, risk=48.0):
    sigs = [
        SignalResult(
            signal_id=SignalId.S1,
            name="Technical-function trajectory divergence",
            signal_version="v1.0",
            state=SignalState.SCORABLE,
            score=55,
            weight=0.30,
            reason_codes=["TECH_BELOW_TOTAL"],
            evidence_ids=["ev-syn-001"],
            confidence=65,
        ),
        SignalResult(
            signal_id=SignalId.S4,
            name="Critical-role hiring pressure",
            signal_version="v1.0",
            state=SignalState.NOT_SCORED,
            weight=0.20,
            reason_codes=["NO_JOB_DATA"],
            confidence=0,
            limitations=["Job endpoint price unknown."],
        ),
    ]
    return Scorecard(
        signals=sigs,
        risk_score=risk,
        coverage_pct=coverage,
        coverage_label="provisional" if coverage >= 60 else "insufficient_evidence",
        risk_band="Watch",
        evidence_confidence=58.0,
        signal_version="v1.0",
    )


def make_state(mode=RunMode.SYNTHETIC):
    inp = CaseInput(
        target_domain=TARGET,
        competitor_domains=[APEX, CEDAR, ORBIT],
        deal_thesis="Expand an enterprise workflow platform while maintaining reliability.",
        mode=mode,
    )
    return CaseState(
        case_id="demo-case-001",
        input=inp,
        mode=mode,
        credit_budget=Decimal("300"),
        credit_estimated_used=Decimal("12"),
        unavailable_tools={"search_jobs": "UNKNOWN_PRICE_FAIL_CLOSED"},
        open_questions=["Can management provide the engineering org chart?"],
    )


@pytest.fixture
def setup():
    state = make_state()
    evidence = build_evidence()
    return state, evidence


def full_run(state, evidence, scorecard, extra=()):
    claims = deterministic_claims(scorecard, evidence, state.input) + list(extra)
    ver = verify_claims(claims, evidence, state.input, scorecard)
    return claims, ver


def test_deterministic_claims_all_verify(setup):
    state, evidence = setup
    sc = make_scorecard()
    claims = deterministic_claims(sc, evidence, state.input)
    assert claims
    res = verify_claims(claims, evidence, state.input, sc)
    assert not res.rejected, [(c.text, res.rejection_codes[c.claim_id]) for c in res.rejected]
    texts = " ".join(c.text for c in claims)
    assert "Target engineering headcount growth over 6m was -4% versus total headcount growth of 11%." in texts
    assert f"now lists {APEX} as current employer" in texts
    assert any(c.claim_type is ClaimType.QUESTION for c in claims)
    assert res.metrics["grounded_claim_rate"] == 1.0


def test_deterministic_claims_without_scorecard(setup):
    state, evidence = setup
    claims = deterministic_claims(None, evidence, state.input)
    assert not verify_claims(claims, evidence, state.input, None).rejected


def test_memo_synthetic_banner_twice_and_sections(setup):
    state, evidence = setup
    sc = make_scorecard()
    claims, ver = full_run(state, evidence, sc)
    memo = render_memo(state, evidence, ver, sc, narrative_available=False, as_of=AS_OF)
    assert memo.count(SYNTHETIC_BANNER) == 2
    assert memo.lstrip().startswith("> **SYNTHETIC")
    assert memo.rstrip().endswith(f"> **{SYNTHETIC_BANNER}**")
    for n in range(1, 11):
        assert f"## {n}." in memo
    assert "not investment advice" in memo
    assert "no valuation recommendation" in memo
    assert "not a census" in memo
    assert "LLM narrative synthesis was unavailable" in memo
    assert "provisional" in memo
    assert "Evidence confidence" in memo and "58/100" in memo
    assert "v1.0" in memo
    assert "search_jobs" in memo and "UNKNOWN_PRICE_FAIL_CLOSED" in memo
    assert "Can management provide the engineering org chart?" in memo
    assert "not scored" in memo
    assert "ESTIMATED" in memo and "ACTUAL: unknown" in memo
    assert "| " + APEX in memo  # movement matrix present (S5 evidence exists)
    # person evidence: opaque ref + role group, no names
    assert "p-syn-001" in memo and "technical_leadership" in memo


def test_memo_narrative_available_has_no_unavailable_note(setup):
    state, evidence = setup
    sc = make_scorecard()
    _, ver = full_run(state, evidence, sc)
    memo = render_memo(state, evidence, ver, sc, narrative_available=True, as_of=AS_OF)
    assert "narrative synthesis was unavailable" not in memo.split("## 10.")[0]


def test_memo_insufficient_evidence_when_coverage_low(setup):
    state, evidence = setup
    sc = make_scorecard(coverage=45.0, risk=70.0)
    _, ver = full_run(state, evidence, sc)
    memo = render_memo(state, evidence, ver, sc, True, AS_OF)
    assert "INSUFFICIENT EVIDENCE" in memo
    assert "70/100" not in memo
    assert "composite risk score withheld" in memo


def test_memo_composite_shown_when_threshold_met(setup):
    state, evidence = setup
    sc = make_scorecard(coverage=85.0, risk=62.0)
    _, ver = full_run(state, evidence, sc)
    memo = render_memo(state, evidence, ver, sc, True, AS_OF)
    assert "62/100" in memo and "coverage threshold met" in memo and "INSUFFICIENT" not in memo


def test_memo_excludes_rejected_claim_text(setup):
    state, evidence = setup
    sc = make_scorecard()
    bad = [
        FindingClaim(
            text="The target leaked IP because an engineer joined a competitor.",
            claim_type=ClaimType.OBSERVATION,
            evidence_ids=["ev-syn-003"],
        ),
        FindingClaim(
            text="A valuation haircut of 15% is warranted.",
            claim_type=ClaimType.OBSERVATION,
            evidence_ids=["ev-syn-001"],
        ),
        FindingClaim(
            text="Fabricated statement about headcount.", claim_type=ClaimType.OBSERVATION, evidence_ids=["ev-fake"]
        ),
    ]
    _, ver = full_run(state, evidence, sc, bad)
    assert len(ver.rejected) == 3
    memo = render_memo(state, evidence, ver, sc, True, AS_OF)
    findings = memo.split("## 3.")[1].split("## 4.")[0]
    for needle in ("leaked", "haircut", "Fabricated statement", "ev-fake"):
        assert needle not in memo
    assert "Finding 1" in findings
    assert "Rejected claims appendix" in memo
    assert "PROHIBITED_CAUSAL_ALLEGATION" in memo and "UNKNOWN_EVIDENCE_ID" in memo and "PROHIBITED_VALUATION" in memo


def test_memo_counter_evidence_and_alternatives(setup):
    state, evidence = setup
    sc = make_scorecard()
    t11 = FindingClaim(
        text="Observed departures of technical leaders may indicate a continuity risk.",
        claim_type=ClaimType.INTERPRETATION,
        evidence_ids=["ev-syn-003", "ev-syn-007"],
        counter_evidence_ids=["ev-syn-001"],
        subject_domain=TARGET,
    )
    _, ver = full_run(state, evidence, sc, [t11])
    memo = render_memo(state, evidence, ver, sc, True, AS_OF)
    assert "Counter-evidence:" in memo and "`ev-syn-001`" in memo
    assert "organizational restructuring, role consolidation, or normal turnover" in memo.lower()
    assert "qualified" in memo


def test_memo_omits_movement_matrix_without_s5_and_live_mode_labels():
    state = make_state(RunMode.LIVE)
    evidence = [e for e in build_evidence() if e.evidence_id in {"ev-syn-001", "ev-syn-004"}]
    live_ev = [e.model_copy(update={"source_provider": "crustdata", "synthetic": False}) for e in evidence]
    sc = make_scorecard()
    ver = verify_claims(deterministic_claims(sc, live_ev, state.input), live_ev, state.input, sc)
    memo = render_memo(state, live_ev, ver, sc, True, AS_OF)
    assert "LIVE CRUSTDATA" in memo and SYNTHETIC_BANNER not in memo
    assert "no competitor movement evidence was found" in memo


def test_bundle_passes_validate_report_and_is_json(setup):
    state, evidence = setup
    sc = make_scorecard()
    bad = FindingClaim(text="Fabricated.", claim_type=ClaimType.OBSERVATION, evidence_ids=["ev-fake"])
    _, ver = full_run(state, evidence, sc, [bad])
    bundle = build_bundle(state, evidence, ver, sc, narrative_available=False, as_of=AS_OF)
    json.dumps(bundle)
    validate = _load_validator()
    assert validate(bundle) == []
    assert bundle["mode"] == "synthetic" and bundle["report"]["synthetic_banner"] is True
    assert all(c["verification_status"] in {"verified", "qualified"} for c in bundle["report"]["claims"])
    assert bundle["verification"]["metrics"]["rejected"] == 1
    assert bundle["scorecard"]["signal_version"] == "v1.0"
