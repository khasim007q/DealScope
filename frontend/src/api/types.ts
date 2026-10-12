// API contract between the DealScope FastAPI server (src/dealscope/api) and this frontend.
// All user-facing wording is produced server-side in plain language; the UI must not show raw
// internal codes (reason codes, stage enums) except inside an optional "technical details" disclosure.

export type RunMode = "live" | "synthetic";
export type Tone = "good" | "neutral" | "caution" | "bad" | "info";

export interface ProviderStatus {
  key: "crustdata" | "llm" | "neatlogs" | "jobs_pricing";
  label: string; // e.g. "Company data (Crustdata)"
  connected: boolean;
  detail: string; // e.g. "Connected" / "Model: gemini-3.1-flash-lite" / "Not configured"
}

export interface BudgetSummary {
  spendable: number; // credits allowed for product use (total minus reserve)
  estimated_used: number;
  actual_used: number; // confirmed from provider response headers
  reserved: number;
  remaining: number;
  unknown_calls: number;
  reserve: number; // credits held back and never spent
  total: number;
}

export interface StatusResponse {
  providers: ProviderStatus[];
  live_budget: BudgetSummary;
  max_case_credits: number;
  live_available: boolean; // false when no Crustdata key: live runs are refused, never faked
}

export interface Scenario {
  id: string; // "scenario_a" | "scenario_b" | "synthetic_case"
  label: string;
  description: string;
  target_domain: string;
  competitor_domains: string[];
  deal_thesis: string;
}

export interface FaultOption {
  id: string; // "none" | "retry_success" | "retry_exhausted" | "auth_failure"
  label: string;
  description: string;
}

export interface IdentityCandidate {
  name: string | null;
  primary_domain: string | null;
  employee_count_range: string | null;
}

export interface IdentityResult {
  domain: string;
  ok: boolean;
  status: "ok" | "ambiguous" | "mismatch" | "no_match" | "error";
  resolved_name: string | null;
  match_count: number;
  message: string; // plain-language explanation, e.g. "23 different companies use this domain..."
  candidates: IdentityCandidate[];
}

export interface CreateCaseRequest {
  target_domain: string;
  competitor_domains: string[];
  deal_thesis: string;
  lookback_months: number;
  max_case_credits: number;
  mode: RunMode;
  scenario_id?: string; // synthetic only
  fault_id?: string; // synthetic only
}

export interface CreateCaseResponse {
  case_id: string;
}

export interface CaseListItem {
  case_id: string;
  target: string;
  mode: RunMode;
  status_label: string; // "Complete", "Partial - can resume", "Running", "Failed"
  tone: Tone;
  risk_label: string; // "Watch (32/100)" or "Not enough evidence"
  updated_at: string; // ISO
}

export interface Assessment {
  risk_score: number | null; // 0-100, null when coverage < 60%
  risk_band: string | null; // "Low signal" | "Watch" | "Elevated" | "High signal"
  risk_tone: Tone;
  headline: string; // one plain sentence summarising the result
  coverage_pct: number;
  coverage_label: string; // "Enough evidence to score" / "Provisional" / "Not enough evidence"
  confidence: number; // 0-100, evidence quality (separate from risk)
  confidence_label: string; // "High" | "Medium" | "Low"
  explainer: string; // how to read risk vs coverage vs confidence
}

export interface SignalView {
  id: string; // "S1".."S5"
  name: string; // plain name, e.g. "Engineering team vs. company growth"
  question: string; // the question this signal answers
  weight_pct: number;
  scored: boolean;
  score: number | null;
  band: string | null; // band label for this signal score
  tone: Tone;
  status_label: string; // "Scored" | "Partly scored (thin data)" | "Not scored"
  confidence: number;
  finding: string; // plain-language result, built from reason codes and raw measures
  why_it_matters: string;
  limitations: string[];
  evidence_ids: string[];
  technical: { reason_codes: string[]; state: string };
}

export interface EvidenceRef {
  id: string;
  label: string; // "Company profile - notion.com" / "Job posting - Staff SRE"
  date: string | null;
  source: string; // "Crustdata /job/search" or "Synthetic fixture"
}

export interface FindingView {
  id: string;
  kind: "Fact" | "Interpretation" | "Hypothesis" | "Question";
  severity: "low" | "medium" | "high";
  text: string;
  verification: "Verified" | "Verified with caveats";
  caveats: string[];
  evidence: EvidenceRef[];
  counter_evidence: EvidenceRef[];
  alternatives: string[];
  limitations: string[];
}

export interface StepView {
  n: number;
  at: string; // ISO timestamp
  kind: "plan" | "tool" | "retry" | "score" | "stage" | "resume" | "blocked" | "note";
  title: string; // plain, e.g. "Checked open engineering roles at notion.com"
  detail: string; // plain explanation, e.g. "Found 25 postings; 14 were reposted."
  actor: string; // "AI planner" | "Rule-based planner" | "Baseline" | "System" | "Retry policy"
  tone: Tone;
  credits: string | null; // e.g. "2 credits (confirmed)" / "from cache, 0 credits"
}

export interface CompanyRow {
  domain: string;
  role: "Target" | "Peer";
  name: string | null;
  headcount: number | null;
  total_growth: Record<string, number>; // period label ("3m","6m","12m") -> percent
  engineering_headcount: number | null;
  engineering_growth: Record<string, number>;
  open_jobs: number | null;
  data_quality_flags: string[]; // plain sentences
  evidence_id: string;
}

export interface PersonRow {
  ref: string; // opaque, never a name
  role_group: string; // plain: "Technical leadership"
  title_at_target: string | null;
  left_target: string | null; // "2026-05" or null if still there / unknown
  status: string; // "Left in lookback window" | "Left earlier" | "Still at target" | "End date unknown"
  now_at: string | null;
  now_at_competitor: boolean;
  evidence_id: string;
}

export interface JobRow {
  title: string;
  capability: string; // plain: "Security"
  posted: string | null;
  reposted: boolean | null;
  openings: number | null;
  url: string | null;
  evidence_id: string;
}

export interface CreditsView {
  cap: number;
  estimated_used: number;
  actual_used: number;
  reserved: number;
  remaining: number;
  unknown_calls: number;
  simulated: boolean; // synthetic runs: simulated accounting, no real credits
}

export interface VerificationView {
  published: number;
  verified: number;
  with_caveats: number;
  rejected: number;
  grounded_rate: number | null; // 0-1
  rejected_reasons: { reason: string; count: number }[]; // plain reasons
  ai_draft_used: boolean; // false when the AI write-up was unavailable and only rule-based findings are shown
}

export interface CaseView {
  case_id: string;
  mode: RunMode;
  synthetic: boolean;
  target: string;
  peers: string[];
  thesis: string;
  lookback_months: number;
  running: boolean;
  status_label: string;
  status_tone: Tone;
  status_detail: string; // plain explanation of how/why the run ended
  can_resume: boolean;
  current_question: string | null;
  planner_turns: number;
  tool_calls: number;
  assessment: Assessment | null; // null until the first scoring
  signals: SignalView[];
  findings: FindingView[];
  questions: string[]; // diligence questions for management
  steps: StepView[];
  companies: CompanyRow[];
  people: PersonRow[];
  jobs: JobRow[];
  credits: CreditsView;
  plan_comparison: PlanComparison | null;
  verification: VerificationView | null;
  trace_ids: string[];
  llm_model: string | null;
  updated_at: string;
  report_available: boolean;
}

// ---------------------------------------------------------------------------
// v0.3 additions: featured (recorded) cases, cancel, partner evidence summary
// ---------------------------------------------------------------------------

// GET /api/featured -> FeaturedCase[]  (finished live cases bundled with the repo; open without spending credits)
export interface FeaturedCase {
  case_id: string;
  label: string; // e.g. "notion.com vs coda.io, airtable.com, clickup.com"
  description: string;
  recorded_at: string; // ISO date of the live run
}

// POST /api/cases/{id}/cancel -> CreateCaseResponse  (409 when the case is not running)
// After cancelling, the case ends with status_label "Stopped by you" and can be resumed.

export interface NeatlogsRun {
  label: string; // "Live investigation - airtable.com"
  kind: "live" | "failure" | "eval";
  case_id: string | null;
  trace_ids: string[];
  summary: string; // plain sentence with the outcome
}

export interface EvalRow {
  scenario: string; // "A" | "B"
  variant: "baseline" | "improved";
  trace_id: string | null;
  draft_claims: number;
  draft_rejected: number;
  draft_verified: number;
  draft_with_caveats: number;
  published: number;
  tool_calls: number;
}

export interface EvidenceFile {
  label: string;
  path: string; // repo-relative "evidence/..."; images and PDFs load from /api/evidence/<path after "evidence/">
}

export interface EvidenceSummary {
  neatlogs: {
    runs: NeatlogsRun[];
    eval_rows: EvalRow[];
    eval_reading: string; // honest one-paragraph interpretation
    screenshots: EvidenceFile[];
  };
  entire: {
    checkpoints: { commit: string; subject: string; checkpoint: string }[];
    screenshots: EvidenceFile[];
    transcript_path: string | null;
    notes: string[];
  };
  cfo: {
    scenarios: {
      name: string;
      revenue: string;
      audits: string;
      gross_margin: string;
      contribution_margin: string;
      peak_funding_need: string;
    }[];
    unit_cost: string; // e.g. "$94.65 per audit (QA $90, tooling $2, Crustdata $2.60, LLM $0.05)"
    pricing: string[];
    notes: string[];
    files: EvidenceFile[];
  };
  crustdata: {
    total: number;
    reserve: number;
    spendable: number;
    actual_used: number;
    estimated_used: number;
    remaining: number;
    prices: { endpoint: string; credits: string }[];
    notes: string[];
  };
}

// Case cost vs the cfo.ai business-plan assumptions per audit (USD). Plan values are editable assumptions.
export interface PlanComparison {
  dollars_per_credit: number;
  credits_used: number;
  credits_basis: string; // "confirmed credits" | "estimated credits" | "simulated credits (demo data)"
  simulated: boolean;
  data_cost_case: number;
  data_cost_plan: number;
  plan_credits_per_audit: number;
  llm_cost_plan: number;
  llm_tokens: number | null; // tokens in the latest run, as reported by the provider
  llm_calls: number | null;
  llm_model: string | null;
  review_cost: number;
  tooling_cost: number;
  total_case: number;
  total_plan: number;
  price: number;
  margin_case_pct: number | null;
  margin_plan_pct: number | null;
  summary: string;
  notes: string[];
}
