"""Deterministic signal scoring S1-S5 and the composite scorecard (thresholds below are the versioned, normative rules).

No LLM, no I/O, no wall-clock reads when ``as_of`` can be derived from the evidence. A score is *risk signal
strength* for prioritising diligence questions, never a probability of deal failure. Every numeric cutoff lives
in :data:`THRESHOLDS` (versioned by ``SIGNAL_SCORING_VERSION``); nothing is inferred at runtime.

Design decisions that go beyond the catalog text (documented here and in the per-signal comments):

* ``LOW_COVERAGE`` signals that still carry a score are members of the assessable set A, but with
  ``THRESHOLDS["low_coverage_weight_factor"]`` (0.5) of their weight, both in the risk average and in
  ``coverage_pct`` - thin evidence neither dominates the composite nor counts as full coverage.
  ``NOT_SCORED`` / ``CONFLICTING`` (no score) signals are never in A.
* Missing data never lowers risk: it lowers coverage and confidence only, and a composite below 60% coverage
  is withheld (``risk_score=None``) rather than reported as zero.
* ``calculated_at`` is derived from ``as_of`` so that identical inputs give identical results.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Final, Literal

from dealscope import SIGNAL_SCORING_VERSION
from dealscope.analysis.peer_benchmark import BenchmarkResult, benchmark_field
from dealscope.domain.enums import EvidenceKind, SignalId, SignalState
from dealscope.domain.models import (
    CaseInput,
    CompanyProfilePayload,
    EvidenceRecord,
    JobPostingPayload,
    PersonHistoryPayload,
    Scorecard,
    SignalResult,
    normalize_domain,
)

# ---------------------------------------------------------------------------
# Configuration (explicit, versioned, commented - never inferred at runtime)
# ---------------------------------------------------------------------------

SIGNAL_NAMES: Final[dict[SignalId, str]] = {
    SignalId.S1: "Technical-function trajectory divergence",
    SignalId.S2: "Critical-role continuity risk",
    SignalId.S3: "Critical capability coverage / senior bench proxy",
    SignalId.S4: "Critical-role hiring pressure",
    SignalId.S5: "Competitor talent movement",
}

# Catalog weights (04-signal-catalog.md). Sum = 1.0.
SIGNAL_WEIGHTS: Final[dict[SignalId, float]] = {
    SignalId.S1: 0.30,
    SignalId.S2: 0.25,
    SignalId.S3: 0.15,
    SignalId.S4: 0.20,
    SignalId.S5: 0.10,
}

# Role groups treated as "critical technical roles" (S2/S3/S4). Weights express seniority/criticality.
CRITICAL_ROLE_GROUPS: Final[frozenset[str]] = frozenset(
    {"technical_leadership", "senior_technical_ic", "security", "data_ml"}
)
ROLE_SENIORITY_WEIGHT: Final[dict[str, float]] = {
    "technical_leadership": 1.0,  # CTO / VP / Head / Director of Engineering, chief architect
    "security": 0.8,
    "data_ml": 0.8,
    "senior_technical_ic": 0.7,  # staff / principal
    "other_technical": 0.3,  # only used by S5 (never by S2)
}

THRESHOLDS: Final[dict[str, float | int]] = {
    # ---- composite / coverage -------------------------------------------------------------------------------
    "coverage_min_publish_pct": 60,  # < 60  -> INSUFFICIENT EVIDENCE, composite withheld
    "coverage_threshold_met_pct": 80,  # >= 80 -> "coverage threshold met" (not "validated"); 60-79 provisional
    "low_coverage_weight_factor": 0.5,  # share of weight a scored LOW_COVERAGE signal contributes to A
    "band_watch_min": 25,  # display labels only: 0-24 Low, 25-49 Watch, 50-69 Elevated, 70+ High
    "band_elevated_min": 50,
    "band_high_min": 70,
    # ---- S1 technical-function trajectory (percentage points, "pp") --------------------------------------------
    "s1_tech_flat_max_pct": 1.0,  # tech growth <= +1.0% counts as "flat or declining"
    "s1_total_growing_min_pct": 3.0,  # total growth >= +3.0% counts as "growing"
    "s1_total_stable_min_pct": -2.0,  # total growth >= -2.0% counts as "stable or growing"
    "s1_gap_modest_pp": 5.0,  # tech - total <= -5pp   -> modest divergence
    "s1_gap_material_pp": 10.0,  # tech - total <= -10pp  -> material divergence
    "s1_peer_modest_pp": 5.0,  # tech - peer median <= -5pp  -> modest shortfall vs peers
    "s1_peer_material_pp": 10.0,  # tech - peer median <= -10pp -> material shortfall ("material margin")
    "s1_corroboration_openings_min": 3,  # critical openings (S4 measure) that count as independent support
    "s1_corroboration_departures_min": 2,  # in-window critical departures (S2 measure) that count as support
    "s1_corroboration_required": 1,  # independent supports needed before any S1 score >= 81
    # ---- S2 critical-role continuity -----------------------------------------------------------------------------
    "s2_min_eligible_profiles": 3,  # fewer observed, eligible profiles -> LOW_COVERAGE
    "s2_min_eligible_share": 0.5,  # eligible / critical-role profiles seen below this -> LOW_COVERAGE
    "s2_concentration_months": 6,  # >= 2 departures within this many months -> concentration bonus
    "s2_concentration_bonus": 10,
    "s2_share_bonus_threshold": 0.5,  # departures / eligible >= 0.5 (with enough profiles) -> small bonus
    "s2_share_bonus": 5,
    "s2_score_cap": 95,
    # ---- S3 capability coverage ---------------------------------------------------------------------------------
    "s3_min_observed_profiles": 3,  # fewer distinct observed current profiles overall -> LOW_COVERAGE
    "s3_min_assessed_share": 0.5,  # assessed capabilities / thesis-critical capabilities below this -> LOW_COVERAGE
    # ---- S4 hiring pressure -------------------------------------------------------------------------------------
    "s4_multiple_openings_min": 3,  # >= 3 critical openings = "multiple"
    "s4_concentration_openings_min": 6,  # >= 6 critical openings = unusual concentration
    "s4_posting_share_unusual": 0.03,  # critical openings / headcount >= 3%
    "s4_persistent_days": 60,  # posting added >= 60 days before as_of (or flagged reposted) = persistent
    "s4_persistent_critical_min": 2,  # >= 2 persistent/reposted critical postings = unusual
    "s4_broad_capabilities_min": 3,  # distinct critical capabilities with openings for the 81+ band
    "s4_corroborating_s1_min_score": 41,  # S1 score at/above which S1 corroborates hiring pressure
    "s4_corroborating_departures_min": 2,  # in-window critical departures that corroborate hiring pressure
    # ---- confidence sub-scores (max points: completeness 30, recency 20, corroboration 20, peers 15, identity 15) ---
    "conf_recency_days_full": 30,
    "conf_recency_days_good": 90,
    "conf_recency_days_ok": 180,
}

# S1/S2/S5 score curves: (weighted count, score), linearly interpolated, clamped at the ends.
_S2_CURVE: Final[Sequence[tuple[float, float]]] = ((0, 5), (1, 25), (2, 45), (3, 65), (4, 80))
_S5_CURVE: Final[Sequence[tuple[float, float]]] = ((0, 5), (1, 30), (2, 50), (3, 70), (4, 80))  # corroborating only

# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})(?:-(\d{2}))?")
_PERIOD_RE = re.compile(r"^\s*(\d+)\s*([a-z]*)\s*$", re.IGNORECASE)


def _t(key: str) -> float:
    return float(THRESHOLDS[key])


def _norm_domain(raw: str | None) -> str:
    try:
        return normalize_domain(raw or "")
    except ValueError:
        return (raw or "").strip().lower()


def _parse_date(raw: str | None) -> tuple[date, bool] | None:
    """Parse "YYYY-MM[-DD...]" -> (date, month_precision). Anything else is unparseable (None)."""
    if not raw:
        return None
    m = _DATE_RE.match(raw)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    day = int(m.group(3)) if m.group(3) else 1
    try:
        return date(year, month, day), m.group(3) is None
    except ValueError:
        return None


def _subtract_months(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(idx, 12)
    month = month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _month_idx(d: date) -> int:
    return d.year * 12 + d.month


def _in_window(parsed: tuple[date, bool] | None, start: date, end: date) -> bool:
    """Inclusive window test. Month-precision dates compare at month granularity (no false precision)."""
    if parsed is None:
        return False
    d, month_precision = parsed
    if month_precision:
        return _month_idx(start) <= _month_idx(d) <= _month_idx(end)
    return start <= d <= end


def _period_sort_key(period: str) -> tuple[int, str]:
    m = _PERIOD_RE.match(period)
    if not m:
        return (10_000, period)
    n, unit = int(m.group(1)), m.group(2).lower()
    months = n * 12 if unit in {"y", "yr", "year", "years"} else n
    return (months, period)


def _interp(x: float, curve: Sequence[tuple[float, float]]) -> float:
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:], strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def _clamp(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def _uniq(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def resolve_as_of(evidence: Sequence[EvidenceRecord], as_of: date | None = None) -> date:
    """Explicit ``as_of`` wins; otherwise the latest ``retrieved_at`` date in the evidence; ``today`` only if the
    evidence set is empty (the one case that cannot be derived)."""
    if as_of is not None:
        return as_of
    if evidence:
        return max(e.retrieved_at for e in evidence).date()
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# Prepared evidence view
# ---------------------------------------------------------------------------


@dataclass
class _Person:
    ref: str
    role_group: str
    capability: str
    start: str | None
    end: str | None
    current_at_target: bool | None
    current_employer_domain: str | None
    evidence_ids: list[str]
    n_records: int
    conflict: bool  # contradictory records (e.g. "currently at target" AND a completed interval)

    @property
    def has_relationship(self) -> bool:
        return bool(self.start or self.end or self.current_at_target is not None)


@dataclass
class _Job:
    key: tuple[str, ...]
    title: str
    role_group: str
    capability: str
    openings: int
    reposted: bool
    date_added: str | None
    url: str | None
    evidence_ids: list[str]
    n_records: int
    has_openings_field: bool


@dataclass
class _Ctx:
    case: CaseInput
    as_of: date
    window_start: date
    all_evidence: list[EvidenceRecord]
    by_id: dict[str, EvidenceRecord]
    target: tuple[EvidenceRecord, CompanyProfilePayload] | None
    peers: dict[str, tuple[EvidenceRecord, CompanyProfilePayload]]
    people: list[_Person]
    jobs: list[_Job]
    duplicate_job_records: int = 0
    critical_caps: frozenset[str] = field(default_factory=frozenset)

    def records(self, ids: Iterable[str]) -> list[EvidenceRecord]:
        return [self.by_id[i] for i in _uniq(ids) if i in self.by_id]


def _latest_per_domain(
    rows: Iterable[tuple[EvidenceRecord, CompanyProfilePayload]],
) -> dict[str, tuple[EvidenceRecord, CompanyProfilePayload]]:
    out: dict[str, tuple[EvidenceRecord, CompanyProfilePayload]] = {}
    for ev, payload in sorted(rows, key=lambda r: (r[0].retrieved_at, r[0].evidence_id)):
        out[_norm_domain(ev.subject_domain)] = (ev, payload)  # later record wins
    return out


def _merge_people(rows: list[tuple[EvidenceRecord, PersonHistoryPayload]]) -> list[_Person]:
    """Collapse profile events to distinct people (by opaque ``person_ref``); latest non-null value wins."""
    by_ref: dict[str, list[tuple[EvidenceRecord, PersonHistoryPayload]]] = defaultdict(list)
    for ev, p in sorted(rows, key=lambda r: (r[0].retrieved_at, r[0].evidence_id)):
        by_ref[p.person_ref].append((ev, p))
    out: list[_Person] = []
    for ref in sorted(by_ref):
        recs = by_ref[ref]
        payloads = [p for _, p in recs]

        def latest(attr: str, payloads: list[PersonHistoryPayload] = payloads) -> object:
            vals = [getattr(p, attr) for p in payloads if getattr(p, attr) is not None]
            return vals[-1] if vals else None

        has_true = any(p.currently_at_target is True for p in payloads)
        has_ended = any(p.currently_at_target is False or p.target_end for p in payloads)
        out.append(
            _Person(
                ref=ref,
                role_group=payloads[-1].role_group,
                capability=payloads[-1].capability,
                start=latest("target_start"),  # type: ignore[arg-type]
                end=latest("target_end"),  # type: ignore[arg-type]
                current_at_target=latest("currently_at_target"),  # type: ignore[arg-type]
                current_employer_domain=latest("current_employer_domain"),  # type: ignore[arg-type]
                evidence_ids=[ev.evidence_id for ev, _ in recs],
                n_records=len(recs),
                conflict=has_true and has_ended,
            )
        )
    return out


def _dedupe_jobs(rows: list[tuple[EvidenceRecord, JobPostingPayload]]) -> tuple[list[_Job], int]:
    """Deduplicate by URL, else by (title, date added). Duplicates keep the max opening count and OR the repost flag."""
    groups: dict[tuple[str, ...], list[tuple[EvidenceRecord, JobPostingPayload]]] = {}
    for ev, j in sorted(rows, key=lambda r: (r[0].retrieved_at, r[0].evidence_id)):
        if j.url and j.url.strip():
            key: tuple[str, ...] = ("url", j.url.strip().lower())
        else:
            key = ("title_date", j.title.strip().lower(), (j.date_added or "").strip())
        groups.setdefault(key, []).append((ev, j))
    jobs: list[_Job] = []
    for key, recs in groups.items():
        payloads = [j for _, j in recs]
        dates = sorted(d for d in (j.date_added for j in payloads) if d)
        jobs.append(
            _Job(
                key=key,
                title=payloads[-1].title,
                role_group=payloads[-1].role_group,
                capability=payloads[-1].capability,
                openings=max(max(1, j.number_of_openings or 1) for j in payloads),
                reposted=any(j.reposted is True for j in payloads),
                date_added=dates[0] if dates else None,
                url=payloads[-1].url,
                evidence_ids=[ev.evidence_id for ev, _ in recs],
                n_records=len(recs),
                has_openings_field=any(j.number_of_openings is not None for j in payloads),
            )
        )
    jobs.sort(key=lambda j: j.key)
    return jobs, len(rows) - len(jobs)


def _build_ctx(case_input: CaseInput, evidence: Sequence[EvidenceRecord], as_of: date | None) -> _Ctx:
    as_of_d = resolve_as_of(evidence, as_of)
    target_domain = _norm_domain(case_input.target_domain)
    peer_domains = {_norm_domain(d) for d in case_input.competitor_domains}

    companies: list[tuple[EvidenceRecord, CompanyProfilePayload]] = []
    people_rows: list[tuple[EvidenceRecord, PersonHistoryPayload]] = []
    job_rows: list[tuple[EvidenceRecord, JobPostingPayload]] = []
    for ev in evidence:
        p = ev.payload
        if ev.kind == EvidenceKind.COMPANY_PROFILE and isinstance(p, CompanyProfilePayload):
            companies.append((ev, p))
        elif ev.kind == EvidenceKind.PERSON_HISTORY and isinstance(p, PersonHistoryPayload):
            people_rows.append((ev, p))
        elif (
            ev.kind == EvidenceKind.JOB_POSTING
            and isinstance(p, JobPostingPayload)
            and _norm_domain(ev.subject_domain) == target_domain
        ):
            job_rows.append((ev, p))

    latest = _latest_per_domain(companies)
    jobs, dup = _dedupe_jobs(job_rows)
    return _Ctx(
        case=case_input,
        as_of=as_of_d,
        window_start=_subtract_months(as_of_d, case_input.lookback_months),
        all_evidence=list(evidence),
        by_id={e.evidence_id: e for e in evidence},
        target=latest.get(target_domain),
        peers={d: v for d, v in latest.items() if d in peer_domains},
        people=_merge_people(people_rows),
        jobs=jobs,
        duplicate_job_records=dup,
        critical_caps=frozenset(case_input.critical_capabilities),
    )


# ---------------------------------------------------------------------------
# Confidence (separate from risk): completeness 30, recency 20, corroboration 20, peers 15, identity 15
# ---------------------------------------------------------------------------


def _recency_points(records: Sequence[EvidenceRecord], as_of: date) -> float:
    if not records:
        return 0.0
    newest = max(r.retrieved_at for r in records).date()
    age = max(0, (as_of - newest).days)
    if age <= _t("conf_recency_days_full"):
        return 20.0
    if age <= _t("conf_recency_days_good"):
        return 14.0
    if age <= _t("conf_recency_days_ok"):
        return 8.0
    return 3.0


def _corroboration_points(records: Sequence[EvidenceRecord]) -> float:
    groups = len({r.independence_group for r in records})
    return {0: 0.0, 1: 6.0, 2: 13.0}.get(groups, 20.0)


def _peer_points(strength: str, n: int) -> float:
    if strength == "usable":
        return 15.0
    if strength == "weak":
        return float(min(10, 4 * n))
    return 0.0


@dataclass
class _Conf:
    completeness: float = 0.0
    recency: float = 0.0
    corroboration: float = 0.0
    peer: float | None = None  # None -> not applicable to this signal (rescaled)
    identity: float = 0.0

    def breakdown(self) -> dict[str, float]:
        out = {
            "field_completeness": round(self.completeness, 1),
            "recency": round(self.recency, 1),
            "independent_corroboration": round(self.corroboration, 1),
        }
        if self.peer is not None:
            out["peer_comparability"] = round(self.peer, 1)
        out["identity_resolution"] = round(self.identity, 1)
        out["applicable_max"] = 100.0 if self.peer is not None else 85.0
        return out

    def total(self) -> float:
        b = self.breakdown()
        pts = sum(v for k, v in b.items() if k != "applicable_max")
        return round(min(100.0, pts / b["applicable_max"] * 100.0), 1)


# ---------------------------------------------------------------------------
# Result construction
# ---------------------------------------------------------------------------


def _result(
    ctx: _Ctx,
    sid: SignalId,
    state: SignalState,
    score: float | None,
    *,
    raw: dict[str, object],
    reasons: list[str],
    evidence_ids: Iterable[str],
    conf: _Conf,
    limitations: list[str],
    benchmark: dict[str, object] | None = None,
) -> SignalResult:
    ids = _uniq(evidence_ids)
    lims = list(limitations)
    if any(e.synthetic for e in ctx.all_evidence):
        lims.append("synthetic fixture data")
    return SignalResult(
        signal_id=sid,
        name=SIGNAL_NAMES[sid],
        signal_version=SIGNAL_SCORING_VERSION,
        state=state,
        score=None if score is None else _clamp(score),
        weight=SIGNAL_WEIGHTS[sid],
        raw_measure=raw,
        benchmark=benchmark or {},
        reason_codes=_uniq(reasons),
        evidence_ids=ids,
        confidence=conf.total(),
        confidence_breakdown=conf.breakdown(),
        limitations=_uniq(lims),
        calculated_at=datetime.combine(ctx.as_of, time.min, tzinfo=UTC),
    )


def _not_scored(
    ctx: _Ctx,
    sid: SignalId,
    reason: str,
    raw: dict[str, object],
    limitations: list[str],
    evidence_ids: Iterable[str] = (),
) -> SignalResult:
    """Missing evidence is reported as unavailable (never 0, never 'no risk'); confidence is 0."""
    return _result(
        ctx,
        sid,
        SignalState.NOT_SCORED,
        None,
        raw=raw,
        reasons=[reason],
        evidence_ids=evidence_ids,
        conf=_Conf(peer=0.0 if sid == SignalId.S1 else None),
        limitations=limitations,
    )


# ---------------------------------------------------------------------------
# Shared measures (also used for cross-signal corroboration)
# ---------------------------------------------------------------------------


@dataclass
class _S2Analysis:
    critical: list[_Person]
    eligible: list[_Person]
    departures: list[_Person]
    conflicts: list[_Person]
    unparseable_end: list[_Person]
    missing_end: list[_Person]
    weighted: float


def _s2_analysis(ctx: _Ctx) -> _S2Analysis:
    critical = [p for p in ctx.people if p.role_group in CRITICAL_ROLE_GROUPS]
    eligible = [p for p in critical if p.has_relationship]
    conflicts = [p for p in eligible if p.conflict]
    usable = [p for p in eligible if not p.conflict]
    departures: list[_Person] = []
    unparseable: list[_Person] = []
    missing: list[_Person] = []
    for p in usable:
        if not p.end:
            missing.append(p)  # a missing target_end is NOT a departure
            continue
        parsed = _parse_date(p.end)
        if parsed is None:
            unparseable.append(p)
        elif _in_window(parsed, ctx.window_start, ctx.as_of):
            departures.append(p)
    weighted = sum(ROLE_SENIORITY_WEIGHT[p.role_group] for p in departures)
    return _S2Analysis(critical, eligible, departures, conflicts, unparseable, missing, weighted)


@dataclass
class _JobStats:
    total_postings: int
    critical: list[_Job]
    critical_openings: int
    reposted: int
    persistent_or_reposted: int
    capabilities: list[str]
    undated_critical: int


def _is_critical_job(job: _Job, caps: frozenset[str]) -> bool:
    if job.role_group == "non_technical":
        return False
    return job.capability in caps or job.role_group in CRITICAL_ROLE_GROUPS


def _job_stats(ctx: _Ctx) -> _JobStats:
    critical = [j for j in ctx.jobs if _is_critical_job(j, ctx.critical_caps)]
    persistent = 0
    undated = 0
    for j in critical:
        parsed = _parse_date(j.date_added)
        old = parsed is not None and (ctx.as_of - parsed[0]).days >= _t("s4_persistent_days")
        if parsed is None:
            undated += 1
        if j.reposted or old:
            persistent += 1
    return _JobStats(
        total_postings=len(ctx.jobs),
        critical=critical,
        critical_openings=sum(j.openings for j in critical),
        reposted=sum(1 for j in critical if j.reposted),
        persistent_or_reposted=persistent,
        capabilities=sorted({j.capability for j in critical}),
        undated_critical=undated,
    )


# ---------------------------------------------------------------------------
# S1 - Technical-function trajectory divergence (30%)
# ---------------------------------------------------------------------------


@dataclass
class _S1Period:
    period: str
    tech: float
    total: float
    gap: float
    bench: BenchmarkResult
    score: float
    level: str
    reasons: list[str]
    tech_contracting_total_stable: bool
    peer_material: bool
    gap_material: bool


def _s1_period(period: str, tech: float, total: float, bench: BenchmarkResult) -> _S1Period:
    gap = tech - total
    delta = bench.delta_vs_median
    peer_material = peer_modest = False
    if delta is not None and bench.strength == "usable":
        # "Material" = >= 10pp below the peer median, or below Q1 together with a >= 5pp shortfall.
        peer_material = delta <= -_t("s1_peer_material_pp") or bool(
            bench.below_q1 and delta <= -_t("s1_peer_modest_pp")
        )
        peer_modest = delta <= -_t("s1_peer_modest_pp")
    elif delta is not None and bench.strength == "weak":
        # Weak benchmark (<3 usable peers): only a large shortfall counts, and only as "modest".
        peer_modest = delta <= -_t("s1_peer_material_pp")

    flat_or_down = tech <= _t("s1_tech_flat_max_pct")
    contraction = tech < 0
    total_growing = total >= _t("s1_total_growing_min_pct")
    total_stable = total >= _t("s1_total_stable_min_pct")
    gap_modest = gap <= -_t("s1_gap_modest_pp")
    gap_material = gap <= -_t("s1_gap_material_pp")
    reasons: list[str] = []
    tag = period.upper()

    if flat_or_down and total_growing and (contraction or gap_modest):
        # 41-60: technical function flat/declining while total headcount grows.
        score = 45.0 + (5 if gap_material else 0) + (5 if peer_material else 0) + (3 if contraction else 0)
        level = "divergence"
        reasons.append(f"TECH_FLAT_OR_DECLINING_TOTAL_GROWING_{tag}")
    elif contraction and total_stable:
        score = 45.0 + (5 if peer_material else 0)  # tech contracting while total is stable (single period: 41-50)
        level = "tech_contraction_total_stable"
        reasons.append(f"TECH_CONTRACTION_TOTAL_STABLE_{tag}")
    elif contraction:
        score = 25.0  # total company shrinking too: consistent with company-wide change, not tech-specific
        level = "company_wide_contraction"
        reasons.append(f"CONTRACTION_CONSISTENT_WITH_TOTAL_{tag}")
    elif peer_material:
        score = 45.0  # 41-60 "below peer median by a material margin"
        level = "below_peers_material"
        reasons.append(f"BELOW_PEER_MEDIAN_MATERIAL_{tag}")
    elif gap_material:
        score = 35.0  # modest divergence: tech still growing but far behind total
        level = "gap_material"
        reasons.append(f"TECH_TOTAL_GAP_MATERIAL_{tag}")
    elif gap_modest or peer_modest:
        score = 25.0 + (5 if gap_modest and peer_modest else 0)
        level = "modest_divergence"
        reasons.append(f"MODEST_DIVERGENCE_{tag}")
    elif gap >= 0 and bench.strength == "usable" and (delta is None or delta >= 0):
        score = 5.0  # stable/strong relative to total and to usable peers
        level = "stable"
        reasons.append(f"TECH_STABLE_OR_STRONG_{tag}")
    else:
        score = 10.0  # no concern observed, but no usable peer verification
        level = "no_concern_unverified_vs_peers"
        reasons.append(f"NO_DIVERGENCE_OBSERVED_{tag}")
    return _S1Period(
        period, tech, total, gap, bench, score, level, reasons,
        tech_contracting_total_stable=contraction and total_stable,
        peer_material=peer_material,
        gap_material=gap_material,
    )  # fmt: skip


def _fmt_pct(v: float) -> str:
    return f"{v:+.1f}%"


def score_s1(case_input: CaseInput, evidence: Sequence[EvidenceRecord], as_of: date | None = None) -> SignalResult:
    ctx = _build_ctx(case_input, evidence, as_of)
    sid = SignalId.S1
    base_lims = [
        "Growth percentages are the periods the provider returned; no longer series is reconstructed.",
        "Department-level fields describe headcount mix, not deal-relevant capability or work quality.",
    ]
    if ctx.target is None:
        return _not_scored(
            ctx, sid, "NO_COMPANY_DATA", {"summary": "No target company profile evidence."},
            [*base_lims, "No target company profile was available."],
        )  # fmt: skip
    tev, tp = ctx.target
    context = {
        "total_growth_pct": dict(tp.total_growth_pct),
        "engineering_growth_pct": dict(tp.engineering_growth_pct),
        "total_headcount": tp.total_headcount,
    }
    if not tp.engineering_growth_pct:
        return _not_scored(
            ctx, sid, "NO_DEPARTMENT_DATA",
            {"summary": "Engineering/R&D growth was not returned; overall growth shown as context only.", **context},
            [
                *base_lims,
                "Overall company growth is not proof of technical-function shrinkage; S1 is not scored "
                "without department-level fields.",
            ],
            [tev.evidence_id],
        )  # fmt: skip
    shared = sorted(set(tp.engineering_growth_pct) & set(tp.total_growth_pct), key=_period_sort_key)
    if not shared:
        return _not_scored(
            ctx, sid, "NO_SHARED_PERIOD",
            {"summary": "Engineering and total growth were not returned for an identical period.", **context},
            [*base_lims, "tech-vs-total gap is only computed for identical periods."],
            [tev.evidence_id],
        )  # fmt: skip

    periods: list[_S1Period] = []
    peer_ids: list[str] = []
    for p in shared:
        peer_payloads = [pl for _, pl in ctx.peers.values()]
        bench = benchmark_field(tp, peer_payloads, "engineering_growth_pct", p)
        for dom, (pev, _) in ctx.peers.items():
            if dom in {_norm_domain(d) for d in bench.peer_values}:
                peer_ids.append(pev.evidence_id)
        periods.append(_s1_period(p, tp.engineering_growth_pct[p], tp.total_growth_pct[p], bench))

    # --- aggregation across the returned periods --------------------------------------------------------------
    s2a = _s2_analysis(ctx)
    jobs = _job_stats(ctx)
    supports: list[str] = []
    if jobs.critical_openings >= _t("s1_corroboration_openings_min"):
        supports.append("CRITICAL_VACANCIES")
    if len(s2a.departures) >= _t("s1_corroboration_departures_min"):
        supports.append("CRITICAL_DEPARTURES_IN_WINDOW")

    reasons = [r for per in periods for r in per.reasons]
    contracting = [per for per in periods if per.tech_contracting_total_stable]
    multi = len(contracting) >= 2
    if multi:
        # 61-80: technical contraction across more than one returned period while total is stable/growing.
        score = 65.0
        score += 5 if any(per.peer_material for per in contracting) else 0
        score += 5 if all(per.gap_material for per in contracting) else 0
        reasons.append("MULTI_PERIOD_TECH_CONTRACTION")
        if len(supports) >= _t("s1_corroboration_required"):
            # 81-100 only with multi-period divergence PLUS independent supporting signals.
            score = 81.0 + 4.0 * (len(supports) - 1)
            reasons.extend(f"CORROBORATED_BY_{s}" for s in supports)
    else:
        score = max(per.score for per in periods)
        if sum(1 for per in periods if per.score >= 41) >= 2:
            score = min(60.0, score + 5)
            reasons.append("DIVERGENCE_IN_MULTIPLE_PERIODS")
    if len(periods) == 1:
        reasons.append("SINGLE_PERIOD")

    best = max(periods, key=lambda per: _peer_points(per.bench.strength, per.bench.stats.n))
    strength = best.bench.strength
    if strength == "insufficient":
        reasons.append("NO_PEER_BENCHMARK")
    elif strength == "weak":
        reasons.append("PEER_BENCHMARK_WEAK")

    lims = list(base_lims)
    if len(periods) == 1:
        lims.append("single returned period; no trend inferred")
    else:
        lims.append("Returned growth periods overlap in time and are not independent observations.")
    if strength != "usable":
        lims.append("Fewer than 3 usable, comparable peers; peer comparison is low confidence.")
    if score >= 61 and not multi:
        lims.append("Score capped below 61: a single returned period cannot establish multi-period divergence.")

    raw: dict[str, object] = {
        "periods_used": shared,
        "periods": {
            per.period: {
                "tech_growth_pct": per.tech,
                "total_growth_pct": per.total,
                "tech_vs_total_gap_pp": round(per.gap, 2),
                "peer_median_pct": per.bench.stats.median,
                "tech_vs_peer_median_pp": (
                    None if per.bench.delta_vs_median is None else round(per.bench.delta_vs_median, 2)
                ),
                "period_score": per.score,
                "pattern": per.level,
            }
            for per in periods
        },
        "supporting_signals": supports,
    }  # fmt: skip
    for per in periods:
        raw[f"tech_growth_{per.period}"] = per.tech
        raw[f"total_growth_{per.period}"] = per.total
        raw[f"tech_vs_total_gap_{per.period}"] = round(per.gap, 2)
    peer_txt = (
        f"; peer median engineering {_fmt_pct(best.bench.stats.median)} (n={best.bench.stats.n})"
        if best.bench.stats.median is not None
        else "; no peer comparison available"
    )
    first = periods[0]
    raw["summary"] = (
        f"{first.period}: engineering {_fmt_pct(first.tech)} vs total {_fmt_pct(first.total)} "
        f"(gap {first.gap:+.1f} pp){peer_txt}." + (f" {len(periods)} periods returned." if len(periods) > 1 else "")
    )
    benchmark = {per.period: per.bench.as_dict() for per in periods}

    ids = [tev.evidence_id, *peer_ids]
    used = ctx.records(ids)
    conf = _Conf(
        completeness=10.0 + (10.0 if tp.total_growth_pct else 0.0) + 5.0 + (5.0 if len(shared) >= 2 else 0.0),
        recency=_recency_points(used, ctx.as_of),
        corroboration=_corroboration_points(used),
        peer=_peer_points(strength, best.bench.stats.n),
        identity=15.0,  # exact normalized-domain match for target and peers
    )
    return _result(
        ctx, sid, SignalState.SCORABLE, score, raw=raw, reasons=reasons, evidence_ids=ids,
        conf=conf, limitations=lims, benchmark=benchmark,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# S2 - Critical-role continuity risk (25%)
# ---------------------------------------------------------------------------


def score_s2(case_input: CaseInput, evidence: Sequence[EvidenceRecord], as_of: date | None = None) -> SignalResult:
    ctx = _build_ctx(case_input, evidence, as_of)
    sid = SignalId.S2
    base_lims = [
        "Counts distinct observed profiles only; this is not a company attrition rate.",
        "A missing target end date is not treated as a departure.",
    ]
    window = {"start": ctx.window_start.isoformat(), "end": ctx.as_of.isoformat()}
    if not ctx.people:
        return _not_scored(
            ctx, sid, "NO_PERSON_DATA", {"summary": "No person work-history evidence.", "window": window},
            [*base_lims, "No person evidence was available; absence of profiles is not absence of departures."],
        )  # fmt: skip
    a = _s2_analysis(ctx)
    seen_ids = [i for p in a.critical for i in p.evidence_ids]
    if not a.critical:
        return _not_scored(
            ctx, sid, "NO_CRITICAL_ROLE_PROFILES",
            {"summary": "No profiles in critical technical role groups.", "window": window},
            [*base_lims, "No technical leadership / senior IC / security / data-ML profiles were observed."],
            [i for p in ctx.people for i in p.evidence_ids],
        )  # fmt: skip
    if not a.eligible:
        return _not_scored(
            ctx, sid, "NO_DATED_EMPLOYMENT",
            {
                "summary": "Critical-role profiles carry no target-company employment data (dates or status).",
                "profiles_seen": len(a.critical),
                "window": window,
            },
            [*base_lims, "Employment dates are required to establish a completed target-company interval."],
            seen_ids,
        )  # fmt: skip

    n_dep, n_elig = len(a.departures), len(a.eligible)
    score = _interp(a.weighted, _S2_CURVE)
    reasons: list[str] = []
    if n_dep:
        reasons.append(f"DEPARTURES_IN_WINDOW_{n_dep}")
        months = sorted(_month_idx(parsed[0]) for p in a.departures if (parsed := _parse_date(p.end)) is not None)
        if n_dep >= 2 and months[-1] - months[0] <= _t("s2_concentration_months"):
            score += _t("s2_concentration_bonus")
            reasons.append("CONCENTRATED_DEPARTURES")
        if n_elig >= _t("s2_min_eligible_profiles") and n_dep / n_elig >= _t("s2_share_bonus_threshold"):
            score += _t("s2_share_bonus")
            reasons.append("HIGH_SHARE_OF_OBSERVED_PROFILES")
    else:
        reasons.append("NO_DEPARTURES_OBSERVED")
    score = min(score, _t("s2_score_cap"))

    low = n_elig < _t("s2_min_eligible_profiles") or n_elig / len(a.critical) < _t("s2_min_eligible_share")
    state = SignalState.LOW_COVERAGE if low else SignalState.SCORABLE
    lims = list(base_lims)
    if low:
        reasons.append("LOW_PROFILE_COVERAGE")
        lims.append(
            f"Only {n_elig} observed profile(s) with target-company employment data (of {len(a.critical)} "
            "critical-role profiles seen); sample is small and nonrepresentative."
        )
    if a.missing_end:
        reasons.append("MISSING_END_DATE_NOT_COUNTED")
        lims.append(f"{len(a.missing_end)} eligible profile(s) have no end date; not counted as departures.")
    if a.unparseable_end:
        reasons.append("UNPARSEABLE_END_DATE_NOT_COUNTED")
        lims.append(f"{len(a.unparseable_end)} profile(s) have an unparseable end date; not counted.")
    if a.conflicts:
        reasons.append("CONFLICTING_RECORDS_EXCLUDED")
        lims.append(f"{len(a.conflicts)} profile(s) have contradictory employment records and were excluded.")
    if any(p.n_records > 1 for p in a.critical):
        reasons.append("DUPLICATE_PROFILES_MERGED")
        lims.append("Duplicate profile records for the same person were merged before counting.")

    statement = (
        f"{n_dep} of {n_elig} observed senior technical profiles show a past target-company role ending "
        f"in the observed window ({window['start']} to {window['end']}); not a company-wide attrition rate."
    )
    raw: dict[str, object] = {
        "summary": statement,
        "departures_in_window": n_dep,
        "observed_eligible_profiles": n_elig,
        "critical_role_profiles_seen": len(a.critical),
        "missing_end_date_count": len(a.missing_end),
        "unparseable_end_date_count": len(a.unparseable_end),
        "seniority_weighted_departures": round(a.weighted, 2),
        "window": window,
        "departed": [{"person_ref": p.ref, "role_group": p.role_group, "target_end": p.end} for p in a.departures],
    }
    used_ids = [i for p in a.eligible for i in p.evidence_ids]
    used = ctx.records(used_ids)
    completeness = 30.0 * (n_elig / len(a.critical)) * min(1.0, n_elig / _t("s2_min_eligible_profiles"))
    dated = sum(1 for p in a.eligible if p.end or p.start) / n_elig
    conf = _Conf(
        completeness=completeness * (0.5 + 0.5 * dated),
        recency=_recency_points(used, ctx.as_of),
        corroboration=_corroboration_points(used),
        identity=15.0 * len(a.eligible) / max(1, sum(p.n_records for p in a.eligible)),
    )
    return _result(ctx, sid, state, score, raw=raw, reasons=reasons, evidence_ids=used_ids, conf=conf, limitations=lims)


# ---------------------------------------------------------------------------
# S3 - Critical capability coverage / senior bench proxy (15%)
# ---------------------------------------------------------------------------


def score_s3(case_input: CaseInput, evidence: Sequence[EvidenceRecord], as_of: date | None = None) -> SignalResult:
    ctx = _build_ctx(case_input, evidence, as_of)
    sid = SignalId.S3
    base_lims = [
        "Publicly observable leadership coverage proxy only; not a workforce census or senior/junior ratio.",
        "'No profile found' is recorded as no_data, not as proof the capability is absent.",
    ]
    caps = _uniq(case_input.critical_capabilities)
    if not caps:
        return _not_scored(
            ctx, sid, "NO_CRITICAL_CAPABILITIES_SPECIFIED", {"summary": "No thesis-critical capabilities specified."},
            base_lims,
        )  # fmt: skip

    matrix: list[dict[str, object]] = []
    row_scores: dict[str, float] = {}
    reasons: list[str] = []
    used_ids: list[str] = []
    observed_profiles: set[str] = set()
    conflicting = 0
    for cap in caps:
        cap_people = [p for p in ctx.people if p.capability == cap and p.role_group != "non_technical"]
        current = [p for p in cap_people if p.current_at_target is True and not p.conflict]
        conflicts = [p for p in cap_people if p.conflict]
        departures = [
            p for p in cap_people
            if not p.conflict and p.end and _in_window(_parse_date(p.end), ctx.window_start, ctx.as_of)
        ]  # fmt: skip
        open_jobs = [j for j in ctx.jobs if j.capability == cap and j.role_group != "non_technical"]
        open_roles = sum(j.openings for j in open_jobs)
        ev_ids = [i for p in cap_people for i in p.evidence_ids] + [i for j in open_jobs for i in j.evidence_ids]
        newest = max((r.retrieved_at for r in ctx.records(ev_ids)), default=None)

        score: float | None
        if conflicts:
            status, score = "conflicting", None
            conflicting += 1
        elif current:
            status = "observed"
            if len(current) >= 2:
                score = 15.0 if departures else 5.0
            else:  # a single observable leader: concentration proxy
                score = 50.0 if (open_roles and departures) else 35.0 if open_roles else 20.0 if departures else 15.0
            if len(current) == 1:
                reasons.append(f"SINGLE_OBSERVED_LEADER_{cap.upper()}")
        elif open_roles:
            status = "open_role_only"
            # Elevated risk needs open roles + departures + no observed current coverage (two independent sources).
            score = 70.0 if departures else 30.0
            if departures:
                reasons.append(f"GAP_WITH_OPEN_ROLES_AND_DEPARTURES_{cap.upper()}")
        else:
            status, score = "no_data", None
        if score is not None:
            row_scores[cap] = score
            used_ids.extend(ev_ids)
        observed_profiles.update(p.ref for p in current)
        matrix.append({
            "capability": cap,
            "status": status,
            "current_observed_profiles": len(current),
            "open_roles": open_roles,
            "departures_in_window": len(departures),
            "source_age_days": None if newest is None else max(0, (ctx.as_of - newest.date()).days),
            "evidence_ids": _uniq(ev_ids),
        })  # fmt: skip

    raw: dict[str, object] = {
        "capability_matrix": matrix,
        "capabilities_assessed": len(row_scores),
        "capabilities_total": len(caps),
        "distinct_observed_profiles": len(observed_profiles),
    }
    all_ids = [i for row in matrix for i in row["evidence_ids"]]  # type: ignore[union-attr]
    if not row_scores:
        if conflicting:
            raw["summary"] = "Capability evidence is conflicting; no coverage score."
            return _result(
                ctx, sid, SignalState.CONFLICTING, None, raw=raw, reasons=["CONFLICTING_CAPABILITY_RECORDS"],
                evidence_ids=all_ids, conf=_Conf(), limitations=base_lims,
            )  # fmt: skip
        raw["summary"] = "No thesis-critical capability has observable profile or job evidence."
        return _not_scored(ctx, sid, "ALL_CAPABILITIES_NO_DATA", raw, base_lims, all_ids)

    score_v = max(row_scores.values())
    low = len(observed_profiles) < _t("s3_min_observed_profiles") or (
        len(row_scores) / len(caps) < _t("s3_min_assessed_share")
    )
    state = SignalState.LOW_COVERAGE if low else SignalState.SCORABLE
    lims = list(base_lims)
    if low:
        reasons.append("LOW_CAPABILITY_COVERAGE")
        lims.append("Few capabilities or profiles observed; coverage proxy is low confidence.")
    if conflicting:
        reasons.append("CONFLICTING_CAPABILITY_RECORDS")
        lims.append(f"{conflicting} capability row(s) had contradictory records and were not scored.")
    no_data = [r["capability"] for r in matrix if r["status"] == "no_data"]
    if no_data:
        reasons.append("SOME_CAPABILITIES_NO_DATA")
    raw["summary"] = "Coverage by capability: " + ", ".join(f"{r['capability']}={r['status']}" for r in matrix) + "."
    used = ctx.records(used_ids)
    assessed_share = len(row_scores) / len(caps)
    conf = _Conf(
        completeness=30.0 * assessed_share * min(1.0, len(observed_profiles) / _t("s3_min_observed_profiles")),
        recency=_recency_points(used, ctx.as_of),
        corroboration=_corroboration_points(used),
        identity=(15.0 * len(ctx.people) / max(1, sum(p.n_records for p in ctx.people)) if ctx.people else 8.0),
    )
    return _result(
        ctx, sid, state, score_v, raw=raw, reasons=reasons, evidence_ids=used_ids, conf=conf, limitations=lims
    )


# ---------------------------------------------------------------------------
# S4 - Critical-role hiring pressure (20%)
# ---------------------------------------------------------------------------


def score_s4(
    case_input: CaseInput,
    evidence: Sequence[EvidenceRecord],
    as_of: date | None = None,
    s1: SignalResult | None = None,
    s2: SignalResult | None = None,
) -> SignalResult:
    """Pass already-computed ``s1`` / ``s2`` to avoid recomputation; otherwise they are derived here."""
    ctx = _build_ctx(case_input, evidence, as_of)
    sid = SignalId.S4
    if not ctx.jobs:
        return _not_scored(
            ctx, sid, "NO_JOB_DATA",
            {"summary": "No job posting evidence for the target; hiring pressure unavailable."},
            [
                "Missing job data, unknown job pricing, or zero matches is unavailable evidence - "
                "it must not be read as 'no hiring'.",
            ],
        )  # fmt: skip
    s1 = s1 or score_s1(case_input, evidence, as_of)
    s2 = s2 or score_s2(case_input, evidence, as_of)
    js = _job_stats(ctx)
    headcount = ctx.target[1].total_headcount if ctx.target else None
    share = js.critical_openings / headcount if isinstance(headcount, int) and headcount > 0 else None

    corrob: list[str] = []
    if s1.score is not None and s1.score >= _t("s4_corroborating_s1_min_score"):
        corrob.append("ENGINEERING_CONTRACTION_SIGNAL")
    dep = s2.raw_measure.get("departures_in_window")
    if s2.score is not None and isinstance(dep, int) and dep >= _t("s4_corroborating_departures_min"):
        corrob.append("CONTINUITY_RISK_SIGNAL")

    c = js.critical_openings
    reasons: list[str] = []
    if c == 0:
        score = 5.0
        reasons.append("NO_CRITICAL_OPENINGS_OBSERVED")
    elif c < _t("s4_multiple_openings_min"):
        score = 12.0 + (8.0 if js.persistent_or_reposted else 0.0)  # 0-20: few/expected openings
        reasons.append("FEW_CRITICAL_OPENINGS")
        if js.persistent_or_reposted:
            reasons.append("REPOSTED_OR_PERSISTENT_CRITICAL_ROLE")
    else:
        score = 30.0  # 21-40: multiple relevant openings without stronger corroboration
        reasons.append("MULTIPLE_CRITICAL_OPENINGS")
        unusual = (
            c >= _t("s4_concentration_openings_min")
            or (share is not None and share >= _t("s4_posting_share_unusual"))
            or js.persistent_or_reposted >= _t("s4_persistent_critical_min")
        )
        if unusual:
            score = 50.0  # 41-60
            reasons.append("UNUSUAL_CONCENTRATION_OR_PERSISTENCE")
        if corrob:
            score = max(score, 65.0 + (7.0 if len(corrob) >= 2 else 0.0))  # 61-80 needs S1/S2 corroboration
            reasons.extend(f"CORROBORATED_BY_{x}" for x in corrob)
        if (
            len(corrob) >= 2
            and c >= _t("s4_concentration_openings_min")
            and len(js.capabilities) >= _t("s4_broad_capabilities_min")
        ):
            score = 85.0  # 81+ only: broad, multi-signal corroborated rebuild pressure
            reasons.append("BROAD_CAPABILITY_REBUILD_PRESSURE")

    lims = [
        "Job postings are current-state records; absence or presence of postings is not a hiring history.",
        "Peer-relative posting pressure is not computed (no matched peer job data used).",
    ]
    if share is None:
        lims.append("Target headcount unavailable; critical posting share not computed.")
        reasons.append("NO_HEADCOUNT_DENOMINATOR")
    if js.undated_critical:
        lims.append(f"{js.undated_critical} critical posting(s) lack a date; persistence cannot be assessed for them.")
    if ctx.duplicate_job_records:
        reasons.append("DUPLICATE_POSTINGS_REMOVED")
    raw: dict[str, object] = {
        "total_postings_after_dedup": js.total_postings,
        "duplicate_records_removed": ctx.duplicate_job_records,
        "critical_openings_count": c,
        "critical_postings": len(js.critical),
        "critical_posting_share": None if share is None else round(share, 4),
        "target_headcount": headcount,
        "reposted_critical_postings": js.reposted,
        "persistent_or_reposted_critical_postings": js.persistent_or_reposted,
        "critical_capabilities_with_openings": js.capabilities,
        "corroborating_signals": corrob,
        "summary": f"{c} critical opening(s) across {len(js.critical)} deduplicated posting(s); "
        f"{js.reposted} reposted.",
    }
    job_ids = [i for j in ctx.jobs for i in j.evidence_ids]
    ids = job_ids + ([ctx.target[0].evidence_id] if ctx.target and share is not None else [])
    used = ctx.records(ids)
    field_frac = sum((bool(j.date_added) + bool(j.url) + j.has_openings_field) / 3 for j in ctx.jobs) / len(ctx.jobs)
    conf = _Conf(
        completeness=30.0 * (0.7 * field_frac + (0.3 if share is not None else 0.0)),
        recency=_recency_points(used, ctx.as_of),
        corroboration=_corroboration_points(used) + (4.0 if corrob else 0.0),
        identity=15.0 * len(ctx.jobs) / max(1, sum(j.n_records for j in ctx.jobs)),
    )
    conf.corroboration = min(20.0, conf.corroboration)
    return _result(ctx, sid, SignalState.SCORABLE, score, raw=raw, reasons=reasons, evidence_ids=ids, conf=conf,
                   limitations=lims)  # fmt: skip


# ---------------------------------------------------------------------------
# S5 - Competitor talent movement (10%)
# ---------------------------------------------------------------------------


def score_s5(case_input: CaseInput, evidence: Sequence[EvidenceRecord], as_of: date | None = None) -> SignalResult:
    ctx = _build_ctx(case_input, evidence, as_of)
    sid = SignalId.S5
    base_lims = [
        "Corroborating context only: a role change is not evidence of harm, and significance depends on timing, "
        "role criticality and the deal thesis.",
        "Competitor match is by exact normalized domain; parent/subsidiary identity is not resolved.",
    ]
    if not ctx.people:
        return _not_scored(ctx, sid, "NO_PERSON_DATA", {"summary": "No person work-history evidence."}, base_lims)
    technical = [p for p in ctx.people if p.role_group != "non_technical"]
    eligible = [p for p in technical if (p.end or p.current_at_target is not None) and not p.conflict]
    if not eligible:
        return _not_scored(
            ctx, sid, "NO_EMPLOYMENT_DATA",
            {"summary": "Profiles lack target-company employment end dates or status."},
            [*base_lims, "A completed target-company interval is required to attribute a move."],
            [i for p in technical for i in p.evidence_ids],
        )  # fmt: skip

    comps = {_norm_domain(d) for d in case_input.competitor_domains}
    movers: list[_Person] = []
    earlier: list[_Person] = []
    unconfirmed: list[_Person] = []
    for p in eligible:
        dom = _norm_domain(p.current_employer_domain) if p.current_employer_domain else ""
        if dom not in comps or p.current_at_target is True:
            continue
        parsed = _parse_date(p.end)
        if parsed is None:
            unconfirmed.append(p)  # competitor employer but no completed target interval date
        elif _in_window(parsed, ctx.window_start, ctx.as_of):
            movers.append(p)
        elif parsed[0] <= ctx.as_of:
            earlier.append(p)
    weighted = sum(ROLE_SENIORITY_WEIGHT[p.role_group] for p in movers)
    score = _interp(weighted, _S5_CURVE)
    n_mov, n_elig = len(movers), len(eligible)
    reasons = [f"COMPETITOR_MOVES_IN_WINDOW_{n_mov}"] if n_mov else ["NO_COMPETITOR_MOVES_OBSERVED"]
    low = n_elig < _t("s2_min_eligible_profiles")
    lims = list(base_lims)
    if low:
        reasons.append("LOW_PROFILE_COVERAGE")
        lims.append(f"Only {n_elig} observed profile(s) with usable employment data; sample is small.")
    if unconfirmed:
        reasons.append("UNCONFIRMED_MOVE_TIMING_NOT_COUNTED")
        lims.append(f"{len(unconfirmed)} competitor-employed profile(s) lack a target end date; not counted.")
    if earlier:
        reasons.append("EARLIER_MOVES_OUTSIDE_WINDOW_NOT_COUNTED")
    by_comp: dict[str, int] = defaultdict(int)
    for p in movers:
        by_comp[_norm_domain(p.current_employer_domain)] += 1
    raw: dict[str, object] = {
        "summary": f"{n_mov} of {n_elig} observed technical profiles show a completed target-company role "
        "followed by a current role at a listed competitor within the observed window.",
        "competitor_moves_in_window": n_mov,
        "observed_eligible_profiles": n_elig,
        "moves_by_competitor": dict(sorted(by_comp.items())),
        "moves_outside_window": len(earlier),
        "unconfirmed_timing": len(unconfirmed),
        "movers": [
            {"person_ref": p.ref, "role_group": p.role_group, "target_end": p.end,
             "competitor_domain": _norm_domain(p.current_employer_domain)}
            for p in movers
        ],
    }  # fmt: skip
    ids = [i for p in eligible for i in p.evidence_ids]
    used = ctx.records(ids)
    conf = _Conf(
        completeness=30.0 * min(1.0, n_elig / _t("s2_min_eligible_profiles")) * len(eligible) / len(technical),
        recency=_recency_points(used, ctx.as_of),
        corroboration=_corroboration_points(used),
        identity=15.0 * len(eligible) / max(1, sum(p.n_records for p in eligible)),
    )
    return _result(
        ctx, sid, SignalState.LOW_COVERAGE if low else SignalState.SCORABLE, score,
        raw=raw, reasons=reasons, evidence_ids=ids, conf=conf, limitations=lims,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# Composite scorecard
# ---------------------------------------------------------------------------


def risk_band_for(score: float) -> Literal["Low signal", "Watch", "Elevated", "High signal"]:
    """Display label only (unvalidated heuristic): 0-24 Low, 25-49 Watch, 50-69 Elevated, 70-100 High."""
    if score >= _t("band_high_min"):
        return "High signal"
    if score >= _t("band_elevated_min"):
        return "Elevated"
    if score >= _t("band_watch_min"):
        return "Watch"
    return "Low signal"


def coverage_label_for(
    coverage_pct: float,
) -> Literal["insufficient_evidence", "provisional", "coverage_threshold_met"]:
    if coverage_pct < _t("coverage_min_publish_pct"):
        return "insufficient_evidence"
    if coverage_pct < _t("coverage_threshold_met_pct"):
        return "provisional"
    return "coverage_threshold_met"


def build_scorecard(signals: Sequence[SignalResult]) -> Scorecard:
    """Composite per the catalog: risk = sum(w*s)/sum(w) over assessable signals A; coverage = sum(w_A)/sum(w_all).

    A = scored SCORABLE signals (full weight) + scored LOW_COVERAGE signals (``low_coverage_weight_factor`` of
    their weight). Below 60% coverage the composite is withheld (risk_score/risk_band None) - never zero."""
    total_w = sum(s.weight for s in signals)
    factor = _t("low_coverage_weight_factor")
    eff: list[tuple[SignalResult, float]] = []
    for s in signals:
        if s.score is None:
            continue
        if s.state == SignalState.SCORABLE:
            eff.append((s, s.weight))
        elif s.state == SignalState.LOW_COVERAGE:
            eff.append((s, s.weight * factor))
    assessable = sum(w for _, w in eff)
    coverage = round(100.0 * assessable / total_w, 2) if total_w else 0.0
    label = coverage_label_for(coverage)
    risk: float | None = None
    band = None
    if label != "insufficient_evidence" and assessable > 0:
        risk = round(sum(w * (s.score or 0.0) for s, w in eff) / assessable, 1)
        band = risk_band_for(risk)
    conf = round(sum(s.weight * s.confidence for s in signals) / total_w, 1) if total_w else 0.0
    return Scorecard(
        signals=list(signals),
        risk_score=risk,
        coverage_pct=coverage,
        coverage_label=label,
        risk_band=band,
        evidence_confidence=conf,
        signal_version=SIGNAL_SCORING_VERSION,
    )


def compute_scorecard(
    case_input: CaseInput, evidence: Sequence[EvidenceRecord], as_of: date | None = None
) -> Scorecard:
    """Score S1-S5 deterministically and compose the scorecard. ``as_of`` defaults to the latest evidence date."""
    resolved = resolve_as_of(evidence, as_of)
    s1 = score_s1(case_input, evidence, resolved)
    s2 = score_s2(case_input, evidence, resolved)
    s3 = score_s3(case_input, evidence, resolved)
    s4 = score_s4(case_input, evidence, resolved, s1=s1, s2=s2)
    s5 = score_s5(case_input, evidence, resolved)
    return build_scorecard([s1, s2, s3, s4, s5])


__all__ = [
    "CRITICAL_ROLE_GROUPS",
    "SIGNAL_NAMES",
    "SIGNAL_WEIGHTS",
    "THRESHOLDS",
    "build_scorecard",
    "compute_scorecard",
    "coverage_label_for",
    "resolve_as_of",
    "risk_band_for",
    "score_s1",
    "score_s2",
    "score_s3",
    "score_s4",
    "score_s5",
]
