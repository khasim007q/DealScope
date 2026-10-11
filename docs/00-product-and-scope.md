# 00 — Product Requirements and Scope

## 1. Product thesis

**DealScope** is an evidence-led outside-in organizational diligence agent for lower-middle-market PE, growth-equity, family-office, and corporate-development teams. It identifies observable organizational signals that could threaten a deal thesis and turns them into prioritized follow-up diligence questions.

### Job to be done

“When evaluating a company, tell me which externally observable organizational signals could undermine our thesis, show exactly what evidence supports them, seek corroborating or contradictory evidence, and tell my team what to validate before signing.”

### Why agentic

The agent has a goal, a bounded action set, persistent case state, and explicit stop conditions. It selects its next action from discovered evidence gaps. A headcount contraction may trigger a department-level check; a concentration of open critical roles may trigger people-history searches; a cluster of identified former technical leaders moving to named competitors may trigger a targeted cross-check. If a call fails, it checkpoints, retries within policy, and resumes. A static sequence that always calls every API is not acceptable.

## 2. Primary users

- PE operating partner / deal team: wants diligence hypotheses and targeted questions.
- Corporate development: wants fast early-warning signals before expensive deep diligence.
- Technical diligence provider: wants leads to validate through interviews and repository/architecture review.

## 3. In-scope MVP

1. Create a case with target domain, 3–5 competitor domains, deal thesis, and time horizon (default last 12 months where the API supports it).
2. Enrich target and selected peers through Crustdata.
3. Search people records for publicly observable technical leadership/job-history signals where supported by the returned schema.
4. Query current job postings for critical technology roles, including descriptions, dates, openings, and reposting flags where available.
5. Normalize evidence with provenance and timestamps.
6. Score five defined signals deterministically.
7. Run a bounded investigative loop that selects follow-up queries based on evidence gaps and current case state.
8. Record actions, retries, failures, budget, model/tool decisions, and signal changes in neatlogs.
9. Persist state in SQLite at every successful tool-result boundary and resume failed cases.
10. Verify report claims against cited evidence IDs, flag unsupported claims, and produce a polished memo in the UI plus Markdown download. PDF export is stretch, not a blocker.
11. Include a fixture mode for deterministic evaluation and a clear visual `SYNTHETIC DEMO DATA` banner.
12. Provide a replayable test showing an injected API failure, bounded retry, checkpoint, and resume.

## 4. Out of scope (do not build)

- Automated investment recommendation, buy/pass instruction, valuation haircut, return forecast, or legal opinion.
- Claiming true employee attrition from sampled public profiles.
- Making accusations of theft, misconduct, deception, or technical failure based solely on job changes or public data.
- Crawling private systems, bypassing access controls, social engineering, or contacting employees.
- Collecting personal emails, phone numbers, personal life data, protected characteristics, or private communications.
- Repo source-code audit, SBOM analysis, cloud permission inspection, VDR/CIM ingestion, eCourts/regulatory data, or private document ingestion in MVP.
- Multi-agent swarm, vector database, custom model training, Kubernetes, cloud deployment dependency, or elaborate RBAC.
- AWS-dependent components. The app must run locally.
- Silent scraping fallback if Crustdata is unavailable.

## 5. Core user flow

1. User enters target domain, peers, and deal thesis.
2. System resolves/validates inputs and shows estimated credit cap.
3. Agent builds a minimum evidence baseline (target + peer enrichment and relevant role/job queries).
4. Agent calculates initial signals and asks: “What uncertainty can materially change this memo?”
5. Agent chooses one targeted follow-up tool call at a time from its allowed tools.
6. New evidence is deduplicated, source-linked, and checked for corroboration/counter-evidence.
7. Stop when evidence coverage is sufficient, the bounded budget/iteration cap is reached, or no available action is likely to change a conclusion.
8. Verifier checks every generated finding. Report explicitly shows limitations and remaining questions.
9. User may resume a failed/incomplete case; existing evidence and budget accounting remain attached.

## 6. Product success metrics

- **Grounded claim rate:** ≥95% of factual claims in the generated memo cite valid evidence IDs; target is 100% for all key findings.
- **Unsupported claim rate:** 0 unsupported material claims after verification; otherwise report generation must fail closed or label the item as an unverified hypothesis.
- **Recovery:** injected retryable failure succeeds after recovery without duplicate enrichment calls when cache/idempotency can safely prevent them.
- **State durability:** all successful tool results remain after process restart.
- **Budget safety:** no new paid call when estimated available budget is insufficient; unknown endpoint costs fail closed until configured.
- **Useful adaptation:** at least one test demonstrates a different next action after changing evidence or a signal gap.
- **Observability:** a neatlogs trace exists for baseline and improved runs, including tools, errors, retries, scores, model decisions, and final outcome.
- **Latency:** target demo case completes in under 4 minutes under normal API performance; no guarantee if provider latency/rate limits vary.
- **Credit discipline:** hard per-case cap and global reserve enforced; no uncapped pagination or broad searches.

## 7. Risk / product language

Use: “observed signal,” “possible exposure,” “hypothesis to validate,” “public-profile coverage,” “evidence confidence,” “not enough data to score.”

Avoid: “fraud detected,” “the team is failing,” “true attrition,” “technical debt proven,” “IP stolen,” “valuation must drop,” or any unqualified causal statement.

## 8. Positioning

“DealScope finds where the organizational story and externally observable signals diverge—then investigates the gap and gives the deal team a sourced validation plan.”

The originality claim is the cross-signal, adaptive investigation and claim-verification loop. Do not claim there are no competing diligence products.
