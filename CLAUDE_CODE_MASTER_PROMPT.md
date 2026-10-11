# Claude Code Master Prompt — DealScope

You are the senior engineer implementing DealScope for the neatHack AI agent hackathon. Follow the specification pack in this repository. Build a small, coherent working product, not an architecture-only scaffold and not a generic LLM wrapper.

## Read these first

Read, in order:
1. `README.md`
2. `docs/00-product-and-scope.md`
3. `docs/01-hld.md`
4. `docs/02-lld.md`
5. `docs/03-functional-spec.md`
6. `docs/04-signal-catalog.md`
7. `docs/05-technical-requirements.md`
8. `docs/06-crustdata-credit-budget.md`
9. `docs/07-hackathon-partner-requirements.md`
10. `docs/08-cfoai-business-plan.md`
11. `docs/09-evaluation-demo-submission.md`

Then inspect the existing repository and its test/lint conventions before changing it.

## Non-negotiable product behavior

1. Implement an adaptive, bounded investigation loop. A model/tool result must change the next action when evidence changes. If the agent merely calls a fixed list of endpoints and summarizes the output, the task is not complete.
2. Persist case state and evidence in SQLite at every tool-result boundary. Demonstrate resume after restart.
3. Use Crustdata in live mode with `CRUSTDATA_API_KEY`. Read current official API docs before implementing calls. Public examples currently show bearer auth and `x-api-version: 2025-11-01`, but verify this before use.
4. Use the 5,000-credit allocation responsibly: conservative estimate, default 1,000-credit global reserve, 300-credit per-case cap, hard result caps, cache, and no unknown-price endpoint calls. In particular, confirm the current Jobs API per-endpoint price from official docs/account pricing; if unknown, disable it rather than inventing a cost.
5. Score only the five signals specified in `docs/04-signal-catalog.md`. Compute scores deterministically. Missing fields result in not-scored/low-coverage, not zero risk.
6. Keep risk score, evidence confidence, and evidence coverage separate.
7. Every material factual claim in the report must cite valid evidence IDs. Reject unsupported attrition-rate claims, causal allegations, and valuation recommendations.
8. Keep runtime model provider configurable. A Claude Code subscription is not automatically a runtime API key. Never rely on AWS credits. When runtime credentials are absent, make fixture mode available and label it loudly as synthetic.
9. Use neatlogs in runtime. A successful real run must create a trace; include meaningful tool spans, retries, state transitions, score changes, and report verification. Do not leak secrets or unnecessary personal details into traces.
10. Use Entire as part of the coding workflow. Inspect the installed CLI's current help (e.g. `entire agent-help` where supported), instrument the coding session, and create checkpoints linked to commits. Do not fabricate screenshots/results.
11. Use cfo.ai via its official neatHack flow to create the required business plan; add a checklist/place to store actual exports/screenshots. Do not claim completion until evidence exists.
12. Build in public and prepare a ≤3-minute demo as documented.

## Implementation workflow

### Phase A — Repo and integration discovery
- Inspect files, git status, Python version and active test setup.
- Check required environment values; never print secrets.
- Read current official Crustdata, neatlogs, and Entire docs where needed.
- Add `IMPLEMENTATION_LOG.md` recording decisions, commands, encountered failures, and reasons. Don't include keys.
- Write a short task checklist and then proceed without waiting for clarification unless blocked by a truly unavailable credential/required external service.

### Phase B — Thin vertical slice
- Implement settings and `.env.example`.
- Implement typed normalized models and SQLite persistence.
- Implement credit governor and fake provider tests first.
- Implement one current official Crustdata company enrichment call and validate actual JSON shape in a limited smoke test if credentials are available.
- Implement live/synthetic mode separation.
- Build a minimal Streamlit case creator and evidence timeline.

### Phase C — Signals and adaptive loop
- Implement the five deterministic signal functions with unit tests from the signal catalog.
- Implement an allowlisted tool layer; never pass raw LLM arguments directly into HTTP requests.
- Implement planner decisions as strict typed JSON or provider-native tool calling. Bound iterations, calls, runtime, and credit budget.
- Implement adaptive branches proving that different evidence gaps lead to different actions.
- Persist before/after each external call and support resume.

### Phase D — Claim verification and report
- Build a normalized evidence index for LLM synthesis.
- Generate claims in a schema that includes evidence IDs, counter-evidence IDs, interpretation type, confidence, and limitations.
- Implement deterministic ID/entity/date/direction checks. Drop unsupported claims and report why.
- Render a useful memo with scorecard, confidence, evidence, alternative explanations, questions, data coverage and caveats.

### Phase E — Partner tools and proof
- Instrument the run using the current neatlogs Python SDK. Verify a trace exists in the real dashboard.
- Run a baseline and improved evaluation on the same synthetic fixture; capture real metrics/trace IDs.
- Use Entire CLI/help as installed, create a meaningful coding checkpoint and capture proof.
- Use cfo.ai to create the business plan and save actual evidence.
- Create build-in-public post, demo outline, and evidence checklist.

### Phase F — Quality pass
- Run full tests, lint, clean-environment setup check, and secret scan.
- Exercise failure cases: 429/503 retry, 401 no retry, unknown job price fail-closed, budget exhausted, malformed model action, resume after restart, unsupported report claim rejected.
- Check the app does not silently switch from live mode to fixtures.
- Ensure `README.md` setup commands work.
- Commit small coherent changes during the hackathon. Don't commit `.env`, DB files, private raw responses, or keys.

## Required code-quality expectations

- No monolithic file containing the entire agent.
- Keep the LLM out of deterministic scoring and budget policy.
- Pydantic/schema validation at every untrusted boundary.
- Structured errors; no catch-all swallowing failures.
- Bounded exponential backoff with jitter only for retryable failures.
- Idempotency/cache strategy avoids duplicated metered calls after restart.
- Every material report finding contains at least one evidence ID and may include counter-evidence.
- Test synthetic data with clearly fictional identities/domains.
- Add only dependencies needed for a working vertical slice.
- Don't overengineer with a vector DB, multi-agent swarm, Celery, Redis, or AWS.

## Definition of done

Do not say “complete” until all applicable items are true:
- Working UI creates and runs a case.
- A live Crustdata smoke test succeeds or a concrete external credential/access blocker is documented; fixture mode is fully tested either way.
- Evidence, scorecards, and case state persist.
- At least two adaptive branches are tested.
- Report verifier blocks unsupported claims.
- Recovery/resume test passes.
- Credit governor blocks calls over budget and unknown-price job requests.
- neatlogs trace from a real run and failure trace exist.
- Entire checkpoint evidence and cfo.ai plan evidence are actually captured (owner may need to perform login steps).
- Baseline vs improved eval metrics are measured and recorded.
- Build-in-public/demo/submission checklists are prepared and truthful.
- No secrets or private records committed.

## How to report progress in IMPLEMENTATION_LOG.md

At each milestone record:
- implementation shipped;
- tests run + exact pass/fail count;
- external API requests made + actual/estimated credit usage if known;
- integration artifacts produced (real trace IDs, checkpoint IDs, cfo.ai evidence path);
- failures and what changed afterwards;
- remaining blockers.

Do not substitute a plan for implementation, or a mocked integration for real partner usage. If no key is available, clearly separate the completed fixture path from the unverified live path.
