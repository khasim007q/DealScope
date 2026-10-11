# 02 — Low-Level Design (LLD)

## 1. Modules and contracts

```text
src/dealscope/
  config.py
  domain/models.py
  domain/enums.py
  persistence/repository.py
  persistence/sqlite_schema.sql
  providers/crustdata.py
  providers/llm.py
  agent/planner.py
  agent/orchestrator.py
  agent/tools.py
  analysis/signals.py
  analysis/peer_benchmark.py
  verification/claims.py
  reports/memo.py
  observability/tracing.py
```

### `CrustdataClient`
Methods should be thin, typed wrappers with schema validation. Exact request shapes are to be implemented against current official docs and one controlled test call:

- `enrich_company(domain, fields) -> CompanyEvidence`
- `search_people(query_spec, limit) -> list[PersonEvidence]`
- `enrich_person(profile_url_or_id) -> PersonEvidence` (only when cached/allowed pricing is known; avoid contact-data requests)
- `search_jobs(company_domain, role_terms, date_window, limit) -> list[JobEvidence]`

Company APIs documented publicly use `POST https://api.crustdata.com/company/enrich` and `POST /company/search`; people APIs use `/person/search` and `/person/enrich`. The current public examples use `x-api-version: 2025-11-01`. Job-listing endpoint request schema and pricing must be confirmed in the live API docs / dashboard; fail closed if required pricing is unknown.

Each adapter method should return normalized results with:
- `source_provider`, `endpoint`, `record_id` if available, `source_url`/profile URL if returned, `observed_at`, `retrieved_at`, `data_freshness`, `fields_present`, `raw_hash`, `request_fingerprint`, `cost_estimate`, `cost_actual` if available.
- Store a sanitized normalized subset; do not store unnecessary contact details or raw full response by default.

## 2. Domain models

### CaseInput
```json
{
  "target_domain": "target.example",
  "competitor_domains": ["peer1.example", "peer2.example", "peer3.example"],
  "deal_thesis": "Scale enterprise platform and expand into regulated mid-market accounts",
  "lookback_months": 12,
  "max_case_credits": 300,
  "mode": "live"
}
```

Validate domain syntax, remove URL scheme/path, deduplicate competitors, reject target-as-competitor, require 2–5 peers when possible, and ask user to confirm resolved company identities before a live run. This sample uses placeholders only.

### CaseState
- `case_id`, `status`, `created_at`, `updated_at`
- `input`, `mode` (`live` / `synthetic`)
- `stage` (`created`, `baseline`, `investigating`, `verifying`, `reporting`, `complete`, `partial`, `failed`)
- `plan`, `current_question`, `open_questions[]`, `completed_actions[]`
- `iteration_count`, `tool_call_count`, `started_at`, `deadline_at`
- `credit_budget`, `credit_reserved`, `credit_estimated_used`, `credit_actual_used`, `credit_unknown_calls`
- `evidence_ids[]`, `signal_results[]`, `claims[]`, `latest_checkpoint_id`, `finish_reason`

### EvidenceRecord
- `evidence_id` (UUID), `case_id`, `kind`, `subject_domain`, `entity_id` (opaque)
- `source_provider`, `source_endpoint`, `source_url`, `source_record_id`
- `retrieved_at`, `valid_from`, `valid_to`, `field_coverage[]`, `freshness_class`
- `normalized_payload` (strict allowlist), `raw_hash`, `dedup_key`
- `credit_estimate`, `credit_actual`, `independence_group`
- `synthetic` bool; if true, a report cannot style it as real evidence.

### SignalResult
- `signal_id`, `case_id`, `signal_version`, `score` nullable 0–100
- `state`: `scorable | not_scored | low_coverage | conflicting`
- `weight`, `raw_measure`, `benchmark`, `reason_codes[]`, `evidence_ids[]`
- `confidence` 0–100, `limitations[]`, `calculated_at`

### FindingClaim
- `claim_id`, `text`, `claim_type` (`observation | interpretation | hypothesis | question`)
- `severity`, `confidence`, `evidence_ids[]`, `counter_evidence_ids[]`
- `verification_status` (`verified | qualified | rejected`), `verification_notes`

## 3. Agent execution protocol

### Initial plan

The LLM receives only the case thesis, normalized signal summaries, evidence index, current open questions, allowed tools, remaining iteration count, and remaining credits. It must not receive API keys or unrelated raw profile details.

The model returns strict JSON:
```json
{
  "action": "search_people",
  "arguments": {"role_group": "technical_leadership", "relationship": "past_target_employment"},
  "question": "Are the apparent senior technical departures corroborated?",
  "why_this_action": "The initial company trend is negative but the role-continuity signal has low coverage.",
  "expected_information_gain": "high",
  "stop_after_action_if": ["no eligible profile evidence", "credit cap reached"]
}
```

`action` must match an allowlisted tool. Validate arguments with Pydantic. If the model gives an illegal action, invalid domain, unsupported field, or over-budget query, reject it and use the deterministic fallback planner.

### Iteration pseudocode
```python
while within_limits(state):
    snapshot = summarize_case(state)            # compact and evidence-indexed
    action = planner.choose_next_action(snapshot, allowed_tools)
    validate_action(action, state, policy)
    if action.stop:
        break
    reserve_budget(action, state)               # fail closed when cost unknown
    result = execute_tool_with_bounded_retry(action)
    persist_tool_result_and_checkpoint(result)
    update_evidence_index(result)
    state.signal_results = score_signals(state.evidence)
    state.open_questions = refresh_open_questions(state)
    log_transition_to_neatlogs(state, action, result)

claims = synthesize_findings(state)
claims = verify_claims(claims, state.evidence)
report = render_report(verified_claims_only(claims), limitations(state))
persist_report_and_complete_state(report)
```

### Mandatory adaptive behavior

The agent must not call all tools in the same fixed order for every case. At least two branch policies:
- If R&D/engineering headcount trend conflicts with total headcount or thesis, inspect available department trend/peer data next.
- If multiple technical-leadership departure indicators appear, inspect public people-history records and current critical-role postings next.
- If job data shows few/no critical postings, do not infer distress; test whether data coverage is absent or hiring is simply low.
- If a signal is unsupported by returned fields, mark unavailable and choose another material question.

## 4. Tool definitions (logical contract)

1. `enrich_company(domain, fields_profile)` — allowed only for target/registered peers; expected fields include basic info, headcount/growth, hiring, funding if available, and department headcount if exposed.
2. `search_people(role_group, relationship, competitor_domain?, limit)` — bounded people search using documented filters; return only professional history fields needed by scorecards.
3. `enrich_person(profile_reference)` — optional selective enrichment for a small set of key profiles. Do not request contact fields. Price and request schema must be confirmed.
4. `search_jobs(domain, role_terms, lookback_days, limit)` — current postings only plus supported opening/repost/date fields. Job call must have configured price budget before executing.
5. `get_case_summary()` — returns current signal gaps/evidence state from local storage; free local operation.
6. `calculate_scorecard()` — deterministic compute step; no external API call.
7. `verify_report_claims(claims)` — deterministic citation/claim validation plus optional LLM support check; no source claim passes without evidence IDs.

No generic `fetch_url`, shell, SQL, arbitrary HTTP, email, phone lookup, or unrestricted search tool may be exposed to the LLM.

## 5. Persistence and resume

- On case creation, create checkpoint 0.
- Before a metered request, create a budget reservation record and a `tool_run` row with `status=started`.
- After response, store normalized evidence and settle reservation. If network failure leaves request outcome unknown, mark `unknown_cost`; do not blindly replay a potentially billable request. Ask provider/account usage ledger or require explicit resume choice if idempotency cannot be established.
- Unique idempotency key is `hash(case_id + provider + endpoint + canonical_body + api_version + mode)`; cached successful calls satisfy resume if within freshness TTL.
- If process exits after result but before next action, reload latest checkpoint and continue after the last persisted tool result.

## 6. Retry policies

- `429`, `500`, `502`, `503`, `504`, timeout: at most 2 retries, exponential backoff with jitter; honor `Retry-After` up to configured total deadline.
- `400`: schema/request issue; no retry, record normalized diagnostic.
- `401/403`: stop live mode and show configuration/permission error; no fallback to synthetic data without explicit mode switch.
- LLM structured-action parse failure: one corrective retry; then deterministic planner.
- Budget/unknown cost: no retry and no request.

## 7. Peer benchmarking

- Use peers provided by the user or confirmed by the user; do not autonomously invent peers as fact.
- Target and peers must be enriched consistently for selected comparable fields.
- Peer median preferred over mean; show sample size and dispersion when n ≥ 3.
- If peers differ substantially by size, stage, sector, or geography, mark benchmark weak; do not make strong percentile claims.
- If fewer than 3 usable peers, show absolute trends and label peer comparison low confidence.

## 8. Security / input hygiene

- Domains must match safe hostname syntax; reject local IPs, localhost, file paths, and injected URL schemes.
- LLM-generated arguments never flow directly into HTTP requests without schema validation and allowlists.
- `.env`, sqlite DB, live report files, and secrets are gitignored.
- Logs contain opaque identifiers and only needed normalized fields.
- Use data minimization. Do not return contacts in UI or report.
