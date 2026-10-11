# 03 — Functional Specification

## FR-01 Case creation

**Inputs:** target domain, 3–5 competitor domains, deal thesis, lookback period (default 12 months), case budget (default 300 credits), live/fixture mode.  
**Behavior:** validate inputs, resolve company identity where supported, show confirmation screen and estimated budget before live calls.  
**Acceptance:** invalid domains, duplicates, target repeated as competitor, missing thesis, or budget over global policy are rejected with actionable messages.

## FR-02 Evidence acquisition

**Behavior:** obtain an initial company snapshot for target and peers; identify fields actually returned; query only people/job data relevant to the current uncertainty. Deduplicate by provider record/source identity and normalized content.  
**Acceptance:** every evidence record has source endpoint, retrieval timestamp, field coverage, synthetic/live flag, and credit ledger relationship. No arbitrary broad search occurs.

## FR-03 Adaptive investigation

**Behavior:** planner sees summary of evidence, signal gaps, open questions, remaining budget, and allowable actions. It proposes one action at a time with a reason and expected information gain.  
**Acceptance:** integration test proves input evidence changes the next selected action. Max 8 planner turns and 12 tool invocations per case. An empty or low-quality result causes the agent to revise/stop, not fabricate.

## FR-04 Signal computation

**Behavior:** use the signal catalog's deterministic thresholds and evidence requirements. Store score version, raw calculation, rule reason codes, sources, and limitations.  
**Acceptance:** same normalized evidence + same scoring version produces same output. Missing evidence is `not_scored` or `low_coverage`, never silently zero.

## FR-05 Cross-signal investigation

**Behavior:** group mutually reinforcing signals into an investigation thread; state which sources independently corroborate; attach alternate explanations and counter-evidence.  
**Acceptance:** report differentiates an observed fact from interpretation and a question requiring internal diligence.

## FR-06 Claim verification

**Behavior:** before rendering, check every material factual claim has valid evidence IDs; source records match the claimed entity, date and direction; unsupported numbers and causal claims are rejected.  
**Acceptance:** tests include fabricated evidence ID, wrong company citation, overstated attrition rate, and ungrounded valuation haircut; all must be rejected or qualified.

## FR-07 Persistent state and resume

**Behavior:** save checkpoint before and after external calls and every state transition. On restart, load the latest checkpoint and reuse completed calls from cache.  
**Acceptance:** kill/restart test resumes without losing previous evidence and without repeating already completed metered calls.

## FR-08 Failure recovery

**Behavior:** bounded retry for retryable errors; no retries for invalid credentials/schema; use next useful tool if a nonessential source fails; persist unknown-cost calls as unresolved.  
**Acceptance:** injected 429/503 demonstrates retry and success or bounded stop; a 401 fails clearly; no infinite retries.

## FR-09 Credit governance

**Behavior:** show starting credits (configured), reserved credits, estimated consumed credits, actual consumed credits if supplied by response/account, remaining usable budget, and uncertainty. Enforce per-case ceiling and global reserve before every paid call.  
**Acceptance:** no job query can run without configured conservative price. No over-budget action reaches provider adapter.

## FR-10 Report

**Required sections:**
1. Cover / case context / as-of date / mode indicator.
2. Executive assessment: risk score only if minimum signal coverage is met; separate evidence confidence and coverage.
3. Top findings with severity, observation, dates, evidence links/IDs, counter-evidence, and limitation.
4. Signal scorecard with weights, scores, scorable/not-scored status, and rationale.
5. Organizational evidence timeline.
6. Competitor/alumni movement matrix only when evidence is found.
7. Alternative explanations.
8. Priority diligence questions for management / technical diligence team.
9. Data coverage, API limitations, peer cohort and known blind spots.
10. Method version and no-investment-advice disclaimer.

**Acceptance:** the memo cannot contain an unverified material factual claim. Fixture report carries a permanent “SYNTHETIC DEMO DATA — NOT A REAL COMPANY ASSESSMENT” mark.

## FR-11 Observability

**Behavior:** each run is a neatlogs root trace with child spans for planning, tools, API calls, scoring, verifier, reporting, retries and recovery.  
**Acceptance:** a trace is visible in the neatlogs project for one real run; a failing run and improved run can be compared; trace metadata excludes secrets and unnecessary personal data.

## FR-12 Hackathon evidence

**Behavior:** repository includes links/screenshots or exports demonstrating neatlogs, Entire, cfo.ai, improvement between runs, failure recovery, and a build-in-public post.  
**Acceptance:** checklist is complete before final submission; do not claim a partner was used if proof is absent.

## FR-13 Demo/fixture mode

**Behavior:** bundled synthetic dataset allows evaluator tests without consuming credits or exposing real-company allegations. Clearly separate live and fixture mode.  
**Acceptance:** no fixture data is labeled as Crustdata output; test can run without API credentials.

## UI minimum requirements

- Left/landing panel: create case, provider status and mode.
- Running panel: stage, current investigation question, action/reason, tool timeline, retry count, credit meter.
- Results panel: scorecard + confidence + coverage, top evidence cards, claim citations, unanswered questions.
- Case history panel: status and Resume action.
- Export: `.md` report plus `.json` evidence/scorecard bundle; PDF is stretch.
