# DealScope — Business Model Assumptions (for cfo.ai)

Prepared 11 October 2026 for the neatHack business plan. **Every figure below is an assumption or an estimate unless
marked ACTUAL. DealScope has no customers, revenue or signed pilots. Do not treat any scenario as traction.**

## 1. Product and customer

- **Product:** DealScope is a B2B agent for outside-in organizational diligence in PE/M&A. It investigates public
  company, people-history and job-posting signals for a target company. It then produces a source-linked memo with
  verified findings and diligence questions. It is an early screen, not technical diligence or valuation advice.
- **Buyers (hypothesis):** lower-middle-market PE and growth-equity deal teams, family offices, independent sponsors,
  corporate development teams, and technical-diligence providers.
- **Unit of work:** one "audit" = one target company + 2–5 peer companies + a deal thesis → one verified memo.

## 2. Pricing scenarios to compare (assumptions)

| Model | Price | Notes |
|---|---|---|
| Per audit — low | $750 | Price-sensitivity floor |
| Per audit — base | $1,500 | Primary hypothesis |
| Per audit — high | $3,000 | Premium / rush |
| Annual deal-team plan | $24,000 / year | Includes 24 standard audits/year (2/month); extra audits at $1,000 each (editable) |
| Hybrid | $6,000 / year workspace + $1,000 per audit | Workspace fee is an editable assumption |

No "unlimited audits" plan until data-cost variance and support load are measured.

## 3. Volume scenarios (assumptions, not traction)

| Scenario | Paying customers | Audits / customer / month | Price assumption | Other |
|---|---:|---:|---|---|
| Conservative | 2 | 2 | $750 per audit | Higher data/model cost (+50%); first revenue delayed 2 months |
| Base | 5 | 3 | $1,500 per audit | Midpoint costs |
| Growth | 15 | 4 | Annual plan $24,000 + overage | Customers ramp linearly over 12 months |

Sensitivity to run: audits per customer per month 2 / 3 / 4; price discounts 0% / 20% / 40%; data cost ×1 / ×2 / ×3;
sales-cycle delay 0 / 2 / 4 months; annual-plan utilization 50% / 75% / 100%.

## 4. Variable cost per audit

| Cost item | Assumption | Basis |
|---|---|---|
| Crustdata data credits | **~26 credits per audit (estimate)**, hard cap 40 credits | 4 company enrichments x 2 = 8; 2–3 people searches x 25 results x ~0.23 = 11.5–17.3; jobs search 25 x 0.03 = 0.75. Prices from Crustdata's published docs (checked 11 Oct 2026); actual usage to be confirmed from our first live runs. |
| Crustdata $ per credit | **INPUT — leave editable** | Not published in Crustdata's docs; depends on plan/contract. Sensitivity: $0.05 / $0.10 / $0.25 per credit. |
| LLM inference (Gemini Flash) | **~$0.05 per audit (estimate)** | About 6 model calls/audit, roughly 40k input + 5k output tokens. Replace with measured cost from neatlogs traces. Model ×5 for a stronger escalation model. |
| Analyst review / QA time | **1.5 hours per audit at $60/hour = $90** (editable) | A human reviews every memo before delivery. "Autonomous" does not mean no review. |
| Report delivery / misc. tooling | $2 per audit | Storage, export, email. |
| Payment processing | 3% of revenue | Card/ACH fees. |

## 5. Fixed monthly costs (assumptions, editable)

| Item | Monthly |
|---|---:|
| Hosting, database, monitoring (incl. observability) | $150 |
| Software/tools (CRM, docs, design) | $100 |
| Data platform minimum / subscription | $0 now (pay-as-you-go credits); add a placeholder line |
| Compliance, security review, insurance (future) | $500 from month 6 |
| Founder/analyst salaries | **INPUT** — leave $0 or enter actual planned draw |
| Sales & marketing | $500 |

## 6. Cash and runway

- **Available cash: INPUT — not provided. Do not invent a number.** Runway = available cash / average monthly net burn,
  computed only when burn is positive and cash is entered.
- No AWS or cloud credits are assumed.

## 7. Required outputs

12-month monthly projection per scenario with revenue, variable costs, gross profit, gross margin, contribution margin,
fixed costs, net burn and runway. Include per-audit unit economics (revenue per audit, variable cost per audit, gross
profit per audit). Add a one-page investor/business summary. Keep formulas transparent.

## 8. Risks to reflect

- Public-profile coverage varies and is not a full employee census. Findings need human validation.
- Buyers may expect private repo, architecture or data-room analysis that the MVP does not offer.
- API licensing, permitted use and field-level data costs need confirmation.
- Fund deal flow is lumpy, so audit frequency per customer is uncertain. Annual-plan pricing must reflect real use.
- Consulting/diligence providers may adopt the tool rather than be displaced.

## 9. Facts (ACTUAL)

- Customers, revenue, pilots: **none** (pre-revenue hackathon MVP).
- Crustdata account balance available to the team: **200 credits** (hackathon allocation as received).
- Runtime LLM: Gemini Flash. Observability: neatlogs. Development checkpoints: Entire.
