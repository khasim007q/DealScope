from __future__ import annotations

import pytest

from dealscope.analysis.peer_benchmark import (
    benchmark_field,
    benchmark_strength,
    comparability_flags,
    peer_period_values,
    peer_stats,
)
from dealscope.domain.models import CompanyProfilePayload


def _co(domain: str, eng: dict[str, float] | None = None, **kw: object) -> CompanyProfilePayload:
    return CompanyProfilePayload(domain=domain, engineering_growth_pct=eng or {}, **kw)  # type: ignore[arg-type]


def test_peer_stats_median_and_iqr_odd_n():
    s = peer_stats([5, 1, 3, 2, 4])
    assert (s.n, s.median, s.q1, s.q3, s.iqr, s.min, s.max) == (5, 3.0, 1.5, 4.5, 3.0, 1.0, 5.0)


def test_peer_stats_three_peers_fixture_values():
    s = peer_stats([7, 8, 3])
    assert s.median == 7.0
    assert (s.q1, s.q3, s.iqr) == (3.0, 8.0, 5.0)


def test_peer_stats_uses_median_not_mean():
    s = peer_stats([1, 2, 100])
    assert s.median == 2.0  # mean would be ~34.3


def test_peer_stats_even_n_and_empty_and_nonfinite():
    s = peer_stats([1, 2, 3, 4])
    assert (s.median, s.q1, s.q3) == (2.5, 1.5, 3.5)
    e = peer_stats([])
    assert e.n == 0 and e.median is None and e.iqr is None
    assert peer_stats([1.0, float("nan"), float("inf")]).n == 1


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, "insufficient"), (1, "weak"), (2, "weak"), (3, "usable"), (5, "usable")],
)
def test_benchmark_strength_by_n(n, expected):
    assert benchmark_strength(n) == expected


def test_benchmark_strength_dissimilar_peers_are_weak():
    assert benchmark_strength(4, n_comparable=2) == "weak"


def test_peer_period_values_identical_period_only():
    peers = [_co("a.example", {"6m": 7.0}), _co("b.example", {"12m": 9.0}), _co("c.example")]
    assert peer_period_values(peers, "engineering_growth_pct", "6m") == {"a.example": 7.0}
    assert peer_period_values(peers, "engineering_growth_pct", "12m") == {"b.example": 9.0}
    assert peer_period_values(peers, "engineering_growth_pct", "3m") == {}


def test_peer_period_values_scalar_field():
    peers = [_co("a.example", total_headcount=100), _co("b.example")]
    assert peer_period_values(peers, "total_headcount") == {"a.example": 100.0}


def test_benchmark_field_vs_peers_and_low_confidence_with_two_peers():
    target = _co("t.example", {"6m": -4.0})
    three = [_co("a.example", {"6m": 7.0}), _co("b.example", {"6m": 8.0}), _co("c.example", {"6m": 3.0})]
    b = benchmark_field(target, three, "engineering_growth_pct", "6m")
    assert b.strength == "usable"
    assert b.delta_vs_median == -11.0 and b.below_q1 is True
    b2 = benchmark_field(target, three[:2], "engineering_growth_pct", "6m")
    assert b2.strength == "weak"
    assert b2.below_q1 is None  # no dispersion claims below n=3
    assert benchmark_field(target, [], "engineering_growth_pct", "6m").strength == "insufficient"


def test_comparability_flags_size_sector_geo():
    t = _co("t.example", total_headcount=100, industry="Software", hq_country="US")
    big = _co("p.example", total_headcount=5000, industry="software", hq_country="DE")
    assert comparability_flags(t, big) == ["size_mismatch", "geography_mismatch"]
    assert comparability_flags(t, _co("q.example")) == []
