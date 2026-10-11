"""Deterministic memo renderer, JSON bundle export and template claims.

Only claims that passed `verify_claims` are rendered as findings. Rejected claims appear in the appendix as codes and
guidance only (never their text). Person evidence is shown as an opaque reference plus role group, never a name.
"""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any

from dealscope.analysis.signals import _in_window, _parse_date, _subtract_months, resolve_as_of
from dealscope.domain.enums import ClaimType, EvidenceKind, RunMode, Severity, SignalId, SignalState
from dealscope.domain.models import (
    CaseInput,
    CaseState,
    CompanyProfilePayload,
    EvidenceRecord,
    FindingClaim,
    JobPostingPayload,
    PersonHistoryPayload,
    Scorecard,
    SignalResult,
)
from dealscope.verification.claims import REJECTION_DESCRIPTIONS, REWRITE_HINTS, VerificationResult

SYNTHETIC_BANNER = "SYNTHETIC DEMO DATA — NOT A REAL COMPANY ASSESSMENT"
LIVE_INDICATOR = "LIVE CRUSTDATA"
MIN_COVERAGE_PCT = 60.0
THRESHOLD_COVERAGE_PCT = 80.0
DISCLAIMER = (
    "This memo is an outside-in organizational diligence aid. It is not investment advice and makes no valuation "
    "recommendation. Public-profile coverage is not a census of the workforce; observed signals are hypotheses "
    "to validate with management and technical diligence, not conclusions."
)
GENERIC_ALTERNATIVES = [
    "Organizational restructuring, role consolidation, or normal turnover.",
    "Reclassification of roles between engineering and other functions, outsourcing, or a deliberate hiring pause.",
    "Incomplete or stale public-profile and provider data; absence of a record is not evidence of absence.",
]
TYPE_LABELS = {
    ClaimType.OBSERVATION: "Observation",
    ClaimType.INTERPRETATION: "Interpretation",
    ClaimType.HYPOTHESIS: "Hypothesis",
    ClaimType.QUESTION: "Question",
}
_SEV_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
MAX_FINDINGS = 12


# ---------------------------------------------------------------------------
# Template claims (no LLM)
# ---------------------------------------------------------------------------


def _fmt(v: float) -> str:
    return f"{round(v, 1):g}"


_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def _count_text(n: int, capital: bool = False) -> str:
    s = _WORDS[n] if 0 <= n <= 10 else str(n)
    return s.capitalize() if capital else s


def _severity_for(sig: SignalResult | None) -> Severity:
    if sig is None or sig.score is None:
        return Severity.LOW
    if sig.score >= 61:
        return Severity.HIGH
    if sig.score >= 41:
        return Severity.MEDIUM
    return Severity.LOW


def _period_order(period: str) -> tuple[int, str]:
    digits = "".join(ch for ch in period if ch.isdigit())
    return (int(digits) if digits else 10**6, period)


def _latest_per_subject(recs: list[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    out: dict[str, EvidenceRecord] = {}
    for r in sorted(recs, key=lambda r: r.retrieved_at):
        out[r.subject_domain] = r
    return out


def deterministic_claims(
    scorecard: Scorecard | None, evidence: list[EvidenceRecord], case_input: CaseInput
) -> list[FindingClaim]:
    """Safe template claims generated straight from evidence/signal results. All pass `verify_claims`."""
    target = case_input.target_domain
    sig: dict[SignalId, SignalResult] = {s.signal_id: s for s in scorecard.signals} if scorecard else {}
    claims: list[FindingClaim] = []

    profiles = _latest_per_subject([e for e in evidence if e.kind is EvidenceKind.COMPANY_PROFILE])
    tgt = profiles.get(target)
    peers = [r for d, r in profiles.items() if d != target]

    # --- S1: trajectory divergence --------------------------------------------------------------------------------
    s1_made = False
    if tgt is not None and isinstance(tgt.payload, CompanyProfilePayload):
        tp = tgt.payload
        common = sorted(set(tp.total_growth_pct) & set(tp.engineering_growth_pct), key=_period_order)
        for period in common[:2]:
            claims.append(
                FindingClaim(
                    text=(
                        f"Target engineering headcount growth over {period} was "
                        f"{_fmt(tp.engineering_growth_pct[period])}% versus total headcount growth of "
                        f"{_fmt(tp.total_growth_pct[period])}%."
                    ),
                    claim_type=ClaimType.OBSERVATION,
                    severity=_severity_for(sig.get(SignalId.S1)),
                    confidence=60,
                    subject_domain=target,
                    related_signals=[SignalId.S1],
                    evidence_ids=[tgt.evidence_id],
                    limitations=["Provider growth percentages only; no department-level history was returned."],
                )
            )
            s1_made = True
            vals = [
                (r, r.payload.engineering_growth_pct[period])
                for r in peers
                if isinstance(r.payload, CompanyProfilePayload) and period in r.payload.engineering_growth_pct
            ]
            if vals:
                nums = [v for _, v in vals]
                if len(vals) >= 2 and min(nums) != max(nums):
                    peer_text = (
                        f"Observed peers' engineering headcount growth over {period} ranged from "
                        f"{_fmt(min(nums))}% to {_fmt(max(nums))}% (median {_fmt(statistics.median(nums))}%)."
                    )
                else:
                    peer_text = f"Observed peers' engineering headcount growth over {period} was {_fmt(nums[0])}%."
                claims.append(
                    FindingClaim(
                        text=peer_text,
                        claim_type=ClaimType.OBSERVATION,
                        severity=Severity.LOW,
                        confidence=55,
                        related_signals=[SignalId.S1],
                        evidence_ids=[r.evidence_id for r, _ in vals],
                        limitations=["Peer cohort is user-selected and may not be comparable."],
                    )
                )
        if s1_made:
            claims.append(
                FindingClaim(
                    text=(
                        "What explains the difference between engineering and total headcount growth, and what "
                        "is management's hiring and restructuring plan for engineering?"
                    ),
                    claim_type=ClaimType.QUESTION,
                    related_signals=[SignalId.S1],
                    evidence_ids=[tgt.evidence_id],
                )
            )

    # --- S2 / S5: person histories --------------------------------------------------------------------------------
    people: dict[str, EvidenceRecord] = {}
    for e in evidence:
        if e.kind is EvidenceKind.PERSON_HISTORY and e.subject_domain == target:
            people.setdefault(e.payload.person_ref, e)  # type: ignore[union-attr]
    # Same lookback window as S2: only intervals ending in [as_of - lookback, as_of] count as recent departures.
    as_of = resolve_as_of(evidence)
    window_start = _subtract_months(as_of, case_input.lookback_months)
    ended = [
        e
        for e in people.values()
        if isinstance(e.payload, PersonHistoryPayload)
        and e.payload.target_end
        and _in_window(_parse_date(e.payload.target_end), window_start, as_of)
    ]
    if ended:
        ends = sorted(
            e.payload.target_end for e in ended if isinstance(e.payload, PersonHistoryPayload) and e.payload.target_end
        )
        span = f"in {ends[0]}" if ends[0] == ends[-1] else f"between {ends[0]} and {ends[-1]}"
        n = len(ended)
        claims.append(
            FindingClaim(
                text=(
                    f"{_count_text(n, True)} observed {_group_label(ended)} "
                    f"{'profile has' if n == 1 else 'profiles have'} "
                    f"a target-company employment interval ending {span}; profile coverage does not establish "
                    "company-wide attrition."
                ),
                claim_type=ClaimType.OBSERVATION,
                severity=_severity_for(sig.get(SignalId.S2)),
                confidence=55,
                subject_domain=target,
                related_signals=[SignalId.S2],
                evidence_ids=[e.evidence_id for e in ended],
                limitations=["Observed profiles are a non-representative sample, not a roster."],
            )
        )
        claims.append(
            FindingClaim(
                text=(
                    "Which critical technical roles changed hands in the period, and are succession and "
                    "knowledge-transfer plans documented?"
                ),
                claim_type=ClaimType.QUESTION,
                related_signals=[SignalId.S2],
                evidence_ids=[e.evidence_id for e in ended],
            )
        )
    for comp in case_input.competitor_domains:
        movers = [
            e
            for e in people.values()
            if isinstance(e.payload, PersonHistoryPayload) and (e.payload.current_employer_domain or "") == comp
        ]
        if movers:
            n = len(movers)
            verb = "lists" if n == 1 else "list"
            claims.append(
                FindingClaim(
                    text=(
                        f"{_count_text(n, True)} observed {_group_label(movers)} {'profile' if n == 1 else 'profiles'} "
                        f"now {verb} {comp} as current employer."
                    ),
                    claim_type=ClaimType.OBSERVATION,
                    severity=Severity.LOW,
                    confidence=55,
                    subject_domain=target,
                    related_signals=[SignalId.S5],
                    evidence_ids=[e.evidence_id for e in movers],
                    limitations=["A job move alone is not evidence of risk; significance depends on role and timing."],
                )
            )

    # --- S4: hiring pressure --------------------------------------------------------------------------------------
    jobs = [e for e in evidence if e.kind is EvidenceKind.JOB_POSTING and e.subject_domain == target]
    if jobs:
        n = len(jobs)
        reposted = sum(1 for j in jobs if isinstance(j.payload, JobPostingPayload) and j.payload.reposted)
        added = sorted(
            j.payload.date_added
            for j in jobs
            if isinstance(j.payload, JobPostingPayload) and j.payload.date_added
        )
        text = (
            f"{_count_text(n, True)} current job {'posting' if n == 1 else 'postings'} for thesis-relevant technical "
            f"roles {'was' if n == 1 else 'were'} observed for the target"
        )
        if reposted:
            text += f", of which {reposted} flagged as reposted"
        if added:
            text += f"; most recently added {added[-1]}"
        claims.append(
            FindingClaim(
                text=text + ".",
                claim_type=ClaimType.OBSERVATION,
                severity=_severity_for(sig.get(SignalId.S4)),
                confidence=55,
                subject_domain=target,
                related_signals=[SignalId.S4],
                evidence_ids=[j.evidence_id for j in jobs],
                limitations=["Open postings are not proof of unfilled critical capability."],
            )
        )
    return claims


def _group_label(recs: list[EvidenceRecord]) -> str:
    groups = {r.payload.role_group for r in recs if isinstance(r.payload, PersonHistoryPayload)}
    if len(groups) == 1:
        return next(iter(groups)).replace("_", "-")
    return "technical"


# ---------------------------------------------------------------------------
# Memo helpers
# ---------------------------------------------------------------------------


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _event_date(e: EvidenceRecord) -> str:
    p = e.payload
    if isinstance(p, PersonHistoryPayload):
        d = p.target_end or e.valid_to or e.valid_from
    elif isinstance(p, JobPostingPayload):
        d = p.date_added or p.date_updated or e.valid_from
    else:
        d = e.valid_to or e.valid_from
    return d or e.retrieved_at.date().isoformat()


def _date_label(e: EvidenceRecord) -> str:
    parts = [f"date {_event_date(e)}"]
    if e.valid_from or e.valid_to:
        parts.append(f"valid {e.valid_from or '?'}..{e.valid_to or '?'}")
    parts.append(f"retrieved {e.retrieved_at.date().isoformat()}")
    return ", ".join(parts)


def _ev_ref(e: EvidenceRecord) -> str:
    tag = "synthetic fixture" if e.synthetic else e.source_provider
    return f"`{e.evidence_id}` ({e.kind.value}; {_date_label(e)}; source: {tag} {e.source_endpoint})"


def _describe(e: EvidenceRecord) -> str:
    p = e.payload
    if isinstance(p, CompanyProfilePayload):
        bits = []
        if p.total_headcount is not None:
            bits.append(f"headcount {p.total_headcount}")
        if p.total_growth_pct:
            bits.append("total growth " + ", ".join(f"{k}: {_fmt(v)}%" for k, v in p.total_growth_pct.items()))
        if p.engineering_growth_pct:
            eng = ", ".join(f"{k}: {_fmt(v)}%" for k, v in p.engineering_growth_pct.items())
            bits.append("engineering growth " + eng)
        return "Company snapshot; " + ("; ".join(bits) if bits else "no growth fields returned")
    if isinstance(p, PersonHistoryPayload):
        bits = [f"ref {p.person_ref}", f"role group {p.role_group}"]
        if p.target_end:
            bits.append(f"target interval ends {p.target_end}")
        if p.current_employer_domain:
            bits.append(f"current employer {p.current_employer_domain}")
        return "; ".join(bits)
    bits = [p.title]
    if p.reposted:
        bits.append("reposted")
    if p.date_added:
        bits.append(f"added {p.date_added}")
    return "Job posting; " + "; ".join(bits)


def _budget_lines(state: CaseState, evidence: list[EvidenceRecord]) -> list[str]:
    actual_known = state.credit_actual_used > 0 or any(e.credit_actual is not None for e in evidence)
    lines = [
        f"- Case credit ceiling (configured): {state.credit_budget}",
        f"- Credits reserved: {state.credit_reserved}",
        f"- Credits consumed, ESTIMATED: {state.credit_estimated_used} (conservative estimate, not a billed amount)",
    ]
    if actual_known:
        lines.append(f"- Credits consumed, ACTUAL (as reported by provider/account): {state.credit_actual_used}")
    else:
        lines.append("- Credits consumed, ACTUAL: unknown (not reported by the provider for this run)")
    if state.credit_unknown_calls:
        lines.append(f"- Calls with unknown billing outcome: {state.credit_unknown_calls}")
    if state.mode is RunMode.SYNTHETIC:
        lines.append("- Fixture mode: no metered Crustdata calls were made.")
    lines.append(
        f"- Planner iterations: {state.iteration_count}; tool calls: {state.tool_call_count}; "
        f"runtime: {state.runtime_seconds_used:.1f}s"
    )
    return lines


def _is_synthetic(state: CaseState, evidence: list[EvidenceRecord]) -> bool:
    return state.mode is RunMode.SYNTHETIC or any(e.synthetic for e in evidence)


def _coverage_text(scorecard: Scorecard) -> tuple[str, str]:
    """Returns (headline, label) for the executive assessment."""
    cov = scorecard.coverage_pct
    if cov < MIN_COVERAGE_PCT or scorecard.risk_score is None:
        return (
            f"**INSUFFICIENT EVIDENCE** — composite risk score withheld (signal coverage {cov:.0f}% is below the "
            f"{MIN_COVERAGE_PCT:.0f}% minimum). Individual scorable signals are shown below.",
            "insufficient_evidence",
        )
    band = f" — band: {scorecard.risk_band}" if scorecard.risk_band else ""
    if cov < THRESHOLD_COVERAGE_PCT:
        return (
            f"Composite risk signal score (provisional): **{scorecard.risk_score:.0f}/100**{band}.",
            "provisional",
        )
    return (
        f"Composite risk signal score (coverage threshold met): **{scorecard.risk_score:.0f}/100**{band}.",
        "coverage_threshold_met",
    )


def _weight_text(w: float) -> str:
    return f"{w * 100:.0f}%" if w <= 1 else f"{w:.0f}%"


# ---------------------------------------------------------------------------
# Memo
# ---------------------------------------------------------------------------


def render_memo(
    case_state: CaseState,
    evidence: list[EvidenceRecord],
    verification: VerificationResult,
    scorecard: Scorecard,
    narrative_available: bool,
    as_of: datetime,
) -> str:
    state = case_state
    inp = state.input
    synthetic = _is_synthetic(state, evidence)
    by_id = {e.evidence_id: e for e in evidence}
    out: list[str] = []

    if synthetic:
        out += [f"> **{SYNTHETIC_BANNER}**", ""]

    # 1 -----------------------------------------------------------------------------------------------------------
    out += [
        f"# DealScope diligence memo: {inp.target_domain}",
        "",
        "## 1. Cover and case context",
        "",
        f"- Mode: **{'SYNTHETIC FIXTURE' if synthetic else LIVE_INDICATOR}**",
        f"- As-of: {as_of.isoformat(timespec='minutes')}",
        f"- Case ID: `{state.case_id}`; run label: {state.run_label}; finish: {state.finish_reason or 'in progress'}",
        f"- Tool calls: {state.tool_call_count}; planner turns: {state.iteration_count}",
        f"- Target: {inp.target_domain}",
        f"- Peer cohort (user-confirmed): {', '.join(inp.competitor_domains)}",
        f"- Lookback: {inp.lookback_months} months",
        f"- Deal thesis: {_cell(inp.deal_thesis)}",
        "",
    ]

    # 2 -----------------------------------------------------------------------------------------------------------
    headline, _label = _coverage_text(scorecard)
    out += [
        "## 2. Executive assessment",
        "",
        headline,
        "",
        f"- Signal coverage: **{scorecard.coverage_pct:.0f}%** of configured signal weight was assessable.",
        f"- Evidence confidence: **{scorecard.evidence_confidence:.0f}/100** (separate from risk; "
        "a higher confidence does not mean higher risk).",
        "- Scores are risk-signal strength for prioritizing diligence, not probabilities of deal failure; "
        "thresholds are unvalidated heuristics.",
        "",
    ]

    # 3 -----------------------------------------------------------------------------------------------------------
    findings = sorted(
        (c for c in verification.accepted if c.claim_type is not ClaimType.QUESTION),
        key=lambda c: (_SEV_ORDER[c.severity], -c.confidence),
    )
    out += ["## 3. Top findings", ""]
    if not narrative_available:
        out += [
            "_Note: LLM narrative synthesis was unavailable for this run; only deterministic, verified findings "
            "are shown._",
            "",
        ]
    if not findings:
        out += ["No claims passed verification; no findings are reported.", ""]
    for i, c in enumerate(findings[:MAX_FINDINGS], 1):
        out += [
            f"### Finding {i} — {TYPE_LABELS[c.claim_type]} (severity: {c.severity.value}, "
            f"verification: {c.verification_status.value if c.verification_status else 'n/a'})",
            "",
            c.text,
            "",
            "- Evidence:",
        ]
        out += [f"  - {_ev_ref(by_id[eid])}" for eid in c.evidence_ids if eid in by_id] or ["  - none cited"]
        if c.counter_evidence_ids:
            out.append("- Counter-evidence:")
            out += [f"  - {_ev_ref(by_id[eid])}" for eid in c.counter_evidence_ids if eid in by_id]
        else:
            out.append("- Counter-evidence: none cited")
        if c.alternative_explanations:
            out.append("- Alternative explanations: " + "; ".join(_cell(a) for a in c.alternative_explanations))
        limits = [*c.limitations, *[n for n in c.verification_notes if not n.startswith("REJECTED")]]
        out.append("- Limitations: " + ("; ".join(_cell(x).rstrip(".") for x in limits) if limits else "none stated"))
        out.append("")
    if len(findings) > MAX_FINDINGS:
        out += [f"_{len(findings) - MAX_FINDINGS} further accepted findings are in the JSON export._", ""]

    # 4 -----------------------------------------------------------------------------------------------------------
    out += [
        "## 4. Signal scorecard",
        "",
        "| Signal | Weight | State | Score | Confidence | Rationale / reason codes |",
        "|---|---:|---|---:|---:|---|",
    ]
    for s in scorecard.signals:
        score = f"{s.score:.0f}" if s.score is not None and s.state is not SignalState.NOT_SCORED else "not scored"
        why = ", ".join(s.reason_codes) if s.reason_codes else "-"
        out.append(
            f"| {s.signal_id.value} {_cell(s.name)} | {_weight_text(s.weight)} | {s.state.value} | {score} | "
            f"{s.confidence:.0f} | {_cell(why)} |"
        )
    out.append("")

    # 5 -----------------------------------------------------------------------------------------------------------
    out += [
        "## 5. Evidence timeline",
        "",
        "| Date | Evidence | Kind | Subject | Detail | Source |",
        "|---|---|---|---|---|---|",
    ]
    for e in sorted(evidence, key=lambda e: (_event_date(e), e.retrieved_at, e.evidence_id)):
        src = f"{'fixture (synthetic)' if e.synthetic else e.source_provider} {e.source_endpoint}"
        out.append(
            f"| {_event_date(e)} | `{e.evidence_id}` | {e.kind.value} | {e.subject_domain} | "
            f"{_cell(_describe(e))} | {_cell(src)} |"
        )
    if not evidence:
        out.append("| - | - | - | - | no evidence collected | - |")
    out.append("")

    # 6 -----------------------------------------------------------------------------------------------------------
    peer_set = set(inp.competitor_domains)
    movers = [
        e
        for e in evidence
        if isinstance(e.payload, PersonHistoryPayload) and (e.payload.current_employer_domain or "") in peer_set
    ]
    out += ["## 6. Competitor / alumni movement matrix", ""]
    if movers:
        groups = sorted({e.payload.role_group for e in movers})  # type: ignore[union-attr]
        out += [
            "| Competitor | " + " | ".join(groups) + " | Evidence |",
            "|---|" + "---:|" * len(groups) + "---|",
        ]
        for comp in inp.competitor_domains:
            rows = {e.payload.person_ref: e for e in movers if e.payload.current_employer_domain == comp}  # type: ignore[union-attr]
            if not rows:
                continue
            cnt = Counter(e.payload.role_group for e in rows.values())  # type: ignore[union-attr]
            out.append(
                f"| {comp} | " + " | ".join(str(cnt.get(g, 0)) for g in groups) + " | "
                + ", ".join(f"`{e.evidence_id}`" for e in rows.values()) + " |"
            )
        out += ["", "Counts are unique observed profiles. A job move alone is not evidence of risk.", ""]
    else:
        out += ["Not shown: no competitor movement evidence was found.", ""]

    # 7 -----------------------------------------------------------------------------------------------------------
    alts = list(
        dict.fromkeys([a for c in verification.accepted for a in c.alternative_explanations] + GENERIC_ALTERNATIVES)
    )
    out += ["## 7. Alternative explanations", ""] + [f"- {_cell(a)}" for a in alts] + [""]

    # 8 -----------------------------------------------------------------------------------------------------------
    questions = list(
        dict.fromkeys(
            [c.text for c in verification.accepted if c.claim_type is ClaimType.QUESTION] + list(state.open_questions)
        )
    )
    out += ["## 8. Priority diligence questions", ""]
    out += [f"{i}. {_cell(q)}" for i, q in enumerate(questions, 1)] or ["No diligence questions were generated."]
    out.append("")

    # 9 -----------------------------------------------------------------------------------------------------------
    kinds = Counter(e.kind.value for e in evidence)
    profiled = {e.subject_domain for e in evidence if e.kind is EvidenceKind.COMPANY_PROFILE}
    m = verification.metrics
    rate = m.get("grounded_claim_rate")
    out += [
        "## 9. Data coverage, limitations and appendix",
        "",
        f"- Evidence records: {len(evidence)} ({', '.join(f'{k}: {v}' for k, v in sorted(kinds.items())) or 'none'}).",
        f"- Company profiles obtained for: {', '.join(sorted(profiled)) or 'none'}; peers without a profile: "
        f"{', '.join(d for d in inp.competitor_domains if d not in profiled) or 'none'}.",
        "- Public-profile coverage is not a census; absence of a record is not evidence of absence.",
        "- Provider growth fields are returned only for fixed periods; no longer series is inferred.",
    ]
    for e in evidence:
        if isinstance(e.payload, CompanyProfilePayload):
            for flag in e.payload.data_quality_flags:
                out.append(f"- Data quality ({e.subject_domain}, `{e.evidence_id}`): {_cell(flag)}")
    for s in scorecard.signals:
        for lim in s.limitations:
            out.append(f"- {s.signal_id.value}: {_cell(lim)}")
    if state.unavailable_tools:
        out.append("- Unavailable tools: " + "; ".join(f"{k} ({_cell(v)})" for k, v in state.unavailable_tools.items()))
    else:
        out.append("- Unavailable tools: none recorded.")
    if state.finish_reason:
        out.append(f"- Run finish reason: {_cell(state.finish_reason)}")
    out += ["", "### Budget usage", ""] + _budget_lines(state, evidence)
    out += [
        "",
        "### Verification summary",
        "",
        f"- Claims checked: {m.get('total', 0)}; verified: {m.get('verified', 0)}; qualified: {m.get('qualified', 0)}; "
        f"rejected: {m.get('rejected', 0)}.",
        f"- Grounded-claim rate (material claims): {'n/a' if rate is None else f'{rate * 100:.0f}%'}; "
        f"unsupported material claims: {m.get('unsupported_material_claims', 0)}.",
        "",
        "### Rejected claims appendix",
        "",
    ]
    if verification.rejected:
        out += ["| Claim | Type | Reason code(s) | Meaning | Safe rewrite guidance |", "|---|---|---|---|---|"]
        for c in verification.rejected:
            codes = verification.rejection_codes.get(c.claim_id, [])
            out.append(
                f"| `{c.claim_id}` | {TYPE_LABELS[c.claim_type]} | {', '.join(codes)} | "
                f"{_cell('; '.join(REJECTION_DESCRIPTIONS.get(x, x) for x in codes))} | "
                f"{_cell(' '.join(REWRITE_HINTS.get(x, '') for x in codes))} |"
            )
        hist = m.get("rejection_reasons", {})
        out += ["", "Rejection counts: " + ", ".join(f"{k}: {v}" for k, v in sorted(hist.items())), ""]
    else:
        out += ["No claims were rejected.", ""]

    # 10 ----------------------------------------------------------------------------------------------------------
    out += [
        "## 10. Method version and disclaimer",
        "",
        f"- Signal method version: `{scorecard.signal_version}`",
        f"- Narrative synthesis: {'available' if narrative_available else 'unavailable (deterministic findings only)'}",
        "",
        f"**Disclaimer:** {DISCLAIMER}",
        "",
    ]
    if synthetic:
        out += [f"> **{SYNTHETIC_BANNER}**", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# JSON bundle
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def build_bundle(
    case_state: CaseState,
    evidence: list[EvidenceRecord],
    verification: VerificationResult,
    scorecard: Scorecard,
    narrative_available: bool,
    as_of: datetime,
) -> dict[str, Any]:
    """JSON-serializable export compatible with scripts/validate_report.py.

    `report.claims` carries accepted claims only; rejected claims are kept for audit under `verification.rejected`.
    """
    synthetic = _is_synthetic(case_state, evidence)
    case = case_state.input.model_dump(mode="json")
    case.update(case_id=case_state.case_id, stage=case_state.stage.value, run_label=case_state.run_label)
    return _jsonable(
        {
            "mode": "synthetic" if synthetic else "live",
            "as_of": as_of.isoformat(),
            "case": case,
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "scorecard": scorecard.model_dump(mode="json"),
            "report": {
                "synthetic_banner": synthetic,
                "synthetic_banner_text": SYNTHETIC_BANNER if synthetic else None,
                "narrative_available": narrative_available,
                "method_version": scorecard.signal_version,
                "claims": [c.model_dump(mode="json") for c in verification.accepted],
            },
            "verification": {
                "metrics": verification.metrics,
                "rejected": [
                    {
                        **c.model_dump(mode="json"),
                        "rejection_codes": verification.rejection_codes.get(c.claim_id, []),
                    }
                    for c in verification.rejected
                ],
            },
            "budget": {
                "credit_budget": case_state.credit_budget,
                "credit_reserved": case_state.credit_reserved,
                "credit_estimated_used": case_state.credit_estimated_used,
                "credit_actual_used": case_state.credit_actual_used,
                "credit_unknown_calls": case_state.credit_unknown_calls,
            },
            "unavailable_tools": case_state.unavailable_tools,
        }
    )
