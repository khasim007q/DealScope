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
  5. numbers in observation/interpretation text must match a cited payload value OF THE SAME KIND (UNSUPPORTED_NUMBER):
     percentages are signed and matched to the growth series of the metric (engineering vs total), scope (target,
     named company, peers) and period the clause names; point gaps to pairwise differences; counts of people /
     postings / peers / records to the cited-record counts (number words included); durations to returned periods /
     lookback.
  6. direction heuristic: clause-level growth words (negation aware) vs. sign of the cited growth percentage
     (DIRECTION_MISMATCH)
  7. years / YYYY-MM / YYYY-MM-DD in the text must be present in cited payload dates, valid_from/valid_to or
     retrieved_at (UNSUPPORTED_DATE)
  8. vague/relative quantity words (a few, a handful, several, many, most, dozens, doubled, ...) ALL need an anchoring
     verified number in the same clause ("most recently" is exempt) (VAGUE_QUANTITY); personal names are rejected when a
     name cue is present (role/title next to a capitalised pair, or a common first name) because evidence is anonymised
     (UNSUPPORTED_PERSON_NAME)
  9. causal connectives (due to, caused by, ...) in material claims are rejected (PROHIBITED_CAUSAL_ALLEGATION),
     except when the connective governs a statement about the evidence itself ("because evidence is limited")
Text copied from cited job-posting titles/categories and cited company names is masked before checks 4, 8 and 9
(a quoted job title is evidence, not an allegation).
Qualification (accepted but labelled): interpretation with a single independence group, interpretation/hypothesis
about continuity or attrition lacking an alternative explanation (default one is added), interpretation that
cites counter-evidence, and any use of synthetic evidence (note only).
"""

from __future__ import annotations

import bisect
import re
import statistics
from collections import Counter
from dataclasses import dataclass
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
    "UNSUPPORTED_PERSON_NAME": "names an individual; evidence is anonymised and cannot support a named person",
    "VAGUE_QUANTITY": "uses a vague or relative quantity (most, dozens, doubled, ...) without an anchoring number",
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
    "UNSUPPORTED_PERSON_NAME": (
        "Refer to observed profiles by role group (for example, one observed technical-leadership profile); "
        "do not name individuals."
    ),
    "VAGUE_QUANTITY": (
        "Replace vague quantities with the exact verified count or percentage from the cited records, or drop them."
    ),
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
_ATTR_SPLIT = re.compile(
    r"[;,]|\.(?!\d)|\b(?:and|but|while|whereas|as|after|although|though|yet|however|with|versus|vs)\b", re.I
)
_ATTRITION_SEGMENT = [
    re.compile(rf"{_PCT}[^.;]{{0,50}}\b{_ATTR_WORDS}\b", re.I),
    re.compile(rf"\b{_ATTR_WORDS}\b[^.;]{{0,50}}{_PCT}", re.I),
]
_ATTRITION_SHARE = re.compile(
    rf"{_PCT}\s+of\s+(?:the\s+)?(?:(?:engineering|technical|total|senior)\s+)?"
    r"(?:team|staff|workforce|engineers|employees|leadership)\b",
    re.I,
)
_ATTRITION_RATE = re.compile(r"\b(?:attrition|turnover|churn)\s+rate\b", re.I)
_NEGATION_BEFORE = re.compile(r"\b(?:not|no|nor|cannot|can't|without|neither)\b[^.;]{0,40}$", re.I)
_NEGATION_WORD = re.compile(r"\b(?:not|no|nor|never|cannot|without|neither|nothing)\b|n't\b", re.I)
_CAUSAL = re.compile(
    r"\b(?:leaked|leaks?|leaking|stole|stolen|steal|theft|poach\w*|misconduct|wrongdoing|"
    r"fraud\w*(?!\s+(?:detection|prevention|risk|analytics|team|teams|models?|engineering|operations|ops)\b)|"
    r"deceiv\w*|"
    r"deceptive)\b|\bIP\s+(?:leak\w*|theft)\b|\btrade\s+secrets?\b|\btechnical\s+debt\b|"
    r"\bbecause\s+(?:an?|the|one|two)\s+(?:engineer|employee|leader|executive|developer|cto)\b|"
    r"(?<!\bnot\s)(?<!\bnever\s)\bproven\b",
    re.I,
)
# Causal connectives (hedged or not): attribution of cause cannot be established from anonymised profile records.
_CAUSAL_CONNECTIVE = re.compile(
    r"\b(?:due\s+to|caused\s+by|because(?:\s+of)?|as\s+a\s+(?:direct\s+)?result\s+of|(?:led|leads|leading)\s+to|"
    r"resulted?\s+in|resulting\s+(?:from|in)|driven\s+by|owing\s+to|attributable\s+to|attributed\s+to|"
    r"stem(?:s|med|ming)?\s+from|triggered\s+by|prompted\s+by|in\s+response\s+to|"
    r"(?:after|following|amid|over)\s+(?:an?\s+|the\s+)?(?:\w+\s+)?"
    r"(?:dispute|conflict|disagreement|falling[- ]out|clash|feud|row|fallout|scandal))\b",
    re.I,
)
_VALUATION = re.compile(
    r"\bvaluations?\b|\bhaircuts?\b|\bdiscount\s+to\s+(?:the\s+)?price\b|\bbuy\b(?!-?side)|\bpass\s+on\s+the\s+deal\b|"
    r"\bshould\s+(?:not\s+)?invest\b|\bprice\s+(?:reduction|adjustment|cut)\b|\bwalk\s+away\b",
    re.I,
)


def _negated_before(text: str, pos: int) -> bool:
    """True when a negation word precedes `pos` in the same clause (within ~45 chars, no contrastive 'but')."""
    clause = re.split(r"[;,]|\.(?!\d)", text[:pos])[-1][-45:]
    return bool(_NEGATION_WORD.search(clause)) and not re.search(r"\bbut\b", clause, re.I)


def _unnegated(pattern: re.Pattern[str], text: str) -> bool:
    return any(not _negated_before(text, m.start()) for m in pattern.finditer(text))


def _attrition_hit(text: str) -> bool:
    if _ATTRITION_SHARE.search(text):
        return True
    # percent and attrition phrase must sit in the same clause (a growth % elsewhere in the sentence is not attrition)
    pos = 0
    for m in [*_ATTR_SPLIT.finditer(text), None]:
        end = m.start() if m else len(text)
        if any(p.search(text[pos:end]) for p in _ATTRITION_SEGMENT):
            return True
        pos = m.end() if m else end
    return any(not _NEGATION_BEFORE.search(text[: m.start()]) for m in _ATTRITION_RATE.finditer(text))


_GOVERNED_END = re.compile(r"[;,.]|\b(?:and|but|so|while)\b", re.I)
_EVIDENCE_TOPIC = re.compile(
    r"\b(?:samples?|sample\s+size|coverage|data|evidence|profiles?|postings?|records?|observations?|sources?|"
    r"visibility|snapshots?|dataset)\b",
    re.I,
)
_PEOPLE_TOPIC = re.compile(
    r"\b(?:depart\w*|left|leav\w*|leaders?|leadership|executives?|ctos?|ceos?|founders?|management|employees?|staff|"
    r"restructur\w*|reorgani[sz]\w*|layoffs?|disputes?|conflicts?|strateg\w*|culture|morale|fired|resign\w*)\b",
    re.I,
)


def _causal_connective_hit(text: str) -> bool:
    """A causal connective whose governed clause is not a statement about the evidence itself
    ('Because evidence is limited', 'Due to small sample size')."""
    for m in _CAUSAL_CONNECTIVE.finditer(text):
        rest = text[m.end() :]
        end = _GOVERNED_END.search(rest)
        governed = rest[: end.start()] if end else rest
        if _EVIDENCE_TOPIC.search(governed) and not _PEOPLE_TOPIC.search(governed):
            continue
        return True
    return False


def _prohibited(
    text: str, claim_type: ClaimType | None = None, has_alternatives: bool = False
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if _attrition_hit(text):
        found.append(("PROHIBITED_ATTRITION_RATE", "attrition rate / share claim is not supported by a profile sample"))
    causal = _unnegated(_CAUSAL, text)
    if _causal_connective_hit(text) and claim_type is not ClaimType.QUESTION:
        # a hypothesis that carries an explicit alternative explanation may speculate; material claims never may
        if claim_type is not ClaimType.HYPOTHESIS or not has_alternatives:
            causal = True
    if causal:
        found.append(("PROHIBITED_CAUSAL_ALLEGATION", "causal, misconduct or overstated-certainty language"))
    if _unnegated(_VALUATION, text):
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


def _period_months(text: str) -> float | None:
    """'6m' / '6 months' -> 6.0; '1y' -> 12.0. Unitless counts as months (provider keys are like '6m')."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*-?\s*([a-z]*)", text.lower())
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2)
    if u.startswith("y"):
        return n * 12
    if u.startswith("w"):
        return n * 12 / 52
    if u.startswith("d"):
        return n * 12 / 365
    return n


def _period_digits(recs: list[EvidenceRecord]) -> set[float]:
    """Periods (in months) of the growth series in the cited company profiles."""
    out: set[float] = set()
    for r in recs:
        if isinstance(r.payload, CompanyProfilePayload):
            for key in [*r.payload.total_growth_pct, *r.payload.engineering_growth_pct]:
                mo = _period_months(key)
                if mo is not None:
                    out.add(mo)
    return out


def _profiles_of(recs: list[EvidenceRecord]) -> list[EvidenceRecord]:
    return [r for r in recs if isinstance(r.payload, CompanyProfilePayload)]


def _count_bounds(recs: list[EvidenceRecord], target: str) -> dict[str, int]:
    """Upper bounds for counts a claim may state, per counted-noun category."""
    people = {r.payload.person_ref for r in recs if isinstance(r.payload, PersonHistoryPayload)}
    jobs = [r.payload for r in recs if isinstance(r.payload, JobPostingPayload)]
    profiles = _profiles_of(recs)
    openings = max(len(jobs), sum((j.number_of_openings or 1) for j in jobs))
    for r in profiles:
        assert isinstance(r.payload, CompanyProfilePayload)
        if r.payload.job_openings_count is not None:
            openings = max(openings, r.payload.job_openings_count)
    employers = {
        (r.payload.current_employer_domain or "").lower()
        for r in recs
        if isinstance(r.payload, PersonHistoryPayload) and r.payload.current_employer_domain
    }
    peers = ({r.subject_domain for r in profiles} | employers) - {target}
    return {
        "person": len(people),
        "profile": max(len(people), len(profiles)),
        "job": openings,
        "role": max(openings, len(people)),
        "peer": len(peers),
        "record": len(recs),
        "team": len(recs),
    }


def _headcounts(recs: list[EvidenceRecord]) -> set[float]:
    out: set[float] = set()
    for r in _profiles_of(recs):
        p = r.payload
        assert isinstance(p, CompanyProfilePayload)
        for v in (p.total_headcount, p.engineering_headcount, p.job_openings_count):
            if v is not None:
                out.add(float(v))
    return out


def _derived_counts(recs: list[EvidenceRecord]) -> set[float]:
    """Plain counts a careful analyst could state from the cited records (never growth percentages)."""
    out: set[float] = {float(len(recs))}
    out.update(float(v) for v in Counter(r.kind for r in recs).values())
    people = {r.payload.person_ref for r in recs if isinstance(r.payload, PersonHistoryPayload)}
    out.add(float(len(people)))
    out.add(float(len({r.subject_domain for r in recs})))
    profiles = _profiles_of(recs)
    out.add(float(len({r.subject_domain for r in profiles})))
    jobs = [r.payload for r in recs if isinstance(r.payload, JobPostingPayload)]
    out.add(float(sum((j.number_of_openings or 1) for j in jobs)))
    out.add(float(sum(1 for j in jobs if j.reposted)))
    out.add(float(len(jobs)))
    out.update(_headcounts(recs))
    return out


def _points_candidates(recs: list[EvidenceRecord]) -> set[float]:
    """Differences between growth values for the same period (percentage-point gaps), plus medians/means."""
    out: set[float] = set()
    by_period: dict[float, list[float]] = {}
    by_field: dict[tuple[str, float], list[float]] = {}
    for r in _profiles_of(recs):
        p = r.payload
        assert isinstance(p, CompanyProfilePayload)
        for fname, d in (("total", p.total_growth_pct), ("eng", p.engineering_growth_pct)):
            for period, v in d.items():
                mo = _period_months(period)
                key = mo if mo is not None else -1.0
                by_period.setdefault(key, []).append(v)
                by_field.setdefault((fname, key), []).append(v)
    for vals in by_period.values():
        for a, b in combinations(vals, 2):
            out.add(abs(a - b))
    for vals in by_field.values():
        if len(vals) >= 2:
            out.add(abs(statistics.median(vals)))
            out.add(abs(statistics.mean(vals)))
    return out


def _close(stated: float, cand: float, decimals: int) -> bool:
    """`stated` equals `cand` rounded to the precision `stated` was written with (sign-sensitive)."""
    return abs(stated - cand) <= 0.5 * 10**-decimals + 1e-9


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
# Company names (so a competitor named without its domain is still entity-checked)
# ---------------------------------------------------------------------------

_COMPANY_SUFFIX = re.compile(r"\b(?:inc|llc|ltd|corp|corporation|co|gmbh|plc|limited)\b\.?", re.I)
NameMap = list[tuple[re.Pattern[str], str]]


def company_names(case_input: CaseInput, evidence: list[EvidenceRecord]) -> NameMap:
    """(pattern, domain) pairs: the domain itself, its label ('stripe' for stripe.com, 'cedar stack' for
    cedar-stack.example) and company-profile names. Patterns are case-insensitive."""
    domains = [d.lower() for d in case_input.all_domains()]
    labels = {d: d.split(".")[0] for d in domains}
    first_counts = Counter(lab.split("-")[0] for lab in labels.values())
    variants: dict[str, set[str]] = {d: set() for d in domains}
    for d, lab in labels.items():
        if len(lab) >= 3:
            variants[d] |= {lab, lab.replace("-", " "), lab.replace("-", "")}
        first = lab.split("-")[0]
        if len(first) >= 4 and first_counts[first] == 1:
            variants[d].add(first)
    for e in evidence:
        p = e.payload
        if isinstance(p, CompanyProfilePayload) and p.name and p.domain.lower() in variants:
            nm = _COMPANY_SUFFIX.sub("", p.name).strip(" ,.").lower()
            if len(nm) >= 3:
                variants[p.domain.lower()].add(nm)
    out: NameMap = []
    for d in domains:
        out.append((re.compile(_domain_pattern(d).pattern, re.I), d))
        for v in sorted(variants[d], key=len, reverse=True):
            body = r"[\s-]+".join(re.escape(t) for t in re.split(r"[\s-]+", v) if t)
            out.append((re.compile(rf"(?<![\w.-]){body}(?![\w-]|\.\w)", re.I), d))
    return out


def _names_in(text: str, names: NameMap) -> list[str]:
    seen: list[str] = []
    for pat, d in names:
        if d not in seen and pat.search(text):
            seen.append(d)
    return seen


def _phrase_regex(phrase: str) -> re.Pattern[str] | None:
    toks = phrase.split()
    if not toks or len(phrase.strip()) < 3:
        return None
    body = r"\s+".join(re.escape(t) for t in toks)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.I)


def mask_evidence_phrases(text: str, cited: list[EvidenceRecord]) -> str:
    """Length-preserving copy of `text` with substrings copied from cited records blanked out: job-posting titles and
    categories, and cited company-profile names (case-insensitive, whitespace-normalised). Quoted titles are evidence,
    not allegations or personal names."""
    phrases: set[str] = set()
    for r in cited:
        p = r.payload
        if isinstance(p, JobPostingPayload):
            phrases.update(x for x in (p.title, p.category) if x)
        elif isinstance(p, CompanyProfilePayload) and p.name:
            phrases.add(p.name)
    out = text
    for phrase in sorted(phrases, key=len, reverse=True):
        rx = _phrase_regex(phrase)
        if rx is not None:
            out = rx.sub(lambda m: " " * len(m.group()), out)
    return out


_NAME_STOP = frozenset(
    """january february march april may june july august september october november december monday tuesday
    wednesday thursday friday saturday sunday series target total engineering technical technology observed senior
    staff principal lead chief head vice president director engineer manager executive leadership officer platform
    product security data machine learning cloud software site reliability infrastructure labs systems technologies
    group capital ventures partners holdings inc llc ltd corp corporation company bank university institute school
    united states kingdom york francisco new north south east west european asian american overall company-wide
    critical thesis diligence synthetic fixture profile profiles posting postings job jobs open current former
    one two three four five six seven eight nine ten""".split()
)
_CAP_PAIR = re.compile(r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b")
_ROLE_TITLES = (
    r"(?:cto|ceo|cfo|coo|ciso|cio|cpo|vp|svp|evp|president|chair(?:man|woman|person)?|founders?|co-founders?|"
    r"head|directors?|chief\s+\w+\s+officer|engineers?|managers?|leads?|architects?)"
)
# role/title cue before a capitalised pair: "former CTO Jane Doe", "CEO Jane Doe", "led by John Smith"
_ROLE_BEFORE = re.compile(
    r"(?i:\b(?:(?:former|ex-|ex|then|current|new|incoming|outgoing)\s+" + _ROLE_TITLES + r"|"
    r"(?:cto|ceo|cfo|coo|ciso|cio|cpo|vp|svp|evp|president|founders?|co-founders?|chair(?:man|woman|person)?)|"
    r"(?:led|headed|run|managed|founded|hired|named|appointed|replaced|according\s+to)\s+by|"
    r"(?:named|appointed|hired|replaced|according\s+to))(?:\s+of\s+\w+)?[,\s]+)$"
)
# role/title cue after a capitalised pair: "Jane Doe, the former CTO", "John Smith (VP)", "Jane Doe is the CEO"
_ROLE_AFTER = re.compile(
    r"(?i:\s*(?:,\s*|\(\s*|\s(?:is|was|as|who\s+(?:is|was))\s+)(?:the\s+|a\s+|an\s+)?"
    r"(?:(?:former|ex-|then|current|new|incoming|outgoing|senior|technical)\s+)*" + _ROLE_TITLES + r"\b)"
)
_TEAM_AFTER = re.compile(
    r"(?i:\s+(?:team|teams|group|org|organi[sz]ation|roles?|hiring|engineering|infrastructure|department|function|"
    r"posting|postings|openings?)\b)"
)
_FIRST_NAMES = frozenset(
    """james john robert michael william david richard joseph thomas charles christopher daniel matthew anthony mark
    donald steven paul andrew joshua kenneth kevin brian george timothy ronald edward jason jeffrey ryan jacob gary
    nicholas eric jonathan stephen larry justin scott brandon benjamin samuel gregory alexander frank patrick raymond
    jack dennis jerry tyler aaron jose adam nathan henry douglas zachary peter kyle walter ethan jeremy harold keith
    christian roger noah gerald carl terry sean austin arthur lawrence jesse dylan bryan joe jordan billy bruce albert
    willie gabriel logan alan juan wayne roy ralph randy eugene vincent russell elijah louis bobby philip johnny
    mary patricia jennifer linda elizabeth barbara susan jessica sarah karen lisa nancy betty margaret sandra ashley
    kimberly emily donna michelle carol amanda dorothy melissa deborah stephanie rebecca sharon laura cynthia kathleen
    amy angela shirley anna brenda pamela emma nicole helen samantha katherine christine debra rachel carolyn janet
    catherine maria heather diane ruth julie olivia joyce virginia victoria kelly lauren christina joan evelyn judith
    megan andrea cheryl hannah jacqueline martha gloria teresa ann sara madison frances kathryn janice jean abigail
    alice judy sophia grace denise amber doris marilyn danielle beverly isabella theresa diana natalie brittany
    charlotte marie kayla alexis lori jane priya raj amit wei li chen yuki hiroshi omar ahmed ali fatima mohammed
    muhammad sanjay anil rahul vikram neha sunita ravi arjun carlos miguel luis sofia elena ivan dmitri olga sergei
    pierre hans lars ingrid""".split()
)

_ROLE_CUE = re.compile(
    r"(?i:\b(?:former|ex-|then|current|ex)\s+(?:cto|ceo|cfo|coo|ciso|cio|vp|svp|head|director|founder|"
    r"chief\s+\w+\s+officer|engineer|manager|lead|architect)(?:\s+of\s+\w+)?[,\s]+)([A-Z][a-z]+)"
)


def person_name_problems(text: str, names: NameMap) -> list[str]:
    """Capitalised personal names ('Jane Doe', 'the former CTO Jane'); evidence is anonymised."""
    low = text.lower()
    covered = [m.span() for pat, _ in names for m in pat.finditer(low)]

    def inside(a: int, b: int) -> bool:
        return any(a < e and b > s for s, e in covered)

    hits: list[str] = []
    for m in _CAP_PAIR.finditer(text):
        w1, w2 = m.group(1), m.group(2)
        if any(w.lower() in _NAME_STOP for w in (*w1.split("-"), *w2.split("-"))) or inside(*m.span()):
            continue
        # a pair is a personal name only with a cue: a role/title next to it, or a common first name
        after = text[m.end() : m.end() + 40]
        if _TEAM_AFTER.match(after):
            continue
        cue = bool(_ROLE_BEFORE.search(text[max(0, m.start() - 45) : m.start()])) or bool(_ROLE_AFTER.match(after))
        if cue or w1.split("-")[0].lower() in _FIRST_NAMES:
            hits.append(m.group())
    for m in _ROLE_CUE.finditer(text):
        w = m.group(1)
        if w.lower() not in _NAME_STOP and not inside(*m.span(1)) and not any(w in h for h in hits):
            hits.append(w)
    return hits


# ---------------------------------------------------------------------------
# Text scanning
# ---------------------------------------------------------------------------

_ID_TOKENS = re.compile(r"\b(?:ev|p|cl|case|job|tr)-[\w-]+\b", re.I)
_DOMAIN_TOKENS = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b", re.I)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SIGNAL_TOKEN = re.compile(r"\bS[1-5]\b")
_NUMBER = re.compile(r"(?<![\w.])[-+\u2212]?\d+(?:,\d{3})*(?:\.\d+)?")
_UNIT = re.compile(r"^\s?-?\s?(months?|mo|m|days?|d|years?|yrs?|y|weeks?|w)\b", re.I)
_PCT_TAIL = re.compile(r"^\s?(?:%|per\s?cent\b)", re.I)
_PTS_TAIL = re.compile(r"^\s?(?:percentage\s+points?|ppts?\b|pp\b|pts\b|points?\b)", re.I)
_STANDARD_DAYS = {7.0, 14.0, 30.0, 60.0, 90.0, 180.0, 365.0}

_NUM_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen"
).split()
_NUM_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_WORD_VALUES: dict[str, float] = {w: float(i) for i, w in enumerate(_NUM_UNITS)}
_WORD_VALUES.update({w: 20.0 + 10 * i for i, w in enumerate(_NUM_TENS)})
_ONES = "|".join(_NUM_UNITS[1:10])
_NUM_WORD_RX = (
    rf"(?:(?:{_ONES})\s+hundred|(?:{'|'.join(_NUM_TENS)})(?:[- ](?:{_ONES}))?|"
    rf"{'|'.join(sorted(_NUM_UNITS, key=len, reverse=True))}|hundred|dozen)"
)
_COUNT_NOUNS: dict[str, str] = {
    "person": (
        r"people|persons?|individuals?|leaders?|engineers?|managers?|executives?|directors?|employees?|developers?|"
        r"staff|hires?|departures?|leavers?|movers?|architects?|officers?|ctos?|founders?"
    ),
    "profile": r"profiles?",
    "job": r"postings?|openings?|vacancies|jobs?|requisitions?",
    "role": r"roles?|positions?",
    "peer": r"peers?|competitors?|companies|company|organi[sz]ations?",
    "record": r"records?|sources?|data\s+points?|observations?",
    "team": r"teams?|groups?|functions?|capabilit(?:y|ies)",
}
_NOUN_RX = "|".join(f"(?:{v})" for v in _COUNT_NOUNS.values())
# up to four filler words between the number and the counted noun; a preposition/conjunction ends the noun phrase
_FILL = r"(?:\s+(?!(?:at|in|on|for|to|from|by|with|over|as|and|or|than)\b)[\w'-]+){0,4}?"
_COUNT_TAIL = re.compile(rf"^{_FILL}\s+({_NOUN_RX})\b", re.I)
_WORD_COUNT = re.compile(rf"\b({_NUM_WORD_RX})\b{_FILL}\s+({_NOUN_RX})\b", re.I)


def _noun_category(noun: str) -> str:
    n = re.sub(r"\s+", " ", noun.lower())
    for cat, rx in _COUNT_NOUNS.items():
        if re.fullmatch(rx.replace(r"\s+", " "), n):
            return cat
    return "record"


def _word_value(words: str) -> float:
    total, cur = 0.0, 0.0
    for tok in re.split(r"[-\s]+", words.lower()):
        if tok == "hundred":
            cur = (cur or 1.0) * 100
        elif tok == "dozen":
            cur = (cur or 1.0) * 12
        elif tok in _WORD_VALUES:
            cur += _WORD_VALUES[tok]
    return total + cur


# --- direction words / clause model ---------------------------------------------------------------------------

_UP = re.compile(
    r"\b(?:grew|grown|grow(?:s|ing)?|increas\w*|rose|rising|expand\w*|rebound\w*|surg\w*|soared|jump\w*|"
    r"doubl\w*|tripl\w*|up(?!\s+(?:to|for|with|from)\b)|higher)\b",
    re.I,
)
_DOWN = re.compile(
    r"\b(?:declin\w*|shr[ia]nk\w*|shrunk|contract\w*|fell|fall\w*|decreas\w*|reduc\w*|dropp?\w*|shed|lost|"
    r"halved|plummet\w*|plung\w*|collaps\w*|tumbl\w*|slash\w*|down|lower|negative|minus|slid|slipped|eroded|dipped)\b",
    re.I,
)
_NO_GROWTH = re.compile(r"\bno\s+(?:net\s+)?(?:growth|increase|expansion)\b", re.I)
_NEG_PREFIX = re.compile(
    r"(?:\b(?:not|never|no|without|hardly|neither|nor)\b|n't\b|\bfailed\s+to\b)\s*(?:\w+\s+){0,2}$", re.I
)
_ENG = re.compile(r"\b(?:engineering|technical|tech|r&d)\b", re.I)
_TOT = re.compile(r"\b(?:total|overall|company-wide|company\s+headcount)\b", re.I)
_PEER_WORD = re.compile(r"\b(?:peers?|competitors?|comparables?|cohort|peer-set)\b", re.I)
_TARGET_WORD = re.compile(r"\b(?:target|the\s+company)\b", re.I)
_CLAUSE_SPLIT = re.compile(
    r"[;,]|\.(?!\d)|\b(?:while|whereas|but|and|versus|vs|compared|against|as|after|although|though|yet|however|than|"
    r"relative\s+to)\b",
    re.I,
)
_PERIOD_IN_CLAUSE = re.compile(r"(\d+)\s*-?\s*(m\b|mo\b|months?\b|y\b|yrs?\b|years?\b)", re.I)


def _mask(text: str) -> str:
    """Length-preserving copy with ids, domains, dates, years and signal tokens blanked out."""
    out = text
    for rx in (_ID_TOKENS, _DOMAIN_TOKENS, _ISO_DATE, _YEAR, _SIGNAL_TOKEN):
        out = rx.sub(lambda m: " " * len(m.group()), out)
    return out


def _clause_spans(masked: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _CLAUSE_SPLIT.finditer(masked):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(masked)))
    return spans


def _dir_words(seg: str) -> tuple[bool, bool, bool, bool]:
    """(up, down, negated_up, negated_down) for a clause; negated forms ('did not grow', 'no growth') are separate."""
    up = down = nup = ndown = False
    for m in _UP.finditer(seg):
        if _NEG_PREFIX.search(seg[: m.start()]):
            nup = True
        else:
            up = True
    for m in _DOWN.finditer(seg):
        if _NEG_PREFIX.search(seg[: m.start()]):
            ndown = True
        else:
            down = True
    if _NO_GROWTH.search(seg):
        nup = True
    return up, down, nup, ndown


@dataclass
class _Clause:
    start: int
    end: int
    own_metrics: frozenset[str]
    metrics: frozenset[str]  # own, else inherited from the previous clause that named one
    inherited: bool
    scope: Any  # None | "peers" | "target" | frozenset[str] of domains
    period: float | None


def _clause_contexts(text: str, masked: str, spans: list[tuple[int, int]], names: NameMap) -> list[_Clause]:
    all_periods = {
        mo for m in _PERIOD_IN_CLAUSE.finditer(masked) if (mo := _period_months(m.group(1) + m.group(2))) is not None
    }
    out: list[_Clause] = []
    prev_metrics: frozenset[str] = frozenset()
    prev_scope: Any = None
    for a, b in spans:
        mseg, seg = masked[a:b], text[a:b]
        own = frozenset([*(["eng"] if _ENG.search(mseg) else []), *(["tot"] if _TOT.search(mseg) else [])])
        low = seg.lower()
        scope: Any = None
        if _PEER_WORD.search(low):
            scope = "peers"
        else:
            doms = frozenset(_names_in(low, names))
            if doms:
                scope = doms
            elif _TARGET_WORD.search(low):
                scope = "target"
        if scope is None:
            scope = prev_scope
        else:
            prev_scope = scope
        pm = _PERIOD_IN_CLAUSE.search(mseg)
        period = _period_months(pm.group(1) + pm.group(2)) if pm else None
        if period is None and len(all_periods) == 1:
            period = next(iter(all_periods))
        if own:
            prev_metrics = own
        out.append(_Clause(a, b, own, own or prev_metrics, not own and bool(prev_metrics), scope, period))
    return out


def _scoped(
    profiles: list[EvidenceRecord], scope: Any, target: str, default_subject: str | None
) -> list[EvidenceRecord]:
    if scope == "peers":
        return [r for r in profiles if r.subject_domain != target]
    if scope == "target":
        return [r for r in profiles if r.subject_domain == target]
    if isinstance(scope, frozenset):
        return [r for r in profiles if r.subject_domain.lower() in scope]
    if default_subject:
        sel = [r for r in profiles if r.subject_domain.lower() == default_subject.lower()]
        if sel:
            return sel
    return [r for r in profiles if r.subject_domain == target] or profiles


def _series_values(
    recs: list[EvidenceRecord], metrics: frozenset[str] | set[str], period: float | None
) -> dict[tuple[str, float], list[float]]:
    groups: dict[tuple[str, float], list[float]] = {}
    for r in recs:
        p = r.payload
        assert isinstance(p, CompanyProfilePayload)
        for metric in metrics:
            series = p.engineering_growth_pct if metric == "eng" else p.total_growth_pct
            for key, v in series.items():
                mo = _period_months(key)
                if period is not None and (mo is None or abs(mo - period) > 0.05):
                    continue
                groups.setdefault((metric, mo if mo is not None else -1.0), []).append(v)
    return groups


def _pct_candidates(groups: dict[tuple[str, float], list[float]]) -> list[float]:
    cands: list[float] = []
    for vals in groups.values():
        cands.extend(vals)
        if len(vals) >= 2:
            cands.extend([statistics.median(vals), statistics.mean(vals)])
    return cands


@dataclass
class _Mention:
    pos: int
    clause: int
    kind: str
    label: str
    ok: bool


_SIGN_WORD = re.compile(r"\b(?:negative|minus)\s+(?:about\s+|roughly\s+|around\s+)?$", re.I)


def _percent_sign(raw: str, seg: str, pos: int) -> int:
    if raw[0] in "-\u2212":
        return -1
    if raw[0] == "+":
        return 1
    if _SIGN_WORD.search(seg[:pos]):  # "negative 4%" / "minus 4%"
        return -1
    before = [m for m in [*_UP.finditer(seg), *_DOWN.finditer(seg)] if m.end() <= pos]
    after = [m for m in [*_UP.finditer(seg), *_DOWN.finditer(seg)] if m.start() >= pos]
    m = max(before, key=lambda x: x.end()) if before else (min(after, key=lambda x: x.start()) if after else None)
    if m is not None and _DOWN.fullmatch(m.group()):
        return -1
    return 1


def _analyze_numbers(
    claim: FindingClaim,
    cited: list[EvidenceRecord],
    target: str,
    extra: list[float],
    names: NameMap,
    lookback: float | None,
) -> tuple[list[_Mention], list[tuple[int, int]], str]:
    text = claim.text
    masked = _mask(text)
    spans = _clause_spans(masked)
    starts = [a for a, _ in spans]
    clauses = _clause_contexts(text, masked, spans, names)
    profiles = _profiles_of(cited)
    bounds = _count_bounds(cited, target)
    counts = _derived_counts(cited)
    heads = _headcounts(cited)
    periods = _period_digits(cited)
    points = _points_candidates(cited)
    extras = [abs(x) for x in extra]
    mentions: list[_Mention] = []

    def cidx(pos: int) -> int:
        return max(0, bisect.bisect_right(starts, pos) - 1)

    for m in _NUMBER.finditer(masked):
        raw = m.group()
        cleaned = raw.replace(",", "").replace("\u2212", "-")
        value = float(cleaned)
        dec = len(cleaned.split(".")[1]) if "." in cleaned else 0
        ci = cidx(m.start())
        cl = clauses[ci]
        tail = masked[m.end() : m.end() + 60]
        if _PCT_TAIL.match(tail):
            signed = _percent_sign(raw, masked[cl.start : cl.end], m.start() - cl.start) * abs(value)
            scoped = _scoped(profiles, cl.scope, target, claim.subject_domain)
            groups = _series_values(scoped, cl.metrics or {"eng", "tot"}, cl.period)
            ok = any(_close(signed, c, dec) for c in _pct_candidates(groups))
            if not ok and cl.inherited:  # metric was only inferred from the previous clause: be lenient on which one
                groups = _series_values(scoped, {"eng", "tot"}, cl.period)
                ok = any(_close(signed, c, dec) for c in _pct_candidates(groups))
            ok = ok or any(_close(abs(signed), e, dec) for e in extras)
            mentions.append(_Mention(m.start(), ci, "percent", raw + "%", ok))
        elif _PTS_TAIL.match(tail):
            ok = any(_close(abs(value), c, dec) for c in (*points, *extras))
            mentions.append(_Mention(m.start(), ci, "points", raw + " points", ok))
        elif (unit := _UNIT.match(tail[:12])) is not None:
            u = unit.group(1).lower()
            mo = _period_months(f"{abs(value):g}{u}")
            ok = (
                (mo is not None and any(abs(mo - p) < 0.05 for p in periods))
                or (u.startswith("d") and abs(value) in _STANDARD_DAYS)
                or (lookback is not None and mo is not None and abs(mo - lookback) < 0.05)
                or any(_close(abs(value), e, dec) for e in extras)
            )
            mentions.append(_Mention(m.start(), ci, "duration", raw + unit.group(0).strip(), ok))
        elif (cm := _COUNT_TAIL.match(masked[m.end() :])) is not None:
            cat = _noun_category(cm.group(1))
            n = abs(value)
            ok = n <= bounds[cat] or (cat in {"person", "profile"} and n in heads)
            mentions.append(_Mention(m.start(), ci, "count", f"{raw} {cm.group(1)}", ok))
        else:
            allowed = [*counts, *extras, 0.0, *([lookback] if lookback is not None else [])]
            ok = any(_close(abs(value), a, dec) for a in allowed)
            mentions.append(_Mention(m.start(), ci, "number", raw, ok))
    for wm in _WORD_COUNT.finditer(masked):
        cat = _noun_category(wm.group(2))
        n = _word_value(wm.group(1))
        ok = n <= bounds[cat] or (cat in {"person", "profile"} and n in heads)
        mentions.append(_Mention(wm.start(), cidx(wm.start()), "count", f"{wm.group(1)} {wm.group(2)}", ok))
    mentions.sort(key=lambda x: x.pos)
    return mentions, spans, masked


def number_problems(
    claim: FindingClaim,
    cited: list[EvidenceRecord],
    target: str,
    extra: list[float],
    names: NameMap | None = None,
    lookback: float | None = None,
) -> list[str]:
    mentions, _, _ = _analyze_numbers(claim, cited, target, extra, names or [], lookback)
    return [m.label for m in mentions if not m.ok]


# --- vague / relative quantities -------------------------------------------------------------------------------

_VAGUE = re.compile(
    r"\b(?:most(?!\s+recent)|majority|many|a\s+few|a\s+handful|dozens?|hundreds|thousands|numerous|several|"
    r"a\s+lot\s+of|lots\s+of|"
    r"significant(?:ly)?|substantial(?:ly)?|doubled|tripled|quadrupled|halved|surged|soared|plummeted|plunged|"
    r"skyrocketed|massive(?:ly)?|huge|sharp(?:ly)?|dramatic(?:ally)?|vast|widespread|exodus|nearly\s+all|almost\s+all|"
    r"virtually\s+all|the\s+bulk|wave\s+of)\b",
    re.I,
)


def vague_problems(text: str, mentions: list[_Mention], spans: list[tuple[int, int]]) -> list[str]:
    starts = [a for a, _ in spans]
    out: list[str] = []
    for m in _VAGUE.finditer(text):
        if _negated_before(text, m.start()):
            continue
        ci = max(0, bisect.bisect_right(starts, m.start()) - 1)
        if any(x.clause == ci and x.ok and x.kind in {"percent", "points", "count", "number"} for x in mentions):
            continue
        out.append(m.group())
    return out


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
# vs total/overall headcount) and exactly one direction (up-words vs down-words, negation aware: "did not grow" /
# "no growth" are negated-up). The cited growth percentages for that metric (optionally restricted to a period named in
# the clause, and to target vs peer records) must not all have the opposite sign. Neutral wording ("growth was -4%") is
# never flagged here; the signed value itself is verified by the number check.


def direction_problems(
    claim: FindingClaim, cited: list[EvidenceRecord], target: str, names: NameMap | None = None
) -> list[str]:
    profiles = _profiles_of(cited)
    if not profiles:
        return []
    text = claim.text
    masked = _mask(text)
    spans = _clause_spans(masked)
    problems: list[str] = []
    for cl in _clause_contexts(text, masked, spans, names or []):
        seg = masked[cl.start : cl.end]
        if len(cl.own_metrics) != 1:
            continue
        up, down, nup, ndown = _dir_words(seg)
        if not (up != down or (not up and not down and nup != ndown)):
            continue
        metric = next(iter(cl.own_metrics))
        label = "engineering" if metric == "eng" else "total"
        groups = _series_values(_scoped(profiles, cl.scope, target, claim.subject_domain), {metric}, cl.period)
        values = [v for vals in groups.values() for v in vals]
        if not values:
            continue
        if up and all(v < 0 for v in values):
            problems.append(f"text says growth but cited {label} growth is negative")
        elif down and all(v > 0 for v in values):
            problems.append(f"text says decline but cited {label} growth is positive")
        elif nup and not up and not down and all(v > 0 for v in values):
            problems.append(f"text says no growth but cited {label} growth is positive")
        elif ndown and not up and not down and all(v < 0 for v in values):
            problems.append(f"text says no decline but cited {label} growth is negative")
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
    names: NameMap,
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

    cited = [by_id[i] for i in dict.fromkeys(claim.evidence_ids) if i in by_id]
    # titles / categories / company names copied from cited records are evidence, not allegations or personal names
    visible = mask_evidence_phrases(claim.text, cited)
    reasons.extend(_prohibited(visible, claim.claim_type, bool(claim.alternative_explanations)))

    counter = [by_id[i] for i in dict.fromkeys(claim.counter_evidence_ids) if i in by_id]

    if cited:
        wanted: list[str] = []
        if claim.subject_domain:
            wanted.append(claim.subject_domain.lower())
        for d in _names_in(claim.text, names):  # registered domains AND company names ('Cedar Stack')
            if d not in wanted:
                wanted.append(d)
        for d in wanted:
            if not any(_relates_to(r, d) for r in cited):
                reasons.append(("ENTITY_MISMATCH", f"no cited evidence relates to {d}"))

    if material:
        people = person_name_problems(visible, names)
        if people:
            reasons.append(("UNSUPPORTED_PERSON_NAME", f"named individual(s) cannot be supported: {', '.join(people)}"))

    if material:
        mentions, spans, _ = _analyze_numbers(
            claim,
            [*cited, *counter] if not unknown else [],
            target,
            _scorecard_numbers(claim, scorecard),
            names,
            float(case_input.lookback_months),
        )
        vague = vague_problems(visible, mentions, spans)
        if vague:
            reasons.append(("VAGUE_QUANTITY", f"vague quantity without anchoring number: {', '.join(vague)}"))

    if cited and not unknown:
        if material:
            bad = [m.label for m in mentions if not m.ok]
            if bad:
                reasons.append(("UNSUPPORTED_NUMBER", f"numbers not found in cited evidence: {', '.join(bad)}"))
            for msg in direction_problems(claim, cited, target, names):
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
    names = company_names(case_input, evidence)
    accepted: list[FindingClaim] = []
    rejected: list[FindingClaim] = []
    codes: dict[str, list[str]] = {}
    histogram: Counter[str] = Counter()
    for claim in claims:
        reasons, _, updated = _verify_one(claim, by_id, case_input, scorecard, names)
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
