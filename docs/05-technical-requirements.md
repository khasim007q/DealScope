# 05 — Technical Requirements (TRD)

## Runtime

- Python 3.12 preferred. neatlogs currently documents Python support for 3.10 ≤ version < 3.14; verify compatibility against chosen dependency lockfile.
- UI: Streamlit.
- Validation/domain contracts: Pydantic v2.
- Persistence: built-in `sqlite3` or SQLAlchemy 2.x. Prefer the simpler option that supports explicit transactions/checkpoints.
- HTTP: `httpx` with connect/read/write timeouts.
- LLM: one configured vendor SDK behind `LLMProvider` interface. Initial implementer may choose Anthropic if a runtime API key exists, but do not assume Claude Code subscription is an API key. No hard dependency on Bedrock/AWS.
- Test: pytest, pytest-cov.
- Report: Markdown first; PDF only after end-to-end requirements are stable.
- Observability: `neatlogs` Python SDK.

## Environment contract

See root `.env.example`. Required for live mode:
- `CRUSTDATA_API_KEY`
- `LLM_PROVIDER` and vendor runtime API key (not the coding-agent subscription)
- `NEATLOGS_API_KEY` for judged runs; app may run locally without it but must show observability is not connected.

Optional:
- `LLM_MODEL` provider model identifier
- `CRUSTDATA_API_VERSION` default to the verified version from official docs (public examples currently show `2025-11-01`)
- `CRUSTDATA_TOTAL_CREDITS=5000`
- `CRUSTDATA_GLOBAL_RESERVE_CREDITS=1000`
- `CRUSTDATA_MAX_CASE_CREDITS=300`
- `CRUSTDATA_MAX_ENRICHED_PEOPLE=20`
- `CRUSTDATA_MAX_PEOPLE_SEARCH_RESULTS=100`
- `CRUSTDATA_JOB_COST_PER_RESULT` / `CRUSTDATA_JOB_CALL_RESERVE` only after confirmation from account pricing; absent means live Jobs API disabled
- `DEALSCOPE_DB_PATH=./data/dealscope.sqlite3`
- `DEALSCOPE_MODE=live|synthetic`
- `DEALSCOPE_MAX_ITERATIONS=8`
- `DEALSCOPE_MAX_TOOL_CALLS=12`
- `DEALSCOPE_MAX_RUNTIME_SECONDS=240`
- `DEALSCOPE_HTTP_TIMEOUT_SECONDS=25`
- `DEALSCOPE_MAX_RETRIES=2`

## API requirements

- Use bearer authorization; never log it.
- Validate all response codes and parse JSON defensively.
- Retry only transient error classes; use bounded retries with jitter and a total request deadline.
- Set connection and read timeouts. Use per-case rate limiter/concurrency of 2 concurrent metered calls max for the MVP.
- Apply response field allowlists and normalize null/missing/empty representations.
- Record provider request ID/usage headers if returned, but do not assume a particular header exists.
- Never paginate without a hard result cap and budget check.
- Validate all endpoint-specific fields against official docs rather than relying solely on these specification notes.

## Quality gates

1. `ruff check .` or equivalent lint command passes.
2. `mypy` is optional if time; type critical domain contracts.
3. `pytest` passes without live credentials using fixtures/mocks.
4. Live smoke test is opt-in and makes an explicitly limited number of requests.
5. App starts without live credentials in fixture mode; live mode must fail closed on missing key.
6. No secrets, live SQLite DB, or real profiles in Git.
7. `git grep`/secret scan before public repository push.
8. README setup instructions are tested on a clean environment.

## Resilience requirements

- API failures cannot erase previous findings.
- Tool results are persisted before next planner turn.
- Credit governor blocks unknown-price endpoints and over-cap requests.
- If LLM is unavailable after evidence collection, deterministic signals remain viewable and a partial report can be rendered with a clear note that narrative synthesis was unavailable.
- If neatlogs is disconnected, local run remains usable, but hackathon evidence checklist must remain incomplete until a traced run is captured.

## Security and privacy

- `.env` and `data/` must be gitignored.
- Avoid storing personal contact details; request fields needed for job/role timeline only.
- Do not send raw full provider objects into LLM context. Send filtered normalized fields with source IDs.
- Do not put full prompt/entire people profiles into neatlogs if they contain unnecessary personal information. Prefer redacted summaries and opaque evidence IDs.
- Limit report shareability; user chooses when to export a report about a real company.

## Non-goals

No AWS requirement, serverless stack, Redis, Celery, vector store, external browser scraping, or multi-tenant SaaS auth within the hackathon MVP.
