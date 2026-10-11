from dealscope.analysis.data_quality import sanitize_company
from dealscope.domain.models import CompanyProfilePayload


def test_implausible_growth_dropped_and_flagged():
    # Values observed live for two peers on 2026-10-11 (provider discontinuities).
    p = CompanyProfilePayload(
        domain="peer.example",
        total_headcount=6134,
        total_growth_pct={"3m": -15.9, "12m": -12.5},
        engineering_headcount=1500,
        engineering_growth_pct={"3m": 346.43, "6m": 443.48, "12m": 500.0},
    )
    out = sanitize_company(p)
    assert out.engineering_growth_pct == {}
    assert out.total_growth_pct == {"3m": -15.9, "12m": -12.5}
    assert len(out.data_quality_flags) == 3 and all("implausible" in f for f in out.data_quality_flags)


def test_plausible_values_untouched_and_small_companies_skipped():
    p = CompanyProfilePayload(
        domain="t.example",
        total_headcount=7591,
        total_growth_pct={"3m": 17.65, "12m": 68.5},
        engineering_headcount=741,
        engineering_growth_pct={"3m": 8.65, "12m": 51.22},
    )
    assert sanitize_company(p) is p
    tiny = CompanyProfilePayload(domain="s.example", total_headcount=10, total_growth_pct={"3m": 150.0})
    assert sanitize_company(tiny).total_growth_pct == {"3m": 150.0}
