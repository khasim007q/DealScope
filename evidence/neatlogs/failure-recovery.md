# neatlogs: failure recovery

Status: captured 2026-10-11 (`failure-recovery-20261011T143846Z.json`). Synthetic fixture, 0 Crustdata credits,
deterministic planner (`scripts/run_case.py --no-llm failure`). Dashboard screenshots still TODO.

| Field | Value |
|---|---|
| Case id | `case-614abd88e5d0` (scenario_a fixture, SYNTHETIC) |
| Injected failure | `enrich_company` on the target: HTTP 503, 503, 503 |
| Retry behaviour | 2 bounded retries with jittered backoff (retry events on the tool span), then `RETRY_EXHAUSTED`; no infinite retry; ledger kept the conservative estimate |
| First run trace | `9e30eca63a3634b9a6f1b8ffe29770c9` — stage **partial**, finish `no_candidates_with_1_failed_actions`, 7 tool calls, S1 not scored (no target data) |
| Restart | new process-equivalent: fresh `Repository` connection + orchestrator on the same SQLite file |
| Resume trace | `3665d83293f0eab47ddb542835ff4622` — `recover_run` span; failed enrichment retried once and succeeded; stage **complete**, 8 tool calls total, S1 scored |
| Duplicate metered calls after resume | none (idempotency keys of succeeded runs are unique; enforced by `test_t10_retry_exhausted_then_resume_without_repeating_calls`) |
| Superseded traces | `5366ba566b2a5941e47dcae66d9d9fb9` / `f748214a3279fa2fe4f4dd545144d5e1` — earlier attempt that exposed a bug (resume skipped the failed baseline enrichment); fixed and re-run above |
| Screenshot path | TODO (`evidence/neatlogs/screenshots/...`) |
