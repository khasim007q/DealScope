# DealScope — Specification Pack

**Product:** DealScope — Evidence-Led Outside-In Diligence Agent  
**Purpose:** Hackathon MVP for neatHack (10–12 October 2026)  
**Primary data source:** Crustdata APIs (5,000 participant credits; do not assume AWS credits)  
**Required partner products:** neatlogs, Entire, cfo.ai

## What we are building

DealScope investigates a target company's externally observable organizational execution risk for a private-equity / M&A deal thesis. It plans a bounded investigation, calls tools, stores intermediate state, follows evidence gaps, tests alternative explanations, recovers from selected failures, verifies report claims against source records, and generates an investment-committee-style memo.

It is **not** a generic research chatbot, a dashboard-only wrapper, a valuation engine, or a claim to measure true employee attrition from incomplete public profiles.

## Read/build order

1. `docs/00-product-and-scope.md`
2. `docs/01-hld.md`
3. `docs/02-lld.md`
4. `docs/03-functional-spec.md`
5. `docs/04-signal-catalog.md`
6. `docs/05-technical-requirements.md`
7. `docs/06-crustdata-credit-budget.md`
8. `docs/07-hackathon-partner-requirements.md`
9. `docs/08-cfoai-business-plan.md`
10. `docs/09-evaluation-demo-submission.md`
11. `CLAUDE_CODE_MASTER_PROMPT.md`

## Key product decisions (do not weaken these)

- Score only five defined signals, with explicit `scorable`, `not_scored`, and `low_coverage` states.
- Keep **risk** and **evidence confidence** separate. An unavailable signal is not a zero-risk signal.
- Every factual claim in the final report must point to one or more evidence IDs and include observation dates/source metadata.
- The agent must choose follow-up actions based on results, not execute a fixed chain regardless of findings.
- Persist state after every tool call. A failed run must resume from a durable checkpoint rather than restart and blindly spend credits again.
- Use Crustdata only for professional/company data needed for diligence. Do not request personal emails, phone numbers, or irrelevant personal details.
- Never infer actual attrition rate, IP theft, technical debt, employee performance, or valuation haircut from public-profile signals alone.
- Never claim a live Crustdata result when running fixture/demo mode.
- neatlogs, Entire, and cfo.ai are mandatory hackathon requirements. Treat proof of actual use as a deliverable, not a README claim.
- AWS credits are optional. Core app must run without AWS.

## MVP acceptance in one sentence

Given one target domain, three to five competitors, and an investment thesis, DealScope produces a source-linked diligence memo while making at least one evidence-driven follow-up decision, persisting recoverable state, and demonstrating a recoverable tool failure in neatlogs traces.

## Project layout expected from Claude Code

```text
app.py                         # Streamlit shell
src/dealscope/
  config.py                    # env settings and feature flags
  domain/                      # Pydantic domain models
  providers/crustdata.py       # API client + field normalization
  providers/llm.py             # configured model adapter
  agent/planner.py             # structured next-action selection
  agent/orchestrator.py        # bounded investigate/recover/stop loop
  agent/tools.py               # allowlisted tool functions
  analysis/signals.py          # deterministic scorecards
  analysis/peer_benchmark.py   # robust peer comparisons
  verification/claims.py       # citation/claim validation
  persistence/repository.py    # SQLite case/checkpoint/evidence store
  reports/memo.py              # Markdown/HTML memo builder
  observability/neatlogs.py    # partner instrumentation
scripts/
tests/
fixtures/
reports/
```

Claude Code may adjust structure if it explains why in the implementation log. Do not create a microservice mesh.

## Source of truth

This pack was designed against the published neatHack page and publicly accessible Crustdata/neatlogs/Entire documentation. API schemas and per-endpoint prices can change. Before implementing an endpoint, inspect its current official docs and validate the response shape using a small, metered request. Do not guess an undocumented job-listing price.

- Hackathon: https://neatlogs.com/hackathon
- Crustdata company API: https://crustdata.com/company-data-api
- Crustdata people API: https://crustdata.com/people-api
- Crustdata jobs API: https://crustdata.com/apis/job-listing
- Crustdata docs: https://docs.crustdata.com/
- neatlogs Python SDK: https://docs.neatlogs.com/sdk/python
- neatlogs evals: https://docs.neatlogs.com/docs/features/evals
- Entire: https://entire.io/
- cfo.ai neatHack page: https://cfo.ai/neathacks

## Hackathon timing

The published schedule says submissions close Monday, 12 October 2026, 7:00–11:55 PM IST (the page notes the final cutoff may be announced on Discord). Confirm the final cutoff in the official Discord before submission. All product code must be written during the hackathon window; this specification is a plan, not prebuilt product code.
