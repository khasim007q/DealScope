# DealScope submission video: spoken script (about 3 minutes)

Required by the organizers (12 Oct): one video covering (1) the problem the agent solves, (2) how cfo.ai and Entire
were part of the project, (3) how neatlogs was used to identify and resolve the incidents the agent ran into, shown in
the neatlogs critical-incidents view.

Prep (before recording)
- App running: `.venv/Scripts/uvicorn dealscope.api.server:app --port 8000`, open http://localhost:8000.
- Tabs open: neatlogs dashboard (critical incidents view + the traces listed below), Entire session view
  (`evidence/entire/screenshots/entire-session-timeline.png` or the live page), cfo.ai plan
  (`evidence/cfo-ai/DealScope-investor-summary.pdf`), GitHub repo.
- In the neatlogs incidents view, find the incidents that match the four below (LLM errors, the resume trace, the
  schema error, the ingest gap). Use the incident names neatlogs shows; the wording below explains each one.
- Optional: pre-start nothing. The featured notion.com case opens instantly and costs no credits.

---

## 0:00 - 0:25 | The problem  (screen: New investigation page)

"Before a private-equity firm buys a software company, the deal team has to ask: can this organization actually
deliver the plan? Are senior engineers leaving? Is the company struggling to hire critical roles? That research is
manual and slow, and public data is easy to over-read.

DealScope is an agent that investigates this from public data. You give it a target company, a few competitors and
your deal thesis, and it returns a diligence memo where every claim cites its evidence."

## 0:25 - 1:05 | What the agent does  (screen: open the featured notion.com case)

"This is a live run on Notion against Coda, Airtable and ClickUp. First it checks each domain for free, so it never
pays for the wrong company. Then it pulls company data from Crustdata and decides what to look at next.

Here in the timeline you can see the AI planner choosing its next step and saying why - it checked open technical
roles, then searched for former and current technical leaders.

The result: an overall risk signal of 32, Watch, with coverage and confidence shown separately, five signals in plain
language, findings with their evidence and other possible explanations, and questions to ask management. The whole
run cost under 11 credits, and a verifier rejects anything unsupported - no attrition rates, no accusations, no
valuation advice."

## 1:05 - 2:10 | neatlogs: incidents we found and fixed  (screen: neatlogs critical-incidents view, then traces)

"Every run is traced in neatlogs, and the incidents view is how we found and fixed problems while building.

Incident one: AI model failures. Here, several Gemini calls show Execution Failed - free-tier quota and overload
errors. The trace showed the run still finished on our rule-based fallback, but we were losing the AI's decisions.
Fix: honor the provider's retry delay and add a model fallback chain - 3.8 Flash, then 3.6, then Flash-Lite.
[show trace with red LLM spans - screenshot 213609 or 213651]

Incident two: a resume bug. We inject outages to test recovery. In this trace, the resumed run goes straight to
scoring - there is no company lookup span, so the failed step was never retried and the case finished without its
key data. [show screenshot 213854] We fixed it, and the new trace shows recover_run followed by the retried lookup,
and no completed request repeated. [show screenshot 213802]

Incident three: a schema error. The trace showed the AI drafting step failing with 400 Invalid Argument. Gemini
rejected one field in our output schema; we simplified the schema and drafting came back.

Incident four: we also saw a gap - one live run's trace never fully arrived during a neatlogs ingest outage, so we
added a delivery probe and re-ran.

Traces also gave us real cost: about a fifth of a cent to two cents per AI write-up, far below what we had assumed."

## 2:10 - 2:30 | Entire  (screen: Entire session timeline)

"The whole build was done with Claude Code, Opus as the lead and Sonnet sub-agents writing modules, and Entire
recorded it. Every commit is linked to the session that produced it - ten checkpoints, 145 file changes - so any line
of code can be traced back to the conversation and decision behind it."

## 2:30 - 2:50 | cfo.ai  (screen: cfo.ai plan, then a case page "Cost vs business plan" panel)

"We built the business plan in cfo.ai: per-audit and annual pricing, conservative, base and growth scenarios, and a
delivery cost of about 95 dollars per audit - and 90 of that is human review, not data or AI. That's why DealScope
focuses on verified, cited findings that are quick to check. Cash is unknown, so runway is left blank rather than
invented.

And the plan is wired into the product: every case shows its real cost against the plan. This live Figma run used
about a dollar of data against 2.60 assumed - under plan."

## 2:50 - 3:00 | Close  (screen: Evidence page, then GitHub repo)

"Everything - traces, checkpoints and the plan - is on the Evidence page and in the public repo. DealScope: sourced
diligence questions, not guesses."

---

## Fact sheet (so every spoken number is true)

| Claim in script | Source |
|---|---|
| Notion live run: risk 32 Watch, under 11 credits (10.82) | `case-0e61a0b82462`, IMPLEMENTATION_LOG 2026-10-12 |
| notion.so resolved to 23 records (if mentioned) | IMPLEMENTATION_LOG live browser test |
| Gemini Execution Failed spans, run still completes | `evidence/neatlogs/screenshots/Screenshot 2026-10-11 213609.png`, `213651.png` |
| Resume bug: no lookup span after recover_run | `Screenshot 2026-10-11 213854.png` (bug) vs `213802.png` (fixed); traces `5366ba56...`/`f748214a...` vs `9e30eca6...`/`3665d832...` |
| 400 INVALID_ARGUMENT from Gemini schema (`maxItems`) | IMPLEMENTATION_LOG 19:40 entry |
| Lost trace during ingest outage | trace `af87b76d...`, `evidence/neatlogs/live-run-20261011T143949Z.json` |
| AI write-up cost $0.0015 - $0.02 | screenshots 213426 and 213710 |
| 10 checkpoints, 145 file changes | `evidence/entire/screenshots/entire-session-timeline.png` |
| $94.65 per audit, three scenarios, runway blank | `evidence/cfo-ai/DealScope-investor-summary.pdf` |
| Figma run: about $1.05 data vs $2.60 plan | `case-879ba1a331fb`, 10.46 confirmed credits x $0.10 plan assumption |

Note: if the neatlogs incidents view groups these differently, keep the four stories and point at whichever incident
entries contain those failing spans.
