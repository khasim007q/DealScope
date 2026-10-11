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
