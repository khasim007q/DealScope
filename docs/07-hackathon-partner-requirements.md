# 07 — Required neatHack Partner Integrations

The published neatHack requirements say every project must use **neatlogs, Entire, and cfo.ai**. The use of all three is part of the 25% partner-tool category, and judges expect checkable evidence. They are distinct integrations with distinct jobs.

## 1. neatlogs — runtime observability and improvement proof

### Product role
Trace each DealScope run so the team can inspect the agent plan, tool calls, failures, retries, score recalculations, verifier decisions, and final report. This is a product runtime integration, not just a screenshot of the neatlogs website.

### Implementation
- Install the Python package and use current official SDK docs: https://docs.neatlogs.com/sdk/python
- Initialize with `NEATLOGS_API_KEY` in non-fixture judged runs.
- Instrument the configured model client with `neatlogs.wrap(...)` if supported, or use documented instrumentation for the selected client.
- Add named spans for `investigation_workflow`, `plan_next_action`, each `crustdata_tool`, `score_signals`, `verify_claims`, `render_memo`, `recover_run`.
- Add safe structured attributes: `case_id`, mode, stage, tool name, attempt number, result count, cost estimate/actual when known, current coverage, stop reason, and score version.
- Flush/shutdown correctly for short scripts and tests.
- Use redaction/data minimization; don't log API keys or all raw profiles.

### Required proof
- At least one successful live Crustdata run trace.
- One injected failure trace showing retry/resume/stop behavior.
- A baseline-versus-improved run pair, with documented metrics compared (e.g. grounded claim rate, unsupported findings, tool-call count, duration, cost estimates).
- Screenshot or trace links saved under `evidence/neatlogs/`.

### Improvement experiment
Baseline run: weak report synthesis prompt, tested only on synthetic fixture; measure citation coverage, unsupported claims, and tool calls.  
Improved run: add strict evidence schema + deterministic verifier + alternate-explanation requirement; rerun the exact same fixture.  
Expected direction (must be measured, not fabricated): fewer unsupported claims, higher citation coverage, and possibly one extra verification action. Record actual numbers and keep both trace IDs.

## 2. Entire — coding-agent context and change checkpoints

### Product role
Make the code changes made with Claude Code traceable to the context and decisions that produced them. This is development workflow evidence, not an application runtime dependency.

### Setup workflow
- Install/configure Entire from official instructions: https://entire.io/
- Inside the repository, run the live CLI help, preferably `entire agent-help` if supported, and follow commands exposed by the installed version. Do not assume an old subcommand/flag.
- Enable the compatible Claude Code integration using current docs/CLI.
- Make meaningful changes in small commits during the official hackathon window.
- Verify checkpoints are linked to commits/sessions. If `entire-graph` is available, generate one useful dependency/context view; otherwise checkpoints are the minimum proof.
- Before a risky change, capture a checkpoint; after fixing a failing test, commit and show the before/after trail.

### Required proof
- Screenshot/export of an Entire checkpoint paired with a project commit and coding session.
- Optional entire-graph output that explains one important code path (orchestrator → tool → budget guard → persistence).
- Note the exact CLI version/commands used in `evidence/entire/README.md`.

Do not claim Entire integration is complete until the checkpoint/graph evidence exists.

## 3. cfo.ai — explicit business plan

### Product role
Build the required business plan in cfo.ai covering pricing, costs, revenue and runway. This is a founder/business planning integration, not a runtime API call.

### Action
- Use the neatHack signup flow at https://cfo.ai/neathacks; follow the official signup/cancellation guidance on the page.
- Paste the business-plan brief from `08-cfoai-business-plan.md` into cfo.ai.
- Adjust its model using observed LLM token costs and Crustdata per-case credit estimates/actuals from test runs.
- Save the resulting plan/export or screenshots under `evidence/cfo-ai/` and cite them from `SUBMISSION_EVIDENCE.md`.

### Required proof
- cfo.ai model output showing pricing assumptions, cost structure, conservative/base/growth scenarios and runway.
- State all forecasts are assumptions. Never present invented customer traction as real.

## 4. Mandatory demo coverage

The ≤3-minute demo must explicitly show:
- agent goal, plan, tools, stateful iteration, and final verified result;
- neatlogs trace + failure recovery + before/after comparison;
- Entire checkpoint/graph;
- cfo.ai business plan and unit economics.

## 5. Hackathon rule guard

The official page says code must be written during the event and the public repository must show hackathon-dated commits. This spec pack is a plan; do not import a finished external implementation. Keep credentials and private traces out of the public repo.
