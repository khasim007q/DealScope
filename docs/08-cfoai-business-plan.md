# 08 — cfo.ai Business Plan Brief

## Product
DealScope is a source-linked outside-in organizational diligence agent for PE/growth equity and corporate development. It investigates public company/people/job signals to identify organizational execution risks relevant to a stated deal thesis and produces a verification-ready diligence memo. It is an early screen and question-generation product, not a replacement for technical diligence or an automated valuation decision.

## Customer / market hypothesis
- Primary: lower-middle-market PE and growth-equity deal teams, family offices, independent sponsors, and corporate development teams.
- User: deal partner, operating partner, investment associate, technical diligence provider.
- Pain hypothesis: initial diligence often requires manual research across company, leadership, job, and people-history sources. Deal teams need a consistent source-linked first pass and targeted questions before spending on deeper diligence.
- Validate willingness to pay; do not represent the market size or customer demand as proven.

## Initial pricing hypotheses to model
Use cfo.ai to compare three structures:
1. **Per audit:** $1,500 per target-company diligence screen (initial hypothesis; stress-test $750 / $1,500 / $3,000).
2. **Deal-team annual:** $24,000/year includes up to a defined number of standard screens; excess usage priced separately.
3. **Hybrid:** $1,000–$1,500 per audit plus an annual team workspace/license.

Don't use “unlimited audits” until API cost variance and support load are understood. Pricing differs from the earlier $3,000 / $36,000 brainstorm and is intentionally left for scenario comparison, not treated as validated.

## Cost model requirements
Separate fixed and variable costs. Model at least:
- Crustdata: count real company enrichments, returned people profiles, person enrichments, and job API usage at confirmed account pricing. Use usage ledger from demo, not theoretical $0.50 per run.
- LLM inference: actual token/model/provider costs from neatlogs or provider dashboard.
- Storage/hosting: local demo costs effectively low; production deployment is a future assumption.
- Engineering/support: include founder/analyst review time. “Autonomous” does not mean no human support or verification.
- Compliance/security/procurement costs for a commercial product: explicit future assumption.
- Gross margin by case and blended gross margin by customer tier.

## Scenarios cfo.ai must produce
1. **Conservative:** 2 customers, 2 audits per customer/month, lower price, higher data/model cost, 2-month sales cycle slippage.
2. **Base:** 5 customers, 3 audits per customer/month, midpoint price/cost assumptions.
3. **Growth:** 15 customers, 4 audits per customer/month, with a defined annual plan.

These are modeling inputs, not claims of customers already signed. Let cfo.ai make the arithmetic coherent and change assumptions if needed. Add revenue, gross profit, gross margin, contribution margin, fixed monthly costs, burn, and runway (cash input is editable). Do not invent available cash: enter the actual amount or leave runway as a formula/input.

## Unit economics formula
- Revenue per case = recognized audit fee (or allocated subscription revenue per case).
- Variable cost/case = Crustdata + model inference + report delivery/variable tooling + human review time cost.
- Gross profit/case = revenue/case − variable cost/case.
- Gross margin = gross profit / revenue, when revenue > 0.
- Monthly contribution = monthly revenue − variable costs − fixed operating costs.
- Runway = available cash / average monthly net burn, only where burn is positive and cash is known.

## Business risks to represent
- Public-profile coverage varies and is not a complete employee census.
- Buyer may expect private repo, architecture, or VDR analysis that the MVP does not offer.
- API licensing/permitted use and field-level cost need confirmation.
- Data inaccuracies can damage trust; source citations and human validation are essential.
- Sales frequency per fund is low and deal-dependent; annual price must reflect real utilization.
- Consulting providers may add software to their existing workflows rather than be displaced entirely.

## Prompt to paste into cfo.ai

> Create an editable business plan and financial model for DealScope, an early-stage B2B agent for source-linked outside-in organizational diligence in PE/M&A. Use the conservative/base/growth assumptions in this document as hypotheses, not actual traction. Compare per-audit pricing at $750/$1,500/$3,000, annual deal-team pricing at $24,000, and hybrid pricing. Include revenue, Crustdata cost per case (leave as editable and use our actual usage if supplied), LLM inference, analyst review/support time, other variable and fixed costs, gross margin, contribution margin, monthly burn and runway. Add sensitivity analysis for 2/3/4 audits per customer/month, variable data costs, price discounting, sales-cycle delay, and annual contract utilization. Explicitly flag assumptions requiring validation. Do not assume AWS credits. Create a one-page investor/business summary and a 12-month monthly projection. Make formulas transparent and do not invent real customer traction or available cash.

## Evidence to capture

- `evidence/cfo-ai/plan.png` screenshot(s) or exported file.
- `evidence/cfo-ai/assumptions.md` listing the actual values entered and which are assumptions.
- Mention that this plan was produced in cfo.ai in the submission materials.
