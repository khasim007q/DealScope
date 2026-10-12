// Dev-only mock backend, used only when VITE_USE_MOCKS === "true" (see src/api/client.ts).
import type {
  CaseListItem,
  CaseView,
  CreateCaseResponse,
  EvidenceSummary,
  FaultOption,
  FeaturedCase,
  IdentityResult,
  RecordedTrace,
  Scenario,
  StatusResponse,
} from "../api/types";
import { sampleCase } from "./sampleCase";
import { sampleCaseTraces, sampleEntireFlow, sampleEntireSession, sampleEvidenceTraces } from "./sampleTrace";

const delay = <T>(v: T, ms = 250): Promise<T> => new Promise((r) => window.setTimeout(() => r(v), ms));

export function status(): Promise<StatusResponse> {
  return delay({
    providers: [
      { key: "crustdata", label: "Company data (Crustdata)", connected: true, detail: "Connected" },
      { key: "llm", label: "AI model", connected: true, detail: "Model: gemini-3.1-flash-lite" },
      { key: "neatlogs", label: "Tracing (Neatlogs)", connected: false, detail: "Not configured" },
      { key: "jobs_pricing", label: "Job-posting pricing", connected: true, detail: "Connected" },
    ],
    live_budget: { spendable: 150, estimated_used: 10, actual_used: 8, reserved: 0, remaining: 140, unknown_calls: 0, reserve: 50, total: 200 },
    max_case_credits: 60,
    live_available: true,
  });
}

export function scenarios(): Promise<Scenario[]> {
  return delay([
    { id: "scenario_a", label: "Engineering slowdown", description: "A target whose engineering team lags company growth.", target_domain: "northwind.example", competitor_domains: ["contoso.example", "fabrikam.example"], deal_thesis: "We expect the engineering team to keep pace with company growth after the acquisition." },
    { id: "scenario_b", label: "Leadership exits", description: "A target losing senior technical leaders to a competitor.", target_domain: "tailspin.example", competitor_domains: ["wingtip.example", "litware.example", "adatum.example"], deal_thesis: "No key technical leaders are likely to leave within a year of closing." },
  ]);
}

export function faults(): Promise<FaultOption[]> {
  return delay([
    { id: "none", label: "None", description: "Run normally." },
    { id: "retry_success", label: "Temporary outage, then recovery", description: "A data source fails once, then works on retry." },
    { id: "retry_exhausted", label: "Persistent outage", description: "A data source keeps failing; the agent must continue with less data." },
    { id: "auth_failure", label: "Authentication failure", description: "The data source rejects credentials; the run stops safely and can be resumed." },
  ]);
}

export function identityCheck(domains: string[]): Promise<IdentityResult[]> {
  return delay(
    domains.map((d, i): IdentityResult =>
      i === 1
        ? {
            domain: d, ok: false, status: "ambiguous", resolved_name: null, match_count: 23,
            message: "23 different companies use this domain. Pick the one you mean.",
            candidates: [
              { name: "Contoso Labs", primary_domain: "contoso-labs.example", employee_count_range: "1001-5000" },
              { name: "Contoso Group", primary_domain: null, employee_count_range: null },
            ],
          }
        : { domain: d, ok: true, status: "ok", resolved_name: d.split(".")[0], match_count: 1, message: "Matched one company.", candidates: [] },
    ),
  );
}

export function createCase(): Promise<CreateCaseResponse> {
  startedAt = Date.now();
  return delay({ case_id: sampleCase.case_id });
}

export function listCases(): Promise<CaseListItem[]> {
  return delay([
    { case_id: sampleCase.case_id, target: sampleCase.target, mode: "synthetic", status_label: "Complete", tone: "good", risk_label: "Watch (41/100)", updated_at: sampleCase.updated_at },
    { case_id: "case_live_0002", target: "notion.com", mode: "live", status_label: "Partial - can resume", tone: "caution", risk_label: "Not enough evidence", updated_at: new Date(Date.now() - 3600_000).toISOString() },
  ]);
}

export function cancelCase(id: string): Promise<CreateCaseResponse> {
  startedAt = 0;
  return delay({ case_id: id });
}

export function featured(): Promise<FeaturedCase[]> {
  return delay([
    {
      case_id: "case_live_notion",
      label: "notion.com vs coda.io, airtable.com, clickup.com",
      description: "A finished live run on a productivity-software target. Opens instantly and spends no credits.",
      recorded_at: "2026-10-09T14:20:00Z",
    },
    {
      case_id: "case_live_airtable",
      label: "airtable.com vs notion.com, smartsheet.com",
      description: "A finished live run that ended with partial coverage, showing how thin data is handled.",
      recorded_at: "2026-10-10T08:05:00Z",
    },
  ]);
}

export function evidenceSummary(): Promise<EvidenceSummary> {
  return delay({
    neatlogs: {
      runs: [
        { label: "Live investigation - airtable.com", kind: "live", case_id: "case_live_airtable", trace_ids: ["a1b2c3d4e5f60718293a4b5c6d7e8f90"], summary: "Finished with 4 of 5 signals scored; 7 claims published after verification." },
        { label: "Failure drill - auth failure", kind: "failure", case_id: null, trace_ids: ["0f9e8d7c6b5a49382716f5e4d3c2b1a0"], summary: "The data source rejected credentials; the run stopped safely and was resumed." },
        { label: "Improvement experiment - scenario A", kind: "eval", case_id: null, trace_ids: ["11112222333344445555666677778888", "99990000aaaabbbbccccddddeeeeffff"], summary: "Baseline and improved prompt compared on the same synthetic data." },
      ],
      eval_rows: [
        { scenario: "A", variant: "baseline", trace_id: "11112222333344445555666677778888", draft_claims: 12, draft_rejected: 5, draft_verified: 5, draft_with_caveats: 2, published: 7, tool_calls: 9 },
        { scenario: "A", variant: "improved", trace_id: "99990000aaaabbbbccccddddeeeeffff", draft_claims: 11, draft_rejected: 2, draft_verified: 7, draft_with_caveats: 2, published: 9, tool_calls: 9 },
        { scenario: "B", variant: "baseline", trace_id: null, draft_claims: 10, draft_rejected: 4, draft_verified: 5, draft_with_caveats: 1, published: 6, tool_calls: 8 },
        { scenario: "B", variant: "improved", trace_id: null, draft_claims: 10, draft_rejected: 1, draft_verified: 7, draft_with_caveats: 2, published: 9, tool_calls: 8 },
      ],
      eval_reading: "The improved prompt cut rejected draft claims in both scenarios without extra tool calls. The sample is two scenarios, so treat it as directional evidence, not a benchmark.",
      screenshots: [
        { label: "Trace list in neatlogs", path: "evidence/neatlogs/trace-list.png" },
        { label: "Single run trace detail", path: "evidence/neatlogs/trace-detail.png" },
      ],
      traces: sampleEvidenceTraces,
    },
    entire: {
      checkpoints: [
        { commit: "be4bb90c1d2e3f405a6b7c8d9e0f1a2b3c4d5e6f", subject: "Replace Streamlit with a React + TypeScript frontend and plain-language API", checkpoint: "chk_7f3a91c2d4" },
        { commit: "75783c2a1b2c3d4e5f60718293a4b5c6d7e8f901", subject: "Live browser test fixes: free identity pre-check, provider data-quality guard", checkpoint: "chk_2b8e40a6f1" },
      ],
      screenshots: [{ label: "Entire session timeline", path: "evidence/entire/session-timeline.png" }],
      flow: sampleEntireFlow,
      session: sampleEntireSession,
      transcript_path: "evidence/entire/session-transcript.md",
      notes: ["Checkpoints were captured automatically at each commit.", "The transcript is the full coding-session log."],
    },
    cfo: {
      scenarios: [
        { name: "Conservative", revenue: "$180,000", audits: "40", gross_margin: "52%", contribution_margin: "38%", peak_funding_need: "$42,000" },
        { name: "Base", revenue: "$420,000", audits: "95", gross_margin: "61%", contribution_margin: "47%", peak_funding_need: "$28,000" },
        { name: "Stretch", revenue: "$900,000", audits: "200", gross_margin: "66%", contribution_margin: "53%", peak_funding_need: "$15,000" },
      ],
      unit_cost: "$94.65 per audit (QA $90, tooling $2, Crustdata $2.60, LLM $0.05)",
      pricing: ["Standard audit: $4,500", "Express audit (48 hours): $6,500", "Monitoring retainer: $1,200 per month"],
      notes: ["Figures come from the cfo.ai scenario exports.", "Human QA is the dominant cost driver."],
      files: [
        { label: "Business plan (PDF)", path: "evidence/cfo/business-plan.pdf" },
        { label: "Scenario model (xlsx)", path: "evidence/cfo/scenarios.xlsx" },
      ],
    },
    crustdata: {
      total: 200,
      reserve: 50,
      spendable: 150,
      actual_used: 8,
      estimated_used: 10,
      remaining: 140,
      prices: [
        { endpoint: "Company search", credits: "0 (free identity check)" },
        { endpoint: "Company enrich", credits: "1 per company" },
        { endpoint: "Job search", credits: "2 per call" },
        { endpoint: "People search", credits: "3 per call" },
      ],
      notes: ["The reserve is never spent by the product.", "Actual use is confirmed from provider response headers."],
    },
  });
}

export function getCaseTraces(): Promise<RecordedTrace[]> {
  return delay(sampleCaseTraces);
}

let startedAt = 0;

export function getCase(id: string): Promise<CaseView> {
  // After creating a case, simulate ~6 s of running before the sample completes.
  const elapsed = Date.now() - startedAt;
  if (startedAt > 0 && elapsed < 6000) {
    const n = Math.max(1, Math.min(sampleCase.steps.length, Math.ceil(elapsed / 1200)));
    return delay({
      ...sampleCase,
      case_id: id,
      running: true,
      status_label: "Running",
      status_tone: "info",
      status_detail: "The investigation is in progress.",
      current_question: "Is the engineering team keeping pace with the company?",
      assessment: null,
      report_available: false,
      steps: sampleCase.steps.slice(0, n),
    });
  }
  return delay({ ...sampleCase, case_id: id });
}
