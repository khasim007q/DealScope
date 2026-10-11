# 06 — Crustdata Integration and 5,000-Credit Budget

## 1. Budget policy

The hackathon page says participants receive 5,000 Crustdata credits. The app must preserve a reserve and must not treat free credits as unlimited. Default policy:

- Starting allocation: `5,000` (configure actual available balance from account, do not hardcode as guaranteed current balance).
- Global reserve: `1,000` (20%; do not spend in MVP unless the owner explicitly changes policy after checking the account).
- Maximum product budget for planned testing: `4,000` estimated credits.
- Default per-case ceiling: `300` estimated credits.
- Initial live demo: target below `100` credits when using only low-cost enrichment/search operations; stop and inspect actual metering after first smoke test.
- Enrichment cap: 20 individual person enrichments per case (prefer search and already-returned profile data first).
- Company cap: target plus up to five peers.
- People search: default max 100 results per query; no uncontrolled pagination.
- Job endpoint: disabled in live mode until the current pricing table/account console has been checked and a conservative per-result or per-call reserve is set in configuration.

The figures above are operational safety caps, not an estimate that every audit will consume exactly that amount.

## 2. Published cost facts to use (reverify before live calls)

Public product pages currently show:
- Company Search: `0.03 credits / result`.
- Company Enrichment: `2 credits / profile`.
- People Search: `0.03 credits / returned profile`.
- Cached People Enrichment starts at `1 credit / profile`; contact data or live-from-web retrieval may cost more.
- Jobs API uses the shared credit balance, but the public page directs users to the endpoint pricing table for the exact cost. Do not invent a price.

Reference: https://crustdata.com/company-data-api  
Reference: https://crustdata.com/people-api  
Reference: https://crustdata.com/apis/job-listing

The API's actual usage/account balance is the source of truth. Endpoint price can vary with enrichment mode and data fields.

## 3. Suggested first audit budget (planning arithmetic only)

| Operation | Planned max | Known/expected credit rule | Budget stance |
|---|---:|---|---|
| Target company enrichment | 1 profile | 2 credits/profile documented | 2 credits |
| Peer enrichment | Up to 5 profiles | 2 credits/profile documented | Up to 10 credits |
| People search | Up to 100 profiles returned total initially | 0.03 credits/result documented | Up to 3 credits |
| Cached enrichment of selected key profiles | Up to 20 profiles | starts at 1 credit/profile; real-time may cost more | reserve 20 only if cached pricing confirmed |
| Jobs queries | Small bounded query count | exact cost must be verified | no call until price is configured |
| LLM calls | max 8 planning turns plus report | depends on configured model; not Crustdata credits | track separately in neatlogs/cost log |

These are not guaranteed final costs: failed calls, live enrichment, response size, and provider pricing can change the bill. The agent must use actual usage records whenever returned and compare with the account dashboard after smoke tests.

## 4. `CreditGovernor` behavior

Before every metered action:
1. Determine operation and max possible result count.
2. Load the current confirmed price/config.
3. Estimate worst-case credits for the requested result cap, plus a safety multiplier if actual pricing has variability.
4. Check `case_estimate + reservation <= per_case_cap`.
5. Check `global_estimate + reservation <= total_credits - global_reserve`.
6. If price is unknown, reject the action with reason `UNKNOWN_PRICE_FAIL_CLOSED`.
7. Persist reservation before request.
8. Settle reservation after response with actual cost if returned/accounted; otherwise retain conservative estimate and mark `actual_unknown`.
9. Never let the model alter the price or cap.

The UI should distinguish: `confirmed actual`, `estimated`, `reserved`, and `unknown`. Don't describe estimates as actual spend.

## 5. Caching and deduplication

- Cache successful enrichment results by normalized domain/profile, requested field set, provider API version, and freshness policy.
- Reuse within same case and on restart. For report reproducibility, store a source snapshot plus `retrieved_at`.
- Do not reuse stale profiles as a current-state claim without showing retrieval date.
- Do not retry a call when previous outcome may have been billable but unknown until it is checked or the user explicitly chooses to continue with risk.

## 6. Crustdata adapter implementation checklist

- Confirm current endpoint path and request schema from official docs.
- Confirm current API version header and auth format.
- Confirm company/people enrichment price for the precise request mode.
- Confirm Jobs API price, request limits, and response fields in the account/docs before enabling.
- Start with one company enrichment in a smoke test; confirm response shape and usage.
- Persist response field coverage; do not assume optional fields exist.
- Never query private personal/contact fields because this product doesn't need them.
- Add mocked tests for 401, 429, 500, malformed JSON, empty data, duplicates, and a job endpoint with unknown price.
