// API contract between the DealScope FastAPI server (src/dealscope/api) and this frontend.
// All user-facing wording is produced server-side in plain language; the UI must not show raw
// internal codes (reason codes, stage enums) except inside an optional "technical details" disclosure.

export type RunMode = "live" | "synthetic";
export type Tone = "good" | "neutral" | "caution" | "bad" | "info";

export interface ProviderStatus {
  key: "crustdata" | "llm" | "jobs_pricing" | "job_boards" | "pdl";
  label: string; // e.g. "Company data (Crustdata)"
  connected: boolean;
  optional?: boolean; // optional systems are not counted in the "connected" total
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
  pdl_key_present?: boolean;
  data_provider?: "free" | "crustdata"; // optional: which live data source is configured; absent on older servers
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
  status: "ok" | "unverified" | "ambiguous" | "mismatch" | "no_match" | "error"; // unverified counts as pass (ok: true)
  resolved_name: string | null;
  match_count: number;
  message: string; // plain-language explanation, e.g. "23 different companies use this domain..."
  candidates: IdentityCandidate[];
}

export interface CreateCaseRequest {
  target_domain: string;
  mode: RunMode;
  competitor_domains?: string[]; // optional, 0-5 (default [])
  deal_thesis?: string; // optional: server applies a generic default
  lookback_months?: number; // optional (default 12)
  max_case_credits?: number; // optional (default 40)
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
  free?: boolean; // free-source run: nothing metered
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

/** The one-screen answer shown first on the case page. Optional: older servers do not send it. */
export interface AnswerView {
  headline: string; // "Investigating..." while running
  level: string | null; // verdict word, e.g. "Watch"; null when there is not enough evidence
  tone: Tone;
  score: number | null;
  top_questions: string[]; // up to 3
  coverage_note: string;
  next_step: string;
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
  answer?: AnswerView; // plain-language answer; fall back to assessment/summary fields when absent
  assessment: Assessment | null; // null until the first scoring
  signals: SignalView[];
  findings: FindingView[];
  questions: string[]; // diligence questions for management
  steps: StepView[];
  companies: CompanyRow[];
  people: PersonRow[];
  jobs: JobRow[];
  credits: CreditsView;
  verification: VerificationView | null;
  trace_ids: string[];
  llm_model: string | null;
  updated_at: string;
  report_available: boolean;
}

// ---------------------------------------------------------------------------
// v0.3 additions: featured (recorded) cases, cancel, Crustdata credit evidence summary
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

export interface EvidenceSummary {
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

// ---------------------------------------------------------------------------
// v0.4: recorded trace flows (OpenTelemetry spans recorded locally)
// ---------------------------------------------------------------------------

export interface TraceSpanEvent {
  name: string; // e.g. "retry", "score_change", "state_transition", "exception"
  at_ms: number; // offset from trace start
  attributes: Record<string, string | number | boolean>;
}

export interface TraceSpan {
  span_id: string;
  parent_id: string | null;
  name: string; // e.g. "investigation_workflow", "tool.enrich_company", "plan_next_action", "gemini-3.8-flash"
  kind: string; // "WORKFLOW" | "AGENT" | "TOOL" | "CHAIN" | "GUARDRAIL" | "LLM" | other
  start_ms: number; // offset from trace start
  duration_ms: number;
  status: "ok" | "error";
  error: string | null;
  attributes: Record<string, string | number | boolean>; // filtered: dealscope.*, model/token/cost fields; no prompt text
  events: TraceSpanEvent[];
}

export interface RecordedTrace {
  trace_id: string; // OpenTelemetry trace id
  started_at: string; // ISO
  duration_ms: number;
  span_count: number;
  error_count: number;
  spans: TraceSpan[];
}

// GET /api/cases/{id}/traces -> RecordedTrace[]  (one per run of the case, oldest first; empty for runs recorded
// before local trace capture existed)
