"""Deterministic claim verifier.

Every `FindingClaim` (whether produced by an LLM or by a template) is checked against the case's evidence
before it may reach the memo. The verifier never calls an LLM and never mutates its inputs.

Checks (rejection codes in parentheses):
  1. material claims need >=1 evidence id (NO_EVIDENCE)
  2. every cited evidence / counter-evidence id must exist in this case (UNKNOWN_EVIDENCE_ID)
  3. entity match: claim.subject_domain and any registered domain named in the text must be related to at least
     one cited record via subject_domain or current_employer_domain (ENTITY_MISMATCH)
  4. prohibited content: attrition-rate claims, causal/misconduct allegations, valuation advice
     (PROHIBITED_ATTRITION_RATE / PROHIBITED_CAUSAL_ALLEGATION / PROHIBITED_VALUATION)
  5. numbers in observation/interpretation text must appear in (or be simply derived from) cited payloads
     (UNSUPPORTED_NUMBER). Derived = abs value, rounding, pairwise differences of growth values for the same period,
     peer medians, counts of cited records / distinct people / distinct peers / summed openings / reposted postings.
  6. direction heuristic: clause-level growth words vs. sign of the cited growth percentage (DIRECTION_MISMATCH)
  7. years / YYYY-MM / YYYY-MM-DD in the text must be present in cited payload dates, valid_from/valid_to or
     retrieved_at (UNSUPPORTED_DATE)
Qualification (accepted but labelled): interpretation with a single independence group, interpretation/hypothesis
about continuity or attrition lacking an alternative explanation (default one is added), interpretation that
cites counter-evidence, and any use of synthetic evidence (note only).
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from itertools import combinations
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dealscope.domain.enums import ClaimType, VerificationStatus
from dealscope.domain.models import (
    CaseInput,
    CompanyProfilePayload,
    EvidenceRecord,
    FindingClaim,
    JobPostingPayload,
    PersonHistoryPayload,
    Scorecard,
)

MATERIAL_TYPES = frozenset({ClaimType.OBSERVATION, ClaimType.INTERPRETATION})

DEFAULT_ALTERNATIVE = "organizational restructuring, role consolidation, or normal turnover"
SINGLE_SOURCE_NOTE = "single-source; not independently corroborated"
SYNTHETIC_NOTE = "synthetic fixture evidence"

REJECTION_DESCRIPTIONS: dict[str, str] = {
    "NO_EVIDENCE": "material claim cites no evidence",
    "UNKNOWN_EVIDENCE_ID": "cites an evidence id that does not exist in this case",
    "ENTITY_MISMATCH": "cited evidence does not relate to the company the claim names",
    "PROHIBITED_ATTRITION_RATE": "states an attrition/turnover rate or share that the sample cannot support",
    "PROHIBITED_CAUSAL_ALLEGATION": "contains a causal, misconduct or overstated-certainty allegation",
    "PROHIBITED_VALUATION": "contains a valuation or deal recommendation",
    "UNSUPPORTED_NUMBER": "contains a number not found in the cited evidence",
    "DIRECTION_MISMATCH": "direction of change contradicts the cited evidence",
    "UNSUPPORTED_DATE": "contains a date/year not found in the cited evidence",
}

REWRITE_HINTS: dict[str, str] = {
    "NO_EVIDENCE": "Cite at least one evidence id, or restate the statement as a hypothesis or diligence question.",
    "UNKNOWN_EVIDENCE_ID": "Cite only evidence ids returned for this case; drop the claim if no record supports it.",
    "ENTITY_MISMATCH": "Cite evidence whose subject_domain (or current employer) is the company named in the claim.",
    "PROHIBITED_ATTRITION_RATE": (
        "Two observed profiles have target-company employment intervals ending in the period; "
        "profile coverage does not establish company-wide attrition."
    ),
    "PROHIBITED_CAUSAL_ALLEGATION": (
        "State only the observed job move (for example, one observed profile now lists a competitor as current "
        "employer) and ask a diligence question; do not infer cause or misconduct."
    ),
    "PROHIBITED_VALUATION": (
        "Remove the valuation or deal recommendation; describe the observed signal and the validation needed."
    ),
    "UNSUPPORTED_NUMBER": "Use only figures present in the cited records, with the exact period returned.",
    "DIRECTION_MISMATCH": "Restate the direction of change exactly as the cited growth figures show it.",
    "UNSUPPORTED_DATE": "Use only dates present in the cited records (valid dates or retrieval date).",
}


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: list[FindingClaim] = Field(default_factory=list)  # verified or qualified
    rejected: list[FindingClaim] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    rejection_codes: dict[str, list[str]] = Field(default_factory=dict)  # claim_id -> codes


# ---------------------------------------------------------------------------
# Prohibited content
# ---------------------------------------------------------------------------

_PCT = r"\d+(?:\.\d+)?\s*%"
_ATTR_WORDS = r"(?:attrition|turnover|churn|left|leave|leaving|departed|departures?|quit|exited)"
_ATTRITION_PATTERNS = [
    re.compile(rf"{_PCT}[^.;]{{0,50}}\b{_ATTR_WORDS}\b", re.I),
    re.compile(rf"\b{_ATTR_WORDS}\b[^.;]{{0,50}}{_PCT}", re.I),
    re.compile(
        rf"{_PCT}\s+of\s+(?:the\s+)?(?:(?:engineering|technical|total|senior)\s+)?"
        r"(?:team|staff|workforce|engineers|employees|leadership)\b",
        re.I,
    ),
]
_ATTRITION_RATE = re.compile(r"\b(?:attrition|turnover|churn)\s+rate\b", re.I)
_NEGATION_BEFORE = re.compile(r"\b(?:not|no|nor|cannot|can't|without|neither)\b[^.;]{0,40}$", re.I)
_CAUSAL = re.compile(
    r"\b(?:leaked|leaks?|leaking|stole|stolen|steal|theft|poach\w*|misconduct|wrongdoing|fraud\w*|deceiv\w*|"
    r"deceptive)\b|\bIP\s+(?:leak\w*|theft)\b|\btrade\s+secrets?\b|\btechnical\s+debt\b|"
    r"\bbecause\s+(?:an?|the|one|two)\s+(?:engineer|employee|leader|executive|developer|cto)\b|"
    r"(?<!\bnot\s)(?<!\bnever\s)\bproven\b",
    re.I,
)
_VALUATION = re.compile(
    r"\bvaluations?\b|\bhaircuts?\b|\bdiscount\s+to\s+(?:the\s+)?price\b|\bbuy\b|\bpass\s+on\s+the\s+deal\b|"
    r"\bshould\s+(?:not\s+)?invest\b|\bprice\s+(?:reduction|adjustment|cut)\b|\bwalk\s+away\b",
    re.I,
)


def _prohibited(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    hit_attr = any(p.search(text) for p in _ATTRITION_PATTERNS)
    if not hit_attr:
        for m in _ATTRITION_RATE.finditer(text):
            if not _NEGATION_BEFORE.search(text[: m.start()]):
                hit_attr = True
                break
    if hit_attr:
        found.append(("PROHIBITED_ATTRITION_RATE", "attrition rate / share claim is not supported by a profile sample"))
    if _CAUSAL.search(text):
        found.append(("PROHIBITED_CAUSAL_ALLEGATION", "causal, misconduct or overstated-certainty language"))
    if _VALUATION.search(text):
        found.append(("PROHIBITED_VALUATION", "valuation or deal recommendation language"))
    return found


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def _relates_to(rec: EvidenceRecord, domain: str) -> bool:
    d = domain.lower()
    if rec.subject_domain.lower() == d:
        return True
    p = rec.payload
    if isinstance(p, PersonHistoryPayload):
        return (p.current_employer_domain or "").lower() == d
    if isinstance(p, CompanyProfilePayload):
        return p.domain.lower() == d
    return False


def _domain_pattern(domain: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w.-]){re.escape(domain.lower())}(?![\w-]|\.\w)")


def _numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numbers_in(v))
    elif isinstance(obj, list | tuple):
        for v in obj:
            out.extend(_numbers_in(v))
    return out


def _period_digits(recs: list[EvidenceRecord]) -> set[float]:
    digits: set[float] = set()
    for r in recs:
        if isinstance(r.payload, CompanyProfilePayload):
            for key in [*r.payload.total_growth_pct, *r.payload.engineering_growth_pct]:
                m = re.match(r"\d+", key)
                if m:
                    digits.add(float(m.group()))
    return digits


def _derived_numbers(recs: list[EvidenceRecord]) -> set[float]:
    """Counts and simple derivations a careful analyst could state from the cited records."""
    out: set[float] = {float(len(recs))}
    kinds = Counter(r.kind for r in recs)
    out.update(float(v) for v in kinds.values())
    people = {r.payload.person_ref for r in recs if isinstance(r.payload, PersonHistoryPayload)}
    out.add(float(len(people)))
    out.add(float(len({r.subject_domain for r in recs})))
    profiles = [r for r in recs if isinstance(r.payload, CompanyProfilePayload)]
    out.add(float(len({r.subject_domain for r in profiles})))
    jobs = [r.payload for r in recs if isinstance(r.payload, JobPostingPayload)]
    out.add(float(sum((j.number_of_openings or 1) for j in jobs)))
    out.add(float(sum(1 for j in jobs if j.reposted)))
    out.add(float(len(jobs)))
    # growth-value derivations
    by_period: dict[str, list[float]] = {}
    by_field: dict[tuple[str, str], list[float]] = {}
    for r in profiles:
        p = r.payload
        assert isinstance(p, CompanyProfilePayload)
        for fname, d in (("total", p.total_growth_pct), ("eng", p.engineering_growth_pct)):
            for period, v in d.items():
                by_period.setdefault(period, []).append(v)
                by_field.setdefault((fname, period), []).append(v)
    for vals in by_period.values():
        for a, b in combinations(vals, 2):
            out.add(abs(a - b))
    for vals in by_field.values():
        if len(vals) >= 2:
            out.add(abs(statistics.median(vals)))
            out.add(abs(statistics.mean(vals)))
    return out


def _matches(n: float, allowed: set[float]) -> bool:
    n = abs(n)
    for a in allowed:
        a = abs(a)
        if abs(a - n) <= 0.051 or (float(n).is_integer() and round(a) == n):
            return True
        if abs(round(a, 1) - n) <= 0.001:
            return True
    return False


def _date_strings(recs: list[EvidenceRecord]) -> list[str]:
    out: list[str] = []
    for r in recs:
        out.extend(s for s in (r.valid_from, r.valid_to, r.retrieved_at.isoformat()) if s)
        p = r.payload
        for attr in ("target_start", "target_end", "date_added", "date_updated"):
            v = getattr(p, attr, None)
            if v:
                out.append(str(v))
    return out


# ---------------------------------------------------------------------------
# Text scanning
# ---------------------------------------------------------------------------

_ID_TOKENS = re.compile(r"\b(?:ev|p|cl|case|job|tr)-[\w-]+\b", re.I)
_DOMAIN_TOKENS = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b", re.I)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SIGNAL_TOKEN = re.compile(r"\bS[1-5]\b")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
_UNIT = re.compile(r"^\s?-?\s?(months?|mo|m|days?|d|years?|yrs?|y|weeks?|w)\b", re.I)
_STANDARD_DAYS = {7.0, 14.0, 30.0, 60.0, 90.0, 180.0, 365.0}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip
_COUNT_WORD = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b(?:\s+[\w-]+){0,4}?\s+"
    r"(profiles?|postings?|openings?|peers?|competitors?|records?)\b",
    re.I,
)


def _max_count_for(noun: str, recs: list[EvidenceRecord], target: str) -> int:
    noun = noun.lower().rstrip("s")
    if noun == "profile":
        return len({r.payload.person_ref for r in recs if isinstance(r.payload, PersonHistoryPayload)})
    if noun in {"posting", "opening"}:
        jobs = [r.payload for r in recs if isinstance(r.payload, JobPostingPayload)]
        return max(len(jobs), sum((j.number_of_openings or 1) for j in jobs))
    if noun in {"peer", "competitor"}:
        return len({r.subject_domain for r in recs if isinstance(r.payload, CompanyProfilePayload)} - {target})
    return len(recs)


def number_problems(claim: FindingClaim, cited: list[EvidenceRecord], target: str, extra: list[float]) -> list[str]:
    text = _ID_TOKENS.sub(" ", claim.text)
    text = _DOMAIN_TOKENS.sub(" ", text)
    text = _ISO_DATE.sub(" ", text)
    text = _YEAR.sub(" ", text)
    text = _SIGNAL_TOKEN.sub(" ", text)
    allowed: set[float] = set()
    for r in cited:
        allowed.update(_numbers_in(r.payload.model_dump()))
    allowed.update(_derived_numbers(cited))
    allowed.update(extra)
    periods = _period_digits(cited)
    problems: list[str] = []
    for m in _NUMBER.finditer(text):
        raw = m.group().replace(",", "")
        value = float(raw)
        unit = _UNIT.match(text[m.end() : m.end() + 12])
        if unit:
            u = unit.group(1).lower()
            if value in periods or (u.startswith("d") and value in _STANDARD_DAYS) or _matches(value, allowed):
                continue
            # lookback window supplied by the case input is accepted via `extra`
            problems.append(m.group() + unit.group(0).strip())
            continue
        if not _matches(value, allowed):
            problems.append(m.group())
    for m in _COUNT_WORD.finditer(text):
        n = _NUMBER_WORDS[m.group(1).lower()]
        if n > _max_count_for(m.group(2), cited, target):
            problems.append(f"{m.group(1)} {m.group(2)}")
    return problems


def date_problems(text: str, recs: list[EvidenceRecord]) -> list[str]:
    dates = _date_strings(recs)
    problems: list[str] = []
    for m in _ISO_DATE.finditer(text):
        token = m.group()
        if not any(d.startswith(token) for d in dates):
            problems.append(token)
    stripped = _ISO_DATE.sub(" ", text)
    for m in _YEAR.finditer(stripped):
        if not any(m.group() in d for d in dates):
            problems.append(m.group())
    return problems


# --- direction heuristic ---------------------------------------------------------------------------------------------
# The text is split into clauses. A clause is checked only if it names exactly one growth metric (engineering/technical
# vs total/overall headcount) and exactly one direction (up-words vs down-words). The cited growth percentages for that
# metric (optionally restricted to a period named in the clause, and to target vs peer records) must not all have the
# opposite sign. Neutral wording ("growth was -4%") is never flagged.

_UP = re.compile(r"\b(?:grew|grown|grow(?:s|ing)?|increas\w*|rose|rising|expand\w*|rebound\w*)\b", re.I)
_DOWN = re.compile(
    r"\b(?:declin\w*|shr[ia]nk\w*|shrunk|contract\w*|fell|fall\w*|decreas\w*|reduc\w*|dropp?\w*|shed|lost)\b", re.I
)
_ENG = re.compile(r"\b(?:engineering|technical|tech|r&d)\b", re.I)
_TOT = re.compile(r"\b(?:total|overall|company-wide|company\s+headcount)\b", re.I)
_CLAUSE_SPLIT = re.compile(r"[;,.]|\b(?:while|whereas|but|and|versus|vs|compared)\b", re.I)
_PERIOD_IN_CLAUSE = re.compile(r"(\d+)\s*-?\s*(?:m\b|mo\b|months?\b)", re.I)


def direction_problems(claim: FindingClaim, cited: list[EvidenceRecord], target: str) -> list[str]:
    profiles = [r for r in cited if isinstance(r.payload, CompanyProfilePayload)]
    if not profiles:
        return []
    problems: list[str] = []
    for clause in _CLAUSE_SPLIT.split(claim.text):
        up, down = bool(_UP.search(clause)), bool(_DOWN.search(clause))
        eng, tot = bool(_ENG.search(clause)), bool(_TOT.search(clause))
        if up == down or eng == tot:
            continue
        if re.search(r"\b(?:peers?|competitors?)\b", clause, re.I):
            scope = [r for r in profiles if r.subject_domain != target]
        elif claim.subject_domain:
            scope = [r for r in profiles if r.subject_domain == claim.subject_domain]
        else:
            scope = [r for r in profiles if r.subject_domain == target] or profiles
        period = _PERIOD_IN_CLAUSE.search(clause)
        values: list[float] = []
        for r in scope:
            p = r.payload
            assert isinstance(p, CompanyProfilePayload)
            series = p.engineering_growth_pct if eng else p.total_growth_pct
            for key, v in series.items():
                if period and not key.lower().startswith(period.group(1)):
                    continue
                values.append(v)
        if not values:
            continue
        if up and all(v < 0 for v in values):
            problems.append(f"text says growth but cited {'engineering' if eng else 'total'} growth is negative")
        elif down and all(v > 0 for v in values):
            problems.append(f"text says decline but cited {'engineering' if eng else 'total'} growth is positive")
    return problems


_CONTINUITY = re.compile(
    r"\b(?:continuity|attrition|departures?|departed|turnover|leaving|retention|succession)\b", re.I
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _scorecard_numbers(claim: FindingClaim, scorecard: Scorecard | None) -> list[float]:
    if scorecard is None:
        return []
    out: list[float] = []
    for s in scorecard.signals:
        if s.signal_id in claim.related_signals:
            out.extend(_numbers_in(s.raw_measure))
            if s.score is not None:
                out.append(float(s.score))
    return out


def _verify_one(
    claim: FindingClaim,
    by_id: dict[str, EvidenceRecord],
    case_input: CaseInput,
    scorecard: Scorecard | None,
) -> tuple[list[tuple[str, str]], list[str], FindingClaim]:
    reasons: list[tuple[str, str]] = []
    notes: list[str] = []
    qualifiers: list[str] = []
    material = claim.claim_type in MATERIAL_TYPES
    target = case_input.target_domain

    if material and not claim.evidence_ids:
        reasons.append(("NO_EVIDENCE", "material claim has no evidence ids"))
    unknown = [i for i in [*claim.evidence_ids, *claim.counter_evidence_ids] if i not in by_id]
    if unknown:
        reasons.append(("UNKNOWN_EVIDENCE_ID", f"unknown evidence ids: {', '.join(sorted(set(unknown)))}"))

    reasons.extend(_prohibited(claim.text))

    cited = [by_id[i] for i in dict.fromkeys(claim.evidence_ids) if i in by_id]
    counter = [by_id[i] for i in dict.fromkeys(claim.counter_evidence_ids) if i in by_id]

    if cited:
        wanted: list[str] = []
        if claim.subject_domain:
            wanted.append(claim.subject_domain.lower())
        for d in case_input.all_domains():
            if _domain_pattern(d).search(claim.text.lower()) and d not in wanted:
                wanted.append(d)
        for d in wanted:
            if not any(_relates_to(r, d) for r in cited):
                reasons.append(("ENTITY_MISMATCH", f"no cited evidence relates to {d}"))

    if cited and not unknown:
        if material:
            bad = number_problems(
                claim,
                [*cited, *counter],
                target,
                [*_scorecard_numbers(claim, scorecard), float(case_input.lookback_months)],
            )
            if bad:
                reasons.append(("UNSUPPORTED_NUMBER", f"numbers not found in cited evidence: {', '.join(bad)}"))
            for msg in direction_problems(claim, cited, target):
                reasons.append(("DIRECTION_MISMATCH", msg))
        bad_dates = date_problems(claim.text, [*cited, *counter])
        if bad_dates:
            reasons.append(("UNSUPPORTED_DATE", f"dates not found in cited evidence: {', '.join(bad_dates)}"))

    alternatives = list(claim.alternative_explanations)
    if not reasons:
        groups = {r.independence_group for r in cited}
        if claim.claim_type is ClaimType.INTERPRETATION and cited and len(groups) <= 1:
            suffix = " (cited records share one independence group)" if len(cited) > 1 else ""
            qualifiers.append(SINGLE_SOURCE_NOTE + suffix)
        if claim.claim_type is ClaimType.INTERPRETATION and counter:
            qualifiers.append("counter-evidence cited; inference qualified accordingly")
        if (
            claim.claim_type in {ClaimType.INTERPRETATION, ClaimType.HYPOTHESIS}
            and _CONTINUITY.search(claim.text)
            and not alternatives
            and not counter
        ):
            alternatives.append(DEFAULT_ALTERNATIVE)
            qualifiers.append(f"no alternative explanation supplied; added default: {DEFAULT_ALTERNATIVE}")
        if any(r.synthetic for r in [*cited, *counter]):
            notes.append(SYNTHETIC_NOTE)

    if reasons:
        status = VerificationStatus.REJECTED
        out_notes = [f"REJECTED[{code}]: {msg}" for code, msg in reasons]
        for code in dict.fromkeys(c for c, _ in reasons):
            out_notes.append(f"Rewrite guidance ({code}): {REWRITE_HINTS[code]}")
    else:
        status = VerificationStatus.QUALIFIED if qualifiers else VerificationStatus.VERIFIED
        out_notes = [*qualifiers, *notes]
    updated = claim.model_copy(
        deep=True,
        update={
            "verification_status": status,
            "verification_notes": [*claim.verification_notes, *out_notes],
            "alternative_explanations": alternatives,
        },
    )
    return reasons, qualifiers, updated


def verify_claims(
    claims: list[FindingClaim],
    evidence: list[EvidenceRecord],
    case_input: CaseInput,
    scorecard: Scorecard | None = None,
) -> VerificationResult:
    by_id = {e.evidence_id: e for e in evidence}
    accepted: list[FindingClaim] = []
    rejected: list[FindingClaim] = []
    codes: dict[str, list[str]] = {}
    histogram: Counter[str] = Counter()
    for claim in claims:
        reasons, _, updated = _verify_one(claim, by_id, case_input, scorecard)
        if reasons:
            rejected.append(updated)
            claim_codes = list(dict.fromkeys(c for c, _ in reasons))
            codes[claim.claim_id] = claim_codes
            histogram.update(claim_codes)
        else:
            accepted.append(updated)
    material_total = sum(1 for c in claims if c.claim_type in MATERIAL_TYPES)
    material_ok = sum(1 for c in accepted if c.claim_type in MATERIAL_TYPES)
    unsupported = sum(1 for c in rejected if c.claim_type in MATERIAL_TYPES)
    metrics: dict[str, Any] = {
        "total": len(claims),
        "verified": sum(1 for c in accepted if c.verification_status is VerificationStatus.VERIFIED),
        "qualified": sum(1 for c in accepted if c.verification_status is VerificationStatus.QUALIFIED),
        "rejected": len(rejected),
        "material_total": material_total,
        "grounded_claim_rate": (material_ok / material_total) if material_total else None,
        "unsupported_material_claims": unsupported,
        "rejection_reasons": dict(histogram),
    }
    return VerificationResult(accepted=accepted, rejected=rejected, metrics=metrics, rejection_codes=codes)


__all__ = [
    "DEFAULT_ALTERNATIVE",
    "MATERIAL_TYPES",
    "REJECTION_DESCRIPTIONS",
    "REWRITE_HINTS",
    "VerificationResult",
    "verify_claims",
]
