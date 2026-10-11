"""Peer benchmarking helpers (docs/02-lld.md section 7).

Pure functions, no I/O. Rules implemented here:

* peers are only the user-provided/confirmed domains (the caller filters; this module never invents peers);
* median / quartiles are preferred over the mean; dispersion is shown with n >= 3;
* values are compared only for the *identical* field and period key (no period inference or interpolation);
* fewer than 3 usable (comparable) peers -> benchmark is `weak` (or `insufficient` with zero peers) and the
  caller must treat the peer comparison as low confidence;
* peers that differ materially by size, sector or geography make the benchmark `weak`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

from dealscope.domain.models import CompanyProfilePayload

BenchmarkStrength = Literal["usable", "weak", "insufficient"]

# Minimum number of usable, comparable peers for a peer-relative claim.
MIN_USABLE_PEERS = 3
# Peers whose total headcount is more than this multiple (either direction) of the target are not "comparable".
MAX_SIZE_RATIO = 10.0


@dataclass(frozen=True)
class PeerStats:
    """Robust summary of a peer sample. Quartiles use the median-of-halves (Tukey hinge) method:
    the median itself is excluded from both halves when n is odd."""

    n: int
    median: float | None
    q1: float | None
    q3: float | None
    iqr: float | None
    min: float | None
    max: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "n": self.n,
            "median": self.median,
            "q1": self.q1,
            "q3": self.q3,
            "iqr": self.iqr,
            "min": self.min,
            "max": self.max,
        }


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def peer_stats(values: Iterable[float]) -> PeerStats:
    """n / median / Q1 / Q3 / IQR / min / max. Non-finite and non-numeric values are ignored.
    The median (not the mean) is the central tendency."""
    vals = sorted(float(v) for v in values if _is_number(v))
    n = len(vals)
    if n == 0:
        return PeerStats(0, None, None, None, None, None, None)
    med = float(median(vals))
    lower = vals[: n // 2]
    upper = vals[(n + 1) // 2 :]
    q1 = float(median(lower)) if lower else vals[0]
    q3 = float(median(upper)) if upper else vals[-1]
    return PeerStats(n, med, q1, q3, q3 - q1, vals[0], vals[-1])


def benchmark_strength(n: int, n_comparable: int | None = None) -> BenchmarkStrength:
    """`usable` needs >= 3 peers that are also comparable; 1-2 peers (or dissimilar peers) -> `weak`
    (low-confidence peer comparison); no peers -> `insufficient`."""
    if n <= 0:
        return "insufficient"
    comparable = n if n_comparable is None else n_comparable
    if n >= MIN_USABLE_PEERS and comparable >= MIN_USABLE_PEERS:
        return "usable"
    return "weak"


def peer_period_values(
    peers: Iterable[CompanyProfilePayload], field_name: str, period: str | None = None
) -> dict[str, float]:
    """Extract one field from peer profiles, keyed by peer domain.

    For dict-valued growth fields (`total_growth_pct`, `engineering_growth_pct`) `period` must be given and only
    peers that returned that *exact* period key contribute. For scalar fields pass `period=None`.
    Peers lacking the value are omitted (never imputed)."""
    out: dict[str, float] = {}
    for peer in peers:
        raw = getattr(peer, field_name, None)
        if period is not None:
            raw = raw.get(period) if isinstance(raw, Mapping) else None
        if _is_number(raw):
            out[peer.domain] = float(raw)
    return out


def comparability_flags(target: CompanyProfilePayload, peer: CompanyProfilePayload) -> list[str]:
    """Reasons a peer is not comparable to the target (empty list = no mismatch observed or fields unknown)."""
    flags: list[str] = []
    t_hc, p_hc = target.total_headcount, peer.total_headcount
    if t_hc and p_hc and t_hc > 0 and p_hc > 0:
        ratio = max(t_hc, p_hc) / min(t_hc, p_hc)
        if ratio > MAX_SIZE_RATIO:
            flags.append("size_mismatch")
    if target.industry and peer.industry and target.industry.strip().lower() != peer.industry.strip().lower():
        flags.append("sector_mismatch")
    if target.hq_country and peer.hq_country and target.hq_country.strip().lower() != peer.hq_country.strip().lower():
        flags.append("geography_mismatch")
    return flags


@dataclass(frozen=True)
class BenchmarkResult:
    field_name: str
    period: str | None
    target_value: float | None
    peer_values: dict[str, float]
    stats: PeerStats
    strength: BenchmarkStrength
    n_comparable: int
    delta_vs_median: float | None
    below_q1: bool | None
    above_q3: bool | None
    flags_by_peer: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field_name,
            "period": self.period,
            "target_value": self.target_value,
            "peer_values": dict(self.peer_values),
            "stats": self.stats.as_dict(),
            "strength": self.strength,
            "n_comparable": self.n_comparable,
            "delta_vs_median": self.delta_vs_median,
            "below_q1": self.below_q1,
            "above_q3": self.above_q3,
            "comparability_flags": {k: list(v) for k, v in self.flags_by_peer.items() if v},
        }


def benchmark_field(
    target: CompanyProfilePayload,
    peers: Iterable[CompanyProfilePayload],
    field_name: str,
    period: str | None = None,
) -> BenchmarkResult:
    """Compare the target's value for (field, period) with the peer median/IQR for the identical field/period."""
    peer_list = list(peers)
    values = peer_period_values(peer_list, field_name, period)
    raw = getattr(target, field_name, None)
    if period is not None:
        raw = raw.get(period) if isinstance(raw, Mapping) else None
    target_value = float(raw) if _is_number(raw) else None

    flags = {p.domain: comparability_flags(target, p) for p in peer_list if p.domain in values}
    n_comparable = sum(1 for d in values if not flags.get(d))
    stats = peer_stats(values.values())
    delta = below = above = None
    if target_value is not None and stats.median is not None:
        delta = target_value - stats.median
        if stats.n >= MIN_USABLE_PEERS and stats.q1 is not None and stats.q3 is not None:
            below = target_value < stats.q1
            above = target_value > stats.q3
    return BenchmarkResult(
        field_name=field_name,
        period=period,
        target_value=target_value,
        peer_values=values,
        stats=stats,
        strength=benchmark_strength(stats.n, n_comparable),
        n_comparable=n_comparable,
        delta_vs_median=delta,
        below_q1=below,
        above_q3=above,
        flags_by_peer=flags,
    )
