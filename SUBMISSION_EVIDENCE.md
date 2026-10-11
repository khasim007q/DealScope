# Submission Evidence Register (fill in truthfully)

This file is a checklist/index. It does not itself prove that integrations were used.

## neatlogs
Files: `evidence/neatlogs/successful-run.md`, `evidence/neatlogs/failure-recovery.md`, `evidence/neatlogs/baseline-vs-improved.md`, `evidence/neatlogs/screenshots/`
- Successful live trace URL/ID: `d3a8f383b6cf980bfc51fcdc436478cd` (+ memo regeneration `81dd213dbdbc546acd906ecf44f66478`) — see `evidence/neatlogs/successful-run.md`
- Failure-recovery trace URL/ID: `9e30eca63a3634b9a6f1b8ffe29770c9` -> resume `3665d83293f0eab47ddb542835ff4622` — see `evidence/neatlogs/failure-recovery.md`
- Baseline run trace URL/ID: A `28fe5ba00882582eb3d298795274dff9`, B `d0e4b0e650a5dd7fe21fc9b8a244decf`
- Improved run trace URL/ID: A `4475d391852dad1707054011b73a3d11`, B `526d3215aee19b3f355e610e2ae47c19`
- Metrics compared and measured values: see `evidence/neatlogs/baseline-vs-improved.md` (unsupported 0 vs 0; verified 2 vs 5)
- Screenshot paths: `TODO`

## Entire
Files: `evidence/entire/README.md`, `evidence/entire/screenshots/`
- CLI version: `Entire CLI 0.11.4`
- Commands used (exact): install `irm https://entire.io/install.ps1 | iex`; owner ran `entire login`, `entire enable --agent claude-code`, `entire doctor`; agent ran `entire agent-help`, `entire status`
- Checkpoint/commit/session link or screenshot: commit `70400f8` carries `Entire-Checkpoint: 01M4NTHZJBFDKJ80R5FCA3CDZS` (linked to this Claude Code session); 5 checkpoint refs on origin (`git ls-remote origin | grep checkpoints`). Screenshot TODO. Note: the hook asks an interactive "Link this commit to session context?" question, which is why agent-made commits blocked.
- entire-graph output if available: `TODO`

## cfo.ai
Files: `evidence/cfo-ai/README.md`, `evidence/cfo-ai/assumptions.md`, `evidence/cfo-ai/plan.png` or `exported-plan.pdf` (not yet created)
- Shared model link: https://cfo.ai/s/LuzFz_Xw5PkfkLJJ (page "DealScope — Model formulas", horizon Oct-26 -> Sep-27)
- Date plan generated: 2026-10-11 (shared by owner)
- Export/screenshot path: `evidence/cfo-ai/` (exported-plan.pdf.xlsx, investor-summary PDF, four workbooks)
- Verified from the export (`evidence/cfo-ai/exported-plan.pdf.xlsx`, sheets "DealScope monthly model and pricing
  alternatives", "Model inputs", "Export notes"), monthly Oct-26 -> Sep-27:
  - Pricing: per audit $750 / $1,500 / $3,000; annual deal-team $24,000 incl. 24 audits + $1,000 overage; hybrid
    $6,000 workspace + $1,000/audit. Selected plan: per audit base.
  - Costs: delivery COGS $94.65/audit (QA 1.5 h x $60, tooling $2, Crustdata 26 credits x $0.10 = $2.60, LLM $0.05);
    payment processing 3%; support; fixed $750/month (hosting $150, software $100, sales/marketing $500), compliance
    $500/month from month 6; founder salary $0 (input).
  - Revenue, gross profit, contribution profit, operating profit, net cash burn, gross and contribution margin by
    pricing model (plan: 93.7% gross / 90.0% contribution margin at $1,500/audit, 5 customers x 3 audits/month).
  - Runway: opening cash not supplied (cash switch 0) -> conditional cash balance left blank; cumulative funding gap
    0 because the modeled plan is cash-generative. No cash or traction invented.
- Scenarios and runway (owner exports added 2026-10-11): `DealScope-investor-summary.pdf` (one-page summary;
  conservative / base / growth: revenue $30,000 / $270,000 / $390,000, gross margin 87.20% / 93.69% / 90.54%,
  peak modeled funding need $1,500 / $0 / $0; cash unknown, runway blank), `DealScope — Business summary.xlsx`
  (scenario comparison, conditional runway), `DealScope — Financial projection.xlsx` (12-month projection, variable
  cost detail, conditional cash and runway), `DealScope — Pricing and sensitivity.xlsx` (audit frequency, discount,
  data-cost sensitivities), `DealScope — Assumptions.xlsx` (editable drivers).
- Note: Crustdata credits/audit in the model is the pre-run estimate (26); measured live runs used 9.18 and 12.21
  credits, so the modeled data cost is conservative.

## Crustdata
- Account usage before/after smoke test: 200.0 -> 198.0 (`X-Credits-Used: 2`)
- Endpoints actually called: /account/credits, /account/endpoints (free), /company/enrich, /person/search, /job/search
- Actual/estimated usage and unknowns: 23.39 credits actual (2 + 9.18 + 12.21), 0 unknown-outcome calls
- Crustdata: API docs/pricing verified on 2026-10-11 (docs/10-crustdata-api-reference.md). Documentation review only, not a live call.

## Build in public
Files: `evidence/build-in-public/post-draft.md`, `evidence/build-in-public/post-url.txt`
- `#neatHack` post URL: `TODO`

## Demo / submission
Script: `docs/demo-script.md`
- Demo video (≤3 min): `TODO`
- Public repository URL: https://github.com/khasim007q/DealScope
- Public quote-post submission URL: `TODO`
- Final deadline confirmed in Discord: `TODO`
