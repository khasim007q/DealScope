"""Plausibility guard for provider growth figures.

Live Crustdata responses can contain discontinuities (e.g. a company headcount re-mapped between months, or a
department series that starts from a tiny base), producing growth such as +300% engineering headcount in 3 months.
Such values are dropped before scoring and recorded as data-quality flags, so they appear as limitations instead of
risk evidence. Thresholds are deliberately loose: they remove only values that are implausible for an operating company.
"""

from __future__ import annotations

from dealscope.domain.models import CompanyProfilePayload

# Max plausible absolute growth (%) per period label.
MAX_ABS_GROWTH_PCT = {"1m": 60.0, "3m": 100.0, "6m": 100.0, "12m": 250.0, "24m": 500.0}
MIN_HEADCOUNT_FOR_CHECK = 20  # tiny companies can legitimately double


def sanitize_company(payload: CompanyProfilePayload) -> CompanyProfilePayload:
    flags = list(payload.data_quality_flags)
    updates: dict[str, dict[str, float]] = {}
    for field, size in (
        ("total_growth_pct", payload.total_headcount),
        ("engineering_growth_pct", payload.engineering_headcount),
    ):
        series = getattr(payload, field)
        if size is not None and size < MIN_HEADCOUNT_FOR_CHECK:
            continue
        kept = {}
        for period, value in series.items():
            limit = MAX_ABS_GROWTH_PCT.get(period)
            if limit is not None and abs(value) > limit:
                flags.append(
                    f"{field}.{period}={value:.1f}% dropped: implausible (>{limit:.0f}%), likely provider "
                    "data discontinuity"
                )
            else:
                kept[period] = value
        if kept != series:
            updates[field] = kept
    if not updates and flags == payload.data_quality_flags:
        return payload
    return payload.model_copy(update={**updates, "data_quality_flags": sorted(set(flags))})
