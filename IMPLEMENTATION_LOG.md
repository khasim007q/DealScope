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

### 2026-10-11 ~20:15 IST — traced proof runs and fixes
- Gemini free tier: 20 requests/day per model family; gemini-3.8-flash and gemini-3.6-flash (shared with 3.5) both
  exhausted during testing (503/504 retries also count). Owner declined billing. Switched to gemini-3.6-flash for the
  live run, gemini-3.1-flash-lite for the eval. Added advised-delay retry for per-minute 429s (<=40 s); daily-quota
  429s fail fast.
- Bug found by the failure trace: resume cleared the failed baseline enrichment but never re-ran it (case reached
  `complete` without target data). Fixed: pending baseline actions run on resume; test now asserts recovery.
- Memo bug: S2 departure observation counted intervals outside the lookback window (2021–2026). Fixed to use the same
  window as the S2 score.
- neatlogs root span now records short input/output summaries (dashboard Input/Output columns were empty).
- Live proof run `case-289f654e60f5` (airtable.com vs smartsheet.com, monday.com, clickup.com): 7 tool calls, all 3
  planner decisions by Gemini, 12.21 credits actual, trace `d3a8f383b6cf980bfc51fcdc436478cd`; memo regenerated with
  Gemini drafting (0 new tool calls) trace `81dd213dbdbc546acd906ecf44f66478`.
- Failure recovery (synthetic): trace `9e30eca63a3634b9a6f1b8ffe29770c9` (partial after 503x3) ->
  `3665d83293f0eab47ddb542835ff4622` (resumed, complete, no duplicate calls).
- Baseline vs improved (deterministic planner, gemini-3.1-flash-lite drafting): no difference in unsupported claims
  (0 vs 0 on both fixtures); improved produced more outright-verified claims (5 vs 2) and explicit questions.
  Recorded as-is in `evidence/neatlogs/baseline-vs-improved.md`.
- Crustdata spend to date: 2 (smoke) + 9.18 (Retool) + 12.21 (Airtable) = 23.39 credits actual of 200.
- Tests: 260 passed; ruff clean.
- Entire: enabled by owner; 4 checkpoint refs pushed on 19:14 push. `prepare-commit-msg` hook blocks indefinitely when
  invoked from this agent session (idle, no log output; `entire doctor` reports OK). Commit `a86ab8d` completed only
  after the hook process was stopped (no Entire-Checkpoint trailer); commits otherwise paused pending owner decision.

### 2026-10-11 ~21:50 IST — live browser test (Streamlit UI, live Crustdata)
- Run 1 (`case-1177e8f2bcd0`, notion.so vs coda.io, airtable.com, clickup.com): target enrichment charged 6 credits
  but produced no evidence; all signals not scored; INSUFFICIENT EVIDENCE shown honestly. Root cause: notion.so is an
  ambiguous hosting domain in Crustdata (23 exact matches of unrelated small companies); Notion's indexed domain is
  notion.com. The primary-domain check correctly refused the junk matches, but credits were already spent.
- Fix (FR-01): free `/company/identify` pre-check for every domain before any metered call (UI and CLI). A run is
  refused unless each domain resolves to exactly one company with that primary domain; candidates are shown.
  Verified in the browser: notion.so flagged `mismatch` (23 matches, suggests notion.com), 0 credits spent.
- Run 2 (`case-d60a330a199c`, notion.com): complete, 4 planner turns, 36 evidence, 4.82 credits actual, risk 32 (Watch),
  coverage 92%, confidence 87, trace `b3875a81576975a4536e4bf132c8c7bb`. Exposed provider data discontinuities:
  peer engineering growth of +304% to +500% (Airtable, ClickUp) that produced an absurd peer-range finding.
- Fix: `analysis/data_quality.py` drops implausible growth values (>60%/1m, >100%/3–6m, >250%/12m, >500%/24m, for
  headcount >= 20) before scoring; flags listed in the memo's data-coverage section. Growth figures rounded to 0.1.
- Run 3 (`case-fedaa94215ba`, same inputs, fully cached, 0 credits): Gemini (gemini-3.1-flash-lite) chose all three
  planner actions; memo 12 claims, 0 rejected; anomalies listed as data-quality flags; trace
  `4e64b2898a114a65b3de4608de851bfe`.
- Crustdata spend to date: 2 + 9.18 + 12.21 + 8 + 4.82 = 36.21 credits actual; balance ~163.8.
- Tests: 265 passed; ruff clean.

### 2026-10-12 — TypeScript frontend, plain-language API, walkthrough
- Owner feedback: the Streamlit UI showed internals a normal user could not interpret. Replaced with a React +
  TypeScript (Vite) frontend (`frontend/`) and a FastAPI server (`src/dealscope/api/server.py`). `api/views.py`
  translates reason codes, stages and outcome codes into plain sentences; raw codes only appear under
  "Technical details". No emojis. Streamlit app removed.
- Contract-first build: Opus wrote `frontend/src/api/types.ts` and `frontend/src/content/types.ts`; one Sonnet agent
  built the frontend against them while another wrote `docs/walkthrough.md` and the in-app "How it works" content
  (13 neatlogs screenshots mapped; Entire transcript referenced).
- Bug found while reconciling walkthrough facts: synthetic (demo) runs were counted against the live account-wide
  cap, so after many demo runs synthetic tool calls were blocked (GLOBAL_SPENDABLE_BUDGET_EXCEEDED); this
  invalidated the first scenario B eval. Fixed (global cap applies to the live pool only; per-case cap still applies)
  and scenario B re-run: baseline `39ee81cc2045fe5f160e428bb24943cd`, improved `e63bac7e90a7d4de175c300f139a82a2`.
- Live browser test of the new UI (`case-0e61a0b82462`, notion.com vs coda.io, airtable.com, clickup.com): free
  identity check all matched; complete; risk 32 (Watch), coverage 93%, confidence 84; Gemini (gemini-3.1-flash-lite)
  made the planner choices and drafted findings; 10.82 credits actual.
- Fixes from that review: memo departure count now uses the same critical role groups as S2 (was "two" vs signal "1");
  engineering-growth limitation text corrected; risk shown as an integer everywhere; planner wording ("Every useful
  data source ... has already been checked"); step titles use "Next step: search ..."; unknown `/api/*` paths 404.
- Crustdata spend to date: 36.21 + 10.82 = 47.03 credits actual. Tests: 272 passed; ruff clean; frontend typecheck
  and build pass.
