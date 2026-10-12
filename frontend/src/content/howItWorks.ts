import type { HowItWorksContent } from "./types";

// Plain-language "How it works" content. Every figure is taken from files in this repository
// (IMPLEMENTATION_LOG.md, SUBMISSION_EVIDENCE.md, evidence/). The long version is docs/walkthrough.md.

export const HOW_IT_WORKS: HowItWorksContent = {
  intro:
    "DealScope is an early-screen tool for deal teams. You give it a target company, two to five peers and your deal thesis. It looks at public company, people-history and job-posting data, shows the evidence behind each signal, and gives you a sourced list of questions to validate before you sign. It is not an investment recommendation, a valuation or a legal opinion.",
  sections: [
    {
      id: "what-it-does",
      title: "What DealScope does",
      summary:
        "It turns public organizational signals into questions for your deal team, with the evidence attached.",
      paragraphs: [
        "You enter a target domain, two to five peer domains, a deal thesis and a lookback window. DealScope builds a baseline from company data, scores five signals, decides what extra data is worth buying, and writes a memo.",
        "Every finding in the memo cites evidence records, and every finding has passed an automatic checker before it is shown. The memo ends with open questions for management rather than a verdict.",
        "DealScope does not calculate employee attrition, does not suggest causes or misconduct from job moves, and never gives valuation or buy/pass advice. Public profiles are a sample, not a full headcount, so missing data is reported as not enough data and never as reassurance.",
      ],
      bullets: [
        "For: private-equity, growth-equity and corporate-development teams, and technical-diligence providers.",
        "Output: a memo, a JSON evidence bundle, and a list of questions to validate.",
        "Demo runs on synthetic fixtures carry a SYNTHETIC DEMO DATA banner.",
        "This web app is a React interface on a FastAPI server; progress is saved in a local SQLite database, so a restart loses nothing and a partial case can be resumed.",
      ],
    },
    {
      id: "one-case",
      title: "One case, step by step",
      summary:
        "The agent works in a short, bounded loop and saves its progress after every paid step.",
      paragraphs: [
        "1. Identity check. Before spending anything, DealScope asks Crustdata (for free) whether each domain points to exactly one company. If a domain is ambiguous, the run is refused and the candidates are shown.",
        "2. Baseline. The target and each peer are looked up once for headcount, department growth and hiring (2 credits per company).",
        "3. Score. Five signals are scored by fixed rules. Anything that cannot be scored is marked as not scored.",
        "4. Next action. The code lists the follow-up searches that are allowed, affordable and not yet done. An AI planner (Gemini) picks one and explains why. If the AI is unavailable or gives an invalid answer, a rule-based fallback picks instead.",
        "5. Run and save. The chosen search passes through the credit budget, runs, and its result is saved. The signals are rescored. This repeats until nothing more would change a conclusion, or a limit is reached (by default 8 planner turns, 12 provider calls, 240 seconds).",
        "6. Write and verify. The AI drafts findings with citations, a deterministic checker accepts or rejects each one, and only accepted findings reach the memo.",
      ],
    },
    {
      id: "signals",
      title: "The five signals and three separate numbers",
      summary:
        "Risk, coverage and confidence are reported separately so that thin data never looks like good news.",
      paragraphs: [
        "Each signal is a prompt for a diligence question, not a prediction. The weights and thresholds are heuristics and are labelled as unvalidated.",
        "Risk is the weighted average of the signals that could be scored, shown as Low signal (0-24), Watch (25-49), Elevated (50-69) or High signal (70+). Coverage is the share of total signal weight that could be assessed. Below 60% coverage the overall risk number is withheld and the memo says INSUFFICIENT EVIDENCE. Evidence confidence reflects field completeness, recency, corroboration, peer comparability and identity quality. Missing data lowers coverage and confidence; it never lowers risk.",
      ],
      table: {
        headers: ["Signal", "Weight", "Plain-language question"],
        rows: [
          [
            "S1 Technical trajectory",
            "30%",
            "Is engineering headcount growing more slowly than the whole company or than peers?",
          ],
          [
            "S2 Role continuity",
            "25%",
            "Do the profiles we can see show several senior technical people whose time at the target ended in the window?",
          ],
          [
            "S3 Capability coverage",
            "15%",
            "For the capabilities the thesis depends on, can we still see current technical leaders? No profile found means no data, not no capability.",
          ],
          [
            "S4 Hiring pressure",
            "20%",
            "Are critical technical roles open in clusters, reposted or long-open? No postings found is treated as unavailable.",
          ],
          [
            "S5 Competitor movement",
            "10%",
            "Did identified senior technical alumni join the competitors you listed? Corroborating evidence only.",
          ],
        ],
      },
    },
    {
      id: "adaptive",
      title: "The agent changes course based on evidence",
      summary:
        "Two synthetic scenarios show a different first move depending on what the baseline reveals.",
      paragraphs: [
        "In scenario A the target's engineering headcount shrinks (-4% over 6 months, -2% over 12) while the company grows (+11% and +18%). The first follow-up is a search for open critical technical roles, because engineering trailing the company is the thing to test.",
        "In scenario B engineering grows faster than the company (+12% and +20% against +10% and +17%). There is nothing to test there, so the first follow-up is a search for senior technical people who left. Because those profiles mostly lack dates, B later adds a broader search that A never needs. In the recorded run B finished with 92.5% coverage and a Low signal overall score of 14.2, while A scored 54.5 (Elevated) with 87.5% coverage.",
        "A test in the repository (test_t02_adaptive_branch_differs_between_scenarios) asserts that the first action and its stated reason differ between the two scenarios.",
      ],
    },
    {
      id: "live-results",
      title: "What the live tests showed",
      summary:
        "Real data, real credits, and a few real failures that made the product safer.",
      paragraphs: [
        "These are small demonstrations on a handful of public companies. They show that the system works end to end; they do not validate the signals as predictors of anything.",
        "The first Notion attempt used notion.so, an ambiguous domain in Crustdata, and spent credits without returning usable evidence. DealScope showed INSUFFICIENT EVIDENCE honestly, and we added the free identity check so it cannot happen again. Separately, some peers showed engineering growth of +304% to +500%, which is a data discontinuity, so implausible values are now dropped before scoring and listed in the memo as data-quality flags.",
      ],
      table: {
        headers: ["Live case", "Crustdata credits (actual)", "Result"],
        rows: [
          ["Retool vs three peers", "9.18", "Risk 22.2, coverage 92.5%, confidence 85.9"],
          [
            "Airtable vs three peers",
            "12.21",
            "Risk 42.7 (Watch), coverage 92.5%, confidence 90; memo of 14 claims, 13 verified and 1 qualified, none rejected",
          ],
          [
            "Notion (notion.com) vs three peers",
            "4.82",
            "Risk 32 (Watch), coverage 92%, confidence 87, 36 evidence records",
          ],
        ],
      },
      bullets: [
        "Total recorded Crustdata spend: 36.21 of 200 credits.",
        "The Notion figure is lower only because the three peers came from a same-day cache (0 credits); it is not a typical full-audit cost.",
      ],
    },
    {
      id: "safety",
      title: "Safety by design, and what it costs",
      summary:
        "The AI proposes; deterministic code disposes. Each safeguard has a tradeoff.",
      paragraphs: [
        "The AI planner can only choose among actions that code has already checked, so it cannot invent a search or overspend. The scoring and the claim checker use no AI, so results are reproducible.",
      ],
      table: {
        headers: ["Decision", "Why", "Tradeoff"],
        rows: [
          [
            "AI picks from a fixed list",
            "Keeps model output away from paid calls",
            "Less flexible; it cannot invent new queries",
          ],
          [
            "Rule-based fallback",
            "Runs finish even when Gemini fails",
            "Plainer wording when the fallback is used",
          ],
          [
            "200-credit account: 40 reserved, 40 per case, 25 results per people search",
            "The real balance is 200, and a person search costs about 0.23 credits per result",
            "Fewer profiles per case, so lower coverage on large companies",
          ],
          [
            "Free identity check first",
            "A paid lookup on an ambiguous domain wasted credits",
            "Crowded domains are refused until you pick a clearer one",
          ],
          [
            "Saved progress and resume",
            "A failed run continues without repeating paid calls",
            "Cached data can be stale; resume retries a failed step once",
          ],
          [
            "No attrition rates, causes or valuation",
            "Public profiles are a sample, not a census",
            "No single headline number; output is questions and signals",
          ],
        ],
      },
    },
    {
      id: "neatlogs",
      title: "neatlogs: seeing what the agent did",
      summary:
        "Each run is traced step by step, which found a real bug and proved the fallback behaviour.",
      paragraphs: [
        "neatlogs records the planner turns, every provider call, scoring, the verifier and the memo. Because of it we found that an early resume did not re-run a failed enrichment, and fixed it. The traces also show Gemini calls failing and the run still completing through the rule-based fallback, and they let us measure the real AI cost per call (about $0.003 per planner call and $0.0015 to $0.02 per memo draft, against $0.05 per audit assumed in the business plan; the free tier was billed at $0).",
        "A controlled experiment compared a loose memo prompt with a strict one on the same synthetic cases. The honest result: no difference in unsupported claims (zero in both), but the strict prompt produced more claims that passed verification outright (5 versus 2 on one scenario, 6 versus 1 on the other). It was one run per variant, so treat it as an indication only. The first run of the second scenario was invalid because of a budget bug we found and fixed, and it was re-run on 2026-10-12.",
      ],
      images: [
        {
          path: "evidence/neatlogs/screenshots/Screenshot 2026-10-11 213732.png",
          caption:
            "Live Airtable investigation: real tool latencies, Gemini errors and successful retries inside the planner steps.",
        },
        {
          path: "evidence/neatlogs/screenshots/Screenshot 2026-10-11 213609.png",
          caption:
            "Resilience: several Gemini calls show Execution Failed, yet the run completes through the rule-based fallback, verifies and renders the memo.",
        },
        {
          path: "evidence/neatlogs/screenshots/Screenshot 2026-10-11 213802.png",
          caption:
            "Failure recovery: the resumed run retries the failed enrichment and completes without repeating completed calls.",
        },
        {
          path: "evidence/neatlogs/screenshots/Screenshot 2026-10-11 213710.png",
          caption:
            "Live memo regeneration through recover_run: 11,146 tokens, $0.02, and no new tool calls.",
        },
        {
          path: "evidence/neatlogs/screenshots/Screenshot 2026-10-11 213426.png",
          caption:
            "Synthetic run showing the input and output summary and the Gemini 3.1-flash-lite synthesis step (2,175 tokens, $0.0015).",
        },
      ],
    },
    {
      id: "entire-cfo",
      title: "Entire and cfo.ai",
      summary:
        "Entire makes the build traceable; cfo.ai holds the business plan. Both are hypotheses and records, not traction.",
      paragraphs: [
        "Entire links commits to the Claude Code session that produced them. Commit 70400f8 carries checkpoint 01M4NTHZJBFDKJ80R5FCA3CDZS and a transcript of the build session is saved in the repository, including the hand-offs from the lead model to its Sonnet sub-agents. One gotcha: the commit hook asks an interactive question that blocks an automated shell, which we resolved by answering once in a terminal.",
        "The cfo.ai plan compares pricing of $750, $1,500 or $3,000 per audit, a $24,000 annual plan, and a hybrid. Delivery cost is $94.65 per audit, mostly an assumed 1.5 hours of human review. The three scenarios below are assumptions: DealScope has no customers, no revenue and no signed pilots. Runway is left blank because opening cash is unknown.",
        "Real runs fed back into the plan: Crustdata use measured 9.18 to 12.21 credits per audit against the 26 the plan assumed, so the modeled data cost is conservative. The measured numbers have not yet been written back into the cfo.ai export.",
      ],
      table: {
        headers: ["12 months", "Conservative", "Base", "Growth"],
        rows: [
          ["Earned revenue", "$30,000", "$270,000", "$390,000"],
          ["Audits delivered", "40", "180", "390"],
          ["Gross margin", "87.20%", "93.69%", "90.54%"],
          ["Peak modeled funding need", "$1,500", "$0", "$0"],
        ],
      },
    },
    {
      id: "limits",
      title: "Limits and what comes next",
      summary:
        "What you should not read into the results, and what we would do next.",
      paragraphs: [
        "Results come from a few live cases and two synthetic scenarios. Signal thresholds are unvalidated heuristics, and public-profile coverage is incomplete. The Gemini free tier forced model switches and fallbacks, and one live trace is missing from the neatlogs dashboard because of an ingest outage.",
        "Next steps we would take: re-export the business plan with measured costs, run more live cases with a higher-quota model key to compare AI and rule-based planning, add a human review step in the app, and run paid pilots with agreed accuracy and usefulness criteria.",
      ],
      bullets: [
        "A memo is a starting point for validation, not a conclusion about the company.",
        "Full detail and evidence links: docs/walkthrough.md.",
      ],
    },
  ],
};
