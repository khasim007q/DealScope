# Demo script (3 minutes max)

Follows docs/09 section 3. Keep neatlogs, Entire and cfo.ai visibly on screen. Do a dry run first, and narrate only results you actually have (do not describe a live Crustdata run unless one was done).

Prep: app running (`.venv/Scripts/uvicorn dealscope.api.server:app --port 8000`, open http://localhost:8000), neatlogs dashboard with the run traces open in a tab, Entire checkpoint view (`entire checkpoint list` or screenshot) and the cfo.ai plan open in tabs.

| Time | Screen | Say / do |
|---|---|---|
| 0:00-0:20 | **New investigation** page | Problem: early diligence misses organizational risk. Show target, peer domains and deal thesis (fixture scenario selector; note the `SYNTHETIC DEMO DATA` banner, or switch to LIVE CRUSTDATA with the credit-cap confirmation if a live run was done). |
| 0:20-0:55 | **Create and run case**, then **Case workspace** tab | Show baseline enrichment, the credit panel (case cap, estimated used, reserved) and the first scorecard. |
| 0:55-1:25 | Investigation timeline + Evidence expander | Show the planner's chosen action and its stated reason citing the evidence gap; open an evidence card. Optionally contrast with the other fixture scenario's different next action. |
| 1:25-1:50 | New case, failure injection "503 three times on first enrichment (retry exhausted -> resume)" | Show bounded retries stopping and state kept, then press **Resume case**; completed calls are not replayed. **Show neatlogs**: the failure/retry/resume trace. |
| 1:50-2:15 | Scorecard + Verified memo | Distinguish risk vs evidence confidence vs coverage; show alternative explanations, diligence questions and rejected claims in the appendix. Show **Download memo (.md)** and **Download evidence bundle (.json)**. |
| 2:15-2:35 | **Entire** | Show a checkpoint paired with a commit/session (`entire checkpoint explain <id>`); say it records the coding-agent context behind the change. |
| 2:35-2:55 | **cfo.ai** | Show the plan: pricing, costs, revenue, runway scenarios. State these are assumptions, not traction. |
| 2:55-3:00 | Repo | Point to the repository and the README quickstart. |

Rules: no claims of attrition, causation or valuation. Any partner screen not yet captured must not be shown as proof (see `SUBMISSION_EVIDENCE.md`).
