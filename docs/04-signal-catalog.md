# 04 — Signal Catalog and Scoring Rules

This document is normative for the MVP. Thresholds are hypotheses for prioritizing diligence, not validated predictors of deal failure. Version every change to weights/rules and record it in every report.

## Global scoring protocol

- Each signal returns `score: 0–100`, `state`, raw inputs, reason codes, source evidence IDs, confidence, and limitations.
- A score means **risk signal strength**, not probability of failure.
- Use matched peer median/IQR where at least 3 usable peers have comparable fields. If peers are weak or missing, fall back to direction-of-change evidence and lower confidence.
- Do not manufacture a 12/24/36-month series if the API only provides 1/3/6/12-month growth metrics. Use only fields actually returned and show exact periods.
- If a required field, time period, or subject mapping is absent, return `not_scored` or `low_coverage`.
- If all source evidence is current-state only, do not use the words “spike,” “sustained,” “trend,” or “change over time.”

## Signal weights

| ID | Signal | Weight | Primary source | Interpretation |
|---|---|---:|---|---|
| S1 | Technical-function trajectory divergence | 30% | Company enrichment / available department headcount history | Is technical workforce trajectory inconsistent with total company trajectory or deal thesis? |
| S2 | Critical-role continuity risk | 25% | People search/profile work history + validated titles/dates | Are multiple key technical leaders observed leaving within relevant window? |
| S3 | Critical capability coverage / senior bench proxy | 15% | Current people records + job postings | Are key technical functions apparently thin or dependent on very few observable leaders? |
| S4 | Critical-role hiring pressure | 20% | Jobs API | Are critical roles repeatedly reposted/open in clusters or high relative to size? |
| S5 | Competitor talent movement | 10% | Person work histories + user-confirmed competitor list | Are identified senior technical alumni joining direct competitors? |

## S1 — Technical-function trajectory divergence (30%)

### Required inputs
- Target total headcount growth over whichever periods the API actually returns (prefer 6m and 12m where available).
- Target engineering/R&D department headcount or growth, if exposed.
- Same fields for 3–5 user-confirmed peers where available.

### Raw measures
- `tech_growth_6m` / `tech_growth_12m` if available.
- `total_growth_6m` / `total_growth_12m` if available.
- `tech_vs_total_gap = tech_growth - total_growth` only where periods are identical.
- Peer-relative gap against peer median, same field/period.

### Risk mapping (initial heuristic)
- 0–20: technical trajectory stable/strong relative to total and peers, with usable data.
- 21–40: modest divergence; one period/measure is concerning.
- 41–60: technical function flat/declining while total headcount grows, or below peer median by a material margin.
- 61–80: technical workforce contraction across more than one returned period while total company is stable/growing.
- 81–100: severe, multi-period divergence plus independent supporting signals (e.g., critical vacancies); never based on one percentage alone.

Threshold logic should be coded explicitly with comments/config, not inferred at runtime by the LLM. Calibrate numeric cutoffs against peer dispersion. If department-level fields are absent, do not substitute overall company shrinkage as proof of technical shrinkage; report overall growth as context and lower/omit S1.

## S2 — Critical-role continuity risk (25%)

### Relevant roles
CTO, Chief Architect, VP/Head/Director of Engineering, Engineering Manager for critical platform function, Staff/Principal Engineer, Security Engineering lead, Data/ML Platform lead, and other roles explicitly identified as critical by the user’s deal thesis.

### Required inputs
- Returned work histories with target employer relationship and dates sufficient to establish a past employment interval.
- Current role/employer records where available.
- A defined observation window and reliable role classification.

### Rules
- Count distinct people, not profile events.
- Only mark a departure if the returned profile records a completed target-company employment interval or an adequately supported current-employer change. Do not infer a departure from missing current employment fields.
- Score concentration in a short window and seniority/role criticality; compare with the number of *observed, eligible profiles*. Never call this the company’s attrition rate.
- A small nonrepresentative sample cannot establish “40% of engineering left.” Use “3 identified senior technical profiles show a past target-company role ending in the observed window.”
- Reduce confidence if employment dates are missing, profiles are duplicated, or coverage is low.

## S3 — Critical capability coverage / senior bench proxy (15%)

### Purpose
Determine whether the data reveals multiple key technical capabilities and leadership roles, or whether the available evidence suggests concentration or vacancies. This is not a workforce census.

### Inputs
- Current relevant technical leadership/specialist profiles if exposed.
- Current role postings for the selected capability groups.
- User-specified capability priorities from the deal thesis (e.g., infrastructure, platform reliability, cybersecurity, data/ML).

### Rules
- Use a capability coverage matrix: capability, current observed role/profile evidence, open relevant roles, source freshness, and status (`observed`, `open_role_only`, `no_data`, `conflicting`).
- Score elevated risk only when a capability is thesis-critical and evidence supports concentration/gap, preferably with multiple independent signals.
- Do not infer a full senior/junior ratio from a biased sample of search results. If only a few profiles are observed, show a “publicly observable leadership coverage proxy,” with low confidence.
- “No profile found” is `no_data`, not proof the company has no capability.

## S4 — Critical-role hiring pressure (20%)

### Inputs
- Current Jobs API records for thesis-relevant technical roles.
- Openings count, category, date added/updated, repost flag, job URL, and employer context where returned.
- Target headcount estimate as denominator if reliable.

### Measures
- `critical_openings_count` after deduplication.
- `critical_posting_share = critical_openings / current headcount` only if denominator is numeric and comparable.
- Repost/age pattern where returned dates support it.
- Peer-relative posting pressure if peers have matching job data.

### Rules
- 0–20: few or expected openings, stable data; not a positive health certification.
- 21–40: multiple relevant openings without stronger corroboration.
- 41–60: unusual concentration or persistent/reposted critical roles relative to peers/size.
- 61–80: several critical role vacancies cluster with continuity-risk or engineering-contraction signals.
- 81–100: broad, corroborated critical capability rebuild pressure; requires multiple independent signals.
- Missing job data, unknown job endpoint costs, or no matches must be marked unavailable—not interpreted as no hiring.

## S5 — Competitor talent movement (10%)

### Inputs
- User-confirmed competitor domains.
- Returned profile history supports previous target employment and current role/employer matching a listed competitor.
- Relevant seniority/technical role classification.

### Rules
- Count unique people, not profile records.
- Match by verified domain/company resolution where possible; don't assume similarity from name alone.
- Weight only for role/thesis relevance; do not claim the competitor gained IP, trade secrets, or unfair advantage.
- Treat this primarily as corroborating evidence. If a competitor’s subsidiary/parent identity is unclear, flag for review.
- Current employee movement alone is not proof of risk; the significance depends on timing, role criticality, and the deal thesis.

## Composite score and coverage

Let `w_i` be the configured weights above and `s_i` each scored signal. `A` is the set of signals with sufficient evidence. Compute:

`assessable_weight = sum(w_i for i in A)`

`risk_score = sum(w_i * s_i for i in A) / assessable_weight`

`coverage_pct = 100 * assessable_weight / sum(all configured weights)`

Do not publish the composite as a full assessment if coverage < 60%. Show `INSUFFICIENT EVIDENCE` and only the individual scorable signal results. At 60–79% coverage, label the composite “provisional.” At ≥80%, label “coverage threshold met,” not “validated prediction.”

Risk bands (display labels only): 0–24 Low signal, 25–49 Watch, 50–69 Elevated, 70–100 High signal. These thresholds are unvalidated and must be shown as heuristics.

## Evidence confidence (separate metric)

Compute confidence from coverage and quality factors—not the same weighted risk score:
- Field completeness for required inputs (0–30 points).
- Recency/timing adequacy (0–20).
- Independent corroboration (0–20).
- Peer comparability (0–15).
- Source/identity resolution quality (0–15).

The first MVP may implement this as transparent deterministic sub-scores. Always show inputs and avoid a false claim of statistical calibration. Missing data lowers confidence; it must not lower risk by itself.

## Anti-patterns prohibited in scorecards

- No unexplained LLM-generated score.
- No invented industry averages or “1.2 years vs 3.4 years” unless both values are sourced and cohort method is shown.
- No treating profile sample as a company-wide census.
- No claims about employee quality, loyalty, protected classes, or private attributes.
- No valuation haircut without an independently specified financial impact model and human review.
