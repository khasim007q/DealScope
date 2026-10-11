# Implementation Log

No secrets are recorded here. Times are IST (hackathon window 10–12 Oct 2026).

## Working model
- Orchestration: Claude Code (Opus 5.5) as lead engineer writing contracts, planner, tools, orchestrator, UI, and reviewing; Sonnet 5.5 sub-agents implemented isolated modules against those contracts (persistence + credit governor, signal engine, verifier + memo, Crustdata client + fixtures) and researched the current Crustdata docs.
- Runtime LLM: Gemini Flash (`LLM_PROVIDER=gemini`, default `gemini-2.5-flash`) behind `LLMProvider`; optional `LLM_ESCALATION_MODEL` used only for report synthesis. The LLM chooses among deterministic candidate actions and drafts cited claims; Python owns scoring, budget, retry and claim acceptance.

### 2026-10-11 Phase A — discovery
- Environment: Windows 11, Python 3.12 (via `py`/uv venv), git 2.53, uv 0.12. No `gh`. Entire CLI not present → installed 0.11.4 via official `irm https://entire.io/install.ps1 | iex` (user approved). `entire agent-help` says `login`/`enable` are user-run commands → owner to run `entire login` and `entire enable --agent claude-code`.
- No `.env` / keys present at start → fixture path built and tested first; live path pending owner keys.
- Crustdata docs researched → `docs/10-crustdata-api-reference.md`. Key corrections to the spec pack:
  - Person search is **~0.23 credits/result** (0.03 base + 0.1 experience filter + 0.1 experience returned), not 0.03. Governor updated.
  - Jobs search is documented at **0.03 credits/result**, zero-result requests free. Still kept **disabled in live mode** until confirmed against our account via the free `GET /account/endpoints?path=/job/search`, then set via `CRUSTDATA_JOB_COST_PER_RESULT`.
  - Company enrich has no engineering-growth scalar; we derive engineering growth from `headcount.by_function_timeseries.CURRENT_FUNCTION.<Engineering>` (documented as derived in evidence notes).
  - `X-Credits-Used` response header gives actual per-call credits → recorded as confirmed actual.

### Decisions
- `budget/` package added (not in the suggested layout) so credit policy is isolated from the agent.
- Ledger has a `pool` column (`live` | `synthetic`): fixture runs simulate budget accounting but never consume the live 5,000-credit allowance.
- Synthetic runs use the documented 0.03 job price for *simulated* accounting only; live job price comes exclusively from config (absent → `UNKNOWN_PRICE_FAIL_CLOSED`).
- Planner: deterministic code enumerates legal candidate actions (allowlisted, registered domains, not done, affordable). The LLM returns a candidate index + rationale; invalid output gets one corrective retry, then the deterministic policy decides. Raw LLM arguments never reach HTTP.
- Failed actions are not retried within a run (HTTP retry already bounded at 2); an explicit Resume gives failed actions one more attempt; unknown-outcome calls are never replayed automatically.

### 2026-10-11 Budget re-scoped to the real account balance
- Owner reports the Crustdata account has **200 credits**, not 5,000. Policy scaled via config only (no code change):
  total 200, global reserve 40 (20%, never spent), per-case cap 40, people-search result cap 25.
- Planned live spend: free pricing check (0) -> one company enrichment smoke test (~2) -> one or two traced live cases
  (~26 estimated each: 4 enrichments = 8, 2-3 people searches x 25 results x 0.23 = 11.5-17.25, jobs 25 x 0.03 = 0.75
  if enabled). Failure-recovery and baseline-vs-improved experiments run on synthetic fixtures (0 Crustdata credits).

### 2026-10-11 ~19:40 IST — first live run (Crustdata + Gemini + neatlogs)
- Free checks: `GET /account/credits` = 200.0; `GET /account/endpoints` confirmed company enrich 2.0 base,
  person search 0.03 base + experience 0.1 filter / 0.1 field, **job search 0.03 base, no premiums** -> set
  `CRUSTDATA_JOB_COST_PER_RESULT=0.03` (account-confirmed). Evidence: `evidence/crustdata/pricing-*.json`.
- Smoke test: one `/company/enrich` (retool.com) -> `X-Credits-Used: 2`, balance 200.0 -> 198.0.
  Confirmed key spelling `headcount.by_function_timeseries.CURRENT_FUNCTION.Engineering`; only a 12m engineering
  growth point was derivable (no matching 3m/6m points) -> S1 treats it as a single period.
  Note: smoke script bypasses the tool-layer cache, so the live case re-enriched retool.com (2 credits).
- Live case `case-8ddc70b2b4de` (retool.com vs appsmith.com, tooljet.com, budibase.com; cap 40):
  stage complete, 7 tool calls, 4 planner turns, **9.18 credits actual** (from `X-Credits-Used`), risk 22.2,
  coverage 92.5%, confidence 85.9, 4/4 material claims grounded. Plan: search_jobs (deterministic fallback after
  two Gemini 504s) -> search_people x2 (chosen by Gemini) -> stop. neatlogs trace id
  `af87b76d2681d7727d184d8aec363d39` (ingest returned 503 for some span batches during this run; trace may be
  incomplete — check dashboard). Evidence: `evidence/neatlogs/live-run-*.json`.
- Total Crustdata spend so far: 11.18 credits (2 smoke + 9.18 case).
- Failures found and fixed:
  - `gemini-2.5-flash` is no longer available to new users (404) -> default model now `gemini-3.8-flash`.
  - Gemini structured output rejected `maxItems` with 400 INVALID_ARGUMENT -> `gemini_schema()` inlines $refs,
    collapses nullable anyOf, drops titles/defaults/maxItems (pydantic still enforces bounds).
  - Transient 503/504 from Gemini -> one retry with backoff; request timeout 60 s.
  - Memo drafting fell back to deterministic claims (narrative unavailable) — the fail-safe path worked.
- Blocker: Gemini key is on the free tier — `generate_content_free_tier_requests` limit 20/day for
  gemini-3.8-flash, exhausted after testing; resets in ~9.5 h.
