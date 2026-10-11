# neatlogs: successful live run

Status: captured 2026-10-11. Values below come from `live-run-*.json` in this folder and the SQLite run log.
Screenshots of the neatlogs dashboard still need to be added by the owner.

## Primary proof run — Airtable (fresh Crustdata calls)

| Field | Value |
|---|---|
| Date | 2026-10-11 ~20:09 IST |
| Mode | LIVE CRUSTDATA |
| Case id | `case-289f654e60f5` |
| Target / peers | airtable.com / smartsheet.com, monday.com, clickup.com |
| Trace id (investigation) | `d3a8f383b6cf980bfc51fcdc436478cd` |
| Trace id (report regeneration with Gemini drafting, 0 new tool calls) | `81dd213dbdbc546acd906ecf44f66478` |
| Configuration | gemini-3.6-flash (planner + drafting), improved prompt, case cap 40 credits, max 8 turns / 12 tool calls |
| Planner sequence | search_people (Gemini) -> search_people (Gemini) -> search_jobs (Gemini) -> stop (no candidates left) |
| Tool calls / planner turns | 7 / 4 |
| Crustdata credits | 12.21 actual (sum of `X-Credits-Used`), 0 unknown-outcome |
| Outcome | complete; risk 42.7 (Watch, heuristic); coverage 92.5%; evidence confidence 90 |
| Verification | memo: 14 claims, 13 verified + 1 qualified, 0 rejected, grounded-claim rate 1.0; Gemini draft: 6 claims, 0 rejected |
| Notes | First investigation run's drafting hit Gemini's per-minute free-tier limit (429) and fell back to deterministic findings; regenerated after adding advised-delay retry. |
| Screenshot path | TODO (`evidence/neatlogs/screenshots/...`) |

## Earlier live run — Retool (trace likely incomplete)

| Field | Value |
|---|---|
| Case id | `case-8ddc70b2b4de` (retool.com vs appsmith.com, tooljet.com, budibase.com) |
| Trace id | `af87b76d2681d7727d184d8aec363d39` — **not visible in the dashboard**; neatlogs ingest returned 503 during this run |
| Outcome | complete; 9.18 credits actual; first planner turn fell back to deterministic after two Gemini 504s |
