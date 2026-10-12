# neatlogs: baseline vs improved

Status: measured 2026-10-11. Raw results: `baseline-vs-improved-20261011T144412Z.json` (scenario A) and
`baseline-vs-improved-20261012T102646Z.json` (scenario B, re-run after a budget-pool bug fix). Command:
`python scripts/run_case.py --deterministic-planner --model gemini-3.1-flash-lite eval --scenario <a|b>`.

## Design
- Same synthetic fixture, same deterministic (rule-based) investigation for both variants, so the only difference
  is memo synthesis: **baseline** = loose "summarize the risks" prompt, memo contains only the Gemini draft (the
  verifier still runs; its *draft* metrics show what a verifier-less system would have published); **improved** = strict evidence schema, observation/interpretation separation, mandatory
  alternative explanations, prohibited-claim rules, plus deterministic findings, all gated by the verifier.
- Model: gemini-3.1-flash-lite (free-tier daily quota on gemini-3.8-flash and 3.6-flash was exhausted; see log).
- Metrics are computed by the deterministic verifier on the Gemini draft (pre-publication) and on the published memo.

## Results (n = 1 run per variant per scenario — small sample)

| Scenario | Variant | Trace id | Draft claims | Draft rejected | Draft verified / qualified | Grounded rate | Published claims | Tool calls | Runtime |
|---|---|---|---:|---:|---|---:|---:|---:|---:|
| A | baseline | `28fe5ba00882582eb3d298795274dff9` | 4 | 0 | 2 / 2 | 1.0 | 4 | 7 | 4.5 s |
| A | improved | `4475d391852dad1707054011b73a3d11` | 6 | 0 | 5 / 1 | 1.0 | 15 | 7 | 5.0 s |
| B | baseline | `39ee81cc2045fe5f160e428bb24943cd` | 3 | 0 | 1 / 2 | 1.0 | 3 | 8 | 16.1 s |
| B | improved | `e63bac7e90a7d4de175c300f139a82a2` | 6 | 0 | 6 / 0 | 1.0 | 17 | 8 | 15.2 s |

Simulated Crustdata accounting for each scenario-A run: 20.25 credits (synthetic pool; no real credits spent).

## Honest reading
- **No reduction in unsupported claims was observed**: the baseline prompt produced 0 rejected claims on both
  fixtures, because the model only sees the evidence index (with IDs) in both variants.
- Observed differences: the improved variant produced more claims that pass verification outright (5 vs 2 on A;
  5 vs 2 on B), a lower share of qualified (single-source / missing alternative explanation) claims on A, explicit
  diligence questions, and a fuller memo once deterministic findings are merged.
- The verifier's rejection behaviour is demonstrated separately by unit tests and by
  `test_unsupported_llm_claims_are_rejected_from_memo` (fabricated ID, "40% left", IP-leak and valuation claims all
  rejected).
- Scenario B was re-run on 2026-10-12: the first B run (`superseded/baseline-vs-improved-20261011T144435Z.json`)
  was invalid because simulated (synthetic) credit spend from earlier demo runs had been counted against the live
  account-wide cap, so some tool calls were blocked (GLOBAL_SPENDABLE_BUDGET_EXCEEDED). Fixed: the global cap now
  applies to the live pool only; synthetic runs keep their per-case cap.
- Superseded attempt (`superseded/`): first eval run on gemini-3.6-flash hit 503/429 errors so neither variant got
  an LLM draft; it is kept for transparency, not used as a result.

Screenshots: `evidence/neatlogs/screenshots/Screenshot 2026-10-11 213426.png` (synthesis span, 2,175 tokens, $0.0015), `evidence/neatlogs/screenshots/Screenshot 2026-10-11 213450.png`, `evidence/neatlogs/screenshots/Screenshot 2026-10-11 213516.png`, `evidence/neatlogs/screenshots/Screenshot 2026-10-11 213542.png`.
