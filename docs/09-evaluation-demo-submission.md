# 09 — Evaluation, Demo, and Submission Evidence

## 1. Evaluation rubric

Every evaluation fixture should score the agent on:

- Goal completion: did it produce a memo or an honest partial memo?
- Adaptivity: did next action reflect current evidence gaps?
- Tool correctness: did it select appropriate allowed actions and validate parameters?
- Evidence grounding: all material claims cite existing correct evidence IDs.
- Counter-evidence: report provides at least one plausible alternative explanation where a material risk is alleged.
- Calibration: unknown/missing coverage is not interpreted as reassuring evidence.
- Resilience: failure does not erase state or cause uncontrolled retries/spend.
- Budget discipline: no call on unknown price/insufficient budget.
- Observability: trace includes action, tool, retry, result, score change and finish reason.

## 2. Required test cases

### T01 — Baseline live run
Given target + 3 peers + a short deal thesis, perform one metered company enrichment request per domain, then bounded targeted tool calls. Verify live mode, source timestamps, evidence IDs, and report limitations.

### T02 — Adaptive branch
Fixture A: engineering/R&D trajectory is lower than overall headcount and critical roles are open. Expected next action: investigate critical role continuity or postings/role coverage.  
Fixture B: no trajectory concern but senior role histories are incomplete. Expected next action differs from Fixture A. Assert action differs and planner reason cites gap.

### T03 — Missing data
Remove department growth and role employment dates. Expected: S1/S2 become not-scored/low-coverage, risk composite reports insufficient evidence if <60% weight assessable. It must not assign zero.

### T04 — Unsupported claim rejection
Candidate claim: “40% of the engineering team left.” Evidence contains four returned profiles with two past-employment records, without total roster denominator. Expected: reject/qualify claim; allowed rewrite: “Two observed profiles have target-company employment intervals ending in the period; profile coverage does not establish company-wide attrition.”

### T05 — False causal claim
Candidate claim: “The target leaked IP because an engineer joined a competitor.” Expected: verifier rejects it; report may state only the observed job move and ask a diligence question.

### T06 — Retryable failure
Mock initial 503 or 429, then success. Expected: max bounded retries, state remains, usage ledger shows reservation/settlement, trace shows retry. Ensure no infinite retries.

### T07 — Permanent failure
Mock 401. Expected: no retry; show actionable credential error; do not silently switch to fixtures.

### T08 — Unknown job pricing
Do not configure job price. Expected: `search_jobs` blocked before HTTP call with reason `UNKNOWN_PRICE_FAIL_CLOSED`.

### T09 — Budget exhaustion
Set per-case budget to a small value. Expected: the next paid action is rejected before request; final partial memo lists remaining gaps.

### T10 — Resume after restart
Persist one result, stop process, restart, resume case. Expected: previous evidence available and completed request not repeated.

### T11 — Verifier counter-evidence
Finding has evidence supporting possible continuity risk and another item offering plausible restructuring explanation. Expected: report labels inference carefully and includes both.

### T12 — Neatlogs improvement comparison
Run the same fixture against the baseline and improved prompt/verifier. Capture actual grounded-claim rate, unsupported claim count, tool call count, latency, and cost estimate. Do not fabricate or cherry-pick metrics; retain both trace IDs.

## 3. Demo narrative (≤3 minutes)

0:00–0:20 — State the problem and show case inputs (target, peers, thesis).  
0:20–0:55 — Start a live case and show the agent’s initial plan, Crustdata calls, and first signal computation.  
0:55–1:25 — Show evidence changing the next investigation action; open an evidence card and explain why it was selected.  
1:25–1:50 — Trigger the scripted failure test (separate run if safer), show bounded retry/checkpoint/resume in neatlogs.  
1:50–2:15 — Show verified memo, coverage/confidence distinction, alternative explanations, and diligence questions.  
2:15–2:35 — Show Entire commit checkpoint and explain what it records.  
2:35–2:55 — Show cfo.ai plan and pricing/cost/runway scenarios.  
2:55–3:00 — Close with repository / try-it path.

Keep all three partner tools visible, not just mentioned in voiceover.

## 4. Required repo evidence structure

```text
evidence/
  neatlogs/
    successful-run.md           # trace URL/ID, configuration, outcome
    failure-recovery.md         # failed action -> retry/checkpoint -> outcome
    baseline-vs-improved.md     # actual metrics + trace IDs
    screenshots/
  entire/
    README.md                   # CLI version, commands, checkpoint links
    screenshots/
  cfo-ai/
    assumptions.md
    plan.png or exported-plan.pdf
  build-in-public/
    post-url.txt
SUBMISSION_EVIDENCE.md
```

Do not commit API keys, private data, real profile dumps, or screenshots that reveal secrets.

## 5. Submission checklist

- [ ] Public repository with commits dated during the hackathon.
- [ ] README includes install/run instructions and a short architecture section.
- [ ] Tests pass in fixture mode.
- [ ] At least one real Crustdata call is evidenced; usage checked in account dashboard.
- [ ] 5,000 credit policy is implemented; job endpoint cost configured only after verification.
- [ ] neatlogs trace link/screenshot for successful run.
- [ ] neatlogs trace link/screenshot for failure recovery.
- [ ] Baseline vs improved neatlogs experiment with actual measured numbers.
- [ ] Entire checkpoint or entire-graph evidence.
- [ ] cfo.ai business plan evidence, including pricing/costs/revenue/runway.
- [ ] Build-in-public post tagged `#neatHack`; real public link added.
- [ ] Demo video is ≤3 minutes and explicitly shows all three partner products.
- [ ] No unsupported claims in demo/report.
- [ ] Submission posted through required official X quote-post flow before confirmed cutoff.
- [ ] Verify official Discord for final deadline/change notes.

## 6. Build-in-public draft

> Building DealScope for #neatHack: an evidence-led M&A diligence agent that doesn't stop at summarizing company data. It identifies organizational signals, chooses the next investigation based on evidence gaps, checkpoints/retries failed data calls, and verifies every finding before it reaches the memo. Built with Crustdata + neatlogs + Entire; business model tested in cfo.ai. More soon: [repo/demo link]

Only publish claims that are true at the time of posting; replace placeholders with real links.
