# Demo script (3 minutes max)

Follows docs/09 section 3. Keep neatlogs, Entire and cfo.ai visibly on screen. Do a dry run first, and narrate only results you actually have (do not describe a live Crustdata run unless one was done).

Prep: app running (`.venv/Scripts/uvicorn dealscope.api.server:app --port 8000`, open http://localhost:8000; the featured notion.com case is imported locally from `fixtures/featured/`, which is gitignored), neatlogs dashboard with the run traces open in a tab, Entire checkpoint view (`entire checkpoint list` or screenshot) and the cfo.ai plan open in tabs.

| Time | Screen | Say / do |
|---|---|---|
| 0:00-0:20 | **New investigation** | Problem: early diligence misses organizational risk. Show the Live vs Demo choice, target, competitors and thesis. Click **Check companies** to show the free identity check (mention notion.so resolving to 23 records). |
| 0:20-0:55 | **See a finished live example** (featured notion.com case) | Opens instantly without spending credits. Walk the summary: risk 32 (Watch), coverage and confidence as separate bars, "How to read this". |
| 0:55-1:25 | Same case: **How the agent investigated** + signal cards | Point at steps marked **AI planner** with their reason, the plain-language signal findings, then a finding with its evidence and "Other possible explanations". |
| 1:25-1:50 | New demo case with **Simulate a failure: outage that outlasts retries** | Show retries, the "Partial - can resume" status, press **Resume**; then show the same failure/resume pair in **neatlogs** (traces `9e30eca6...` / `3665d832...`). Optionally press **Stop investigation** on a running case. |
| 1:50-2:15 | **Evidence** page | neatlogs runs and the baseline-vs-improved table (honest result: 0 unsupported claims either way; improved has more fully verified claims), screenshots. |
| 2:15-2:35 | **Evidence** page, Entire section (+ terminal) | Commit-to-checkpoint pairs read from git; `entire checkpoint explain 01M4QTX0BRBQSWDQ1TTCEFYKJ7`. |
| 2:35-2:55 | **Evidence** page, cfo.ai section (+ investor PDF) | Pricing, $94.65 unit cost, three scenarios; runway blank because cash is unknown; real runs show data and AI costs below the model's assumptions. |
| 2:55-3:00 | **Compare** + repo | Compare notion.com vs airtable.com side by side; point to the repository, CI badge and README. |

Rules: no claims of attrition, causation or valuation. Any partner screen not yet captured must not be shown as proof (see `SUBMISSION_EVIDENCE.md`).
