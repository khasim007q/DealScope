// Dev-only mock backend, used only when VITE_USE_MOCKS === "true" (see src/api/client.ts).
import type {
  CaseListItem,
  CaseView,
  CreateCaseResponse,
  FaultOption,
  IdentityResult,
  Scenario,
  StatusResponse,
} from "../api/types";
import { sampleCase } from "./sampleCase";

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
