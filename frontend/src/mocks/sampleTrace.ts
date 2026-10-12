import type { EntireCommitCheckpoint, EvidenceTrace, RecordedTrace, TraceSpan } from "../api/types";

const ERR_429 =
  "429 RESOURCE_EXHAUSTED: Quota exceeded for model gemini-3.8-flash. Please retry in 28s. The run fell back to gemini-3.1-flash-lite.";

function span(
  id: string,
  parent: string | null,
  name: string,
  kind: string,
  start_ms: number,
  duration_ms: number,
  extra: Partial<TraceSpan> = {},
): TraceSpan {
  return {
    span_id: id,
    parent_id: parent,
    name,
    kind,
    start_ms,
    duration_ms,
    status: "ok",
    error: null,
    attributes: {},
    events: [],
    ...extra,
  };
}

const spans: TraceSpan[] = [
  span("s01", null, "investigation_workflow", "WORKFLOW", 0, 41800, {
    attributes: { "dealscope.case_id": "case_live_airtable", "dealscope.mode": "live", "neatlogs.span.kind": "workflow" },
  }),
  span("s02", "s01", "tool.enrich_company", "TOOL", 120, 1480, { attributes: { "dealscope.domain": "airtable.com", "dealscope.credits": 1 } }),
  span("s03", "s01", "tool.enrich_company", "TOOL", 1700, 1320, { attributes: { "dealscope.domain": "notion.com", "dealscope.credits": 1 } }),
  span("s04", "s01", "tool.enrich_company", "TOOL", 3100, 5200, {
    attributes: { "dealscope.domain": "smartsheet.com", "dealscope.credits": 1, "dealscope.attempts": 3 },
    events: [
      { name: "retry", at_ms: 4100, attributes: { attempt: 1, reason: "HTTP 503 from provider", wait_s: 1 } },
      { name: "retry", at_ms: 6300, attributes: { attempt: 2, reason: "HTTP 503 from provider", wait_s: 2 } },
    ],
  }),
  span("s05", "s01", "tool.enrich_company", "TOOL", 8500, 1100, { attributes: { "dealscope.domain": "clickup.com", "dealscope.credits": 1 } }),
  span("s06", "s01", "score_signals", "CHAIN", 9800, 620, { attributes: { "dealscope.signals_scored": 3, "dealscope.coverage_pct": 60 } }),
  span("s07", "s01", "plan_next_action", "AGENT", 10500, 9400, { attributes: { "dealscope.turn": 2 } }),
  span("s08", "s07", "gemini-3.8-flash", "LLM", 10600, 1900, {
    status: "error",
    error: ERR_429,
    attributes: { "llm.model": "gemini-3.8-flash", "dealscope.attempt": 1 },
    events: [{ name: "exception", at_ms: 12400, attributes: { type: "ResourceExhausted" } }],
  }),
  span("s09", "s07", "gemini-3.8-flash", "LLM", 12600, 1700, {
    status: "error",
    error: ERR_429,
    attributes: { "llm.model": "gemini-3.8-flash", "dealscope.attempt": 2 },
  }),
  span("s10", "s07", "gemini-3.1-flash-lite", "LLM", 14500, 5200, {
    attributes: {
      "llm.model": "gemini-3.1-flash-lite",
      "llm.token_count.prompt": 4812,
      "llm.token_count.completion": 356,
      "llm.token_count.total": 5168,
      "dealscope.fallback": true,
    },
  }),
  span("s11", "s01", "tool.search_jobs", "TOOL", 20000, 2400, { attributes: { "dealscope.domain": "airtable.com", "dealscope.credits": 2 } }),
  span("s12", "s01", "score_signals", "CHAIN", 22500, 540, { attributes: { "dealscope.signals_scored": 4, "dealscope.coverage_pct": 80 } }),
  span("s13", "s01", "synthesize_findings", "CHAIN", 23200, 12600, { attributes: { "dealscope.draft_claims": 11 } }),
  span("s14", "s13", "gemini-3.1-flash-lite", "LLM", 23400, 12100, {
    attributes: {
      "llm.model": "gemini-3.1-flash-lite",
      "llm.token_count.prompt": 7340,
      "llm.token_count.completion": 1520,
      "llm.token_count.total": 8860,
    },
  }),
  span("s15", "s01", "verify_claims", "GUARDRAIL", 35900, 3100, {
    attributes: { "dealscope.claims_checked": 11, "dealscope.rejected": 2, "dealscope.published": 9 },
  }),
  span("s16", "s01", "render_memo", "CHAIN", 39100, 2600, { attributes: { "dealscope.report_format": "markdown" } }),
];

export const sampleTrace: RecordedTrace = {
  trace_id: "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  started_at: "2026-10-10T08:05:12Z",
  duration_ms: 41800,
  span_count: spans.length,
  error_count: spans.filter((s) => s.status === "error").length,
  spans,
};

const resumeSpans: TraceSpan[] = [
  span("r01", null, "investigation_workflow", "WORKFLOW", 0, 9800, { attributes: { "dealscope.resumed": true } }),
  span("r02", "r01", "tool.enrich_company", "TOOL", 100, 1500, { attributes: { "dealscope.domain": "smartsheet.com", "dealscope.credits": 1 } }),
  span("r03", "r01", "score_signals", "CHAIN", 1700, 500),
  span("r04", "r01", "verify_claims", "GUARDRAIL", 2300, 2900),
  span("r05", "r01", "render_memo", "CHAIN", 5300, 2400),
];

export const sampleResumeTrace: RecordedTrace = {
  trace_id: "0f9e8d7c6b5a49382716f5e4d3c2b1a0",
  started_at: "2026-10-10T08:20:40Z",
  duration_ms: 9800,
  span_count: resumeSpans.length,
  error_count: 0,
  spans: resumeSpans,
};

export const sampleCaseTraces: RecordedTrace[] = [sampleTrace, sampleResumeTrace];

export const sampleEvidenceTraces: EvidenceTrace[] = [
  {
    label: "Live run with model rate limit",
    description:
      "Look for the two red gemini-3.8-flash steps: the model was rate limited, the agent fell back to gemini-3.1-flash-lite and finished.",
    trace: sampleTrace,
  },
  {
    label: "Failure recovery: resumed run",
    description: "A short second run that picks up where the first stopped and finishes the memo.",
    trace: sampleResumeTrace,
  },
];

export const sampleEntireFlow: EntireCommitCheckpoint[] = [
  {
    checkpoint: "a3f91c2d4e7b",
    commit: "fe73170",
    date: "2026-10-12T09:14:00Z",
    subject: "Clean up repository: remove spec pack, build prompt and duplicate write-ups",
    files_changed: 14,
    insertions: 42,
    deletions: 1380,
    files: [
      { path: "docs/build-prompt.md", insertions: 0, deletions: 640 },
      { path: "spec/README.md", insertions: 3, deletions: 410 },
      { path: "README.md", insertions: 39, deletions: 21 },
    ],
  },
  {
    checkpoint: "7be20a914c3d",
    commit: "9cf484c",
    date: "2026-10-11T18:02:00Z",
    subject: "Show each case's real cost against the cfo.ai business plan",
    files_changed: 6,
    insertions: 318,
    deletions: 24,
    files: [
      { path: "src/dealscope/api/plan.py", insertions: 140, deletions: 4 },
      { path: "frontend/src/components/PlanComparisonCard.tsx", insertions: 120, deletions: 0 },
      { path: "frontend/src/api/types.ts", insertions: 40, deletions: 2 },
    ],
  },
  {
    checkpoint: "2b8e40a6f1d9",
    commit: "8a17c25",
    date: "2026-10-11T11:30:00Z",
    subject: "Add Entire session timeline screenshot to evidence and the Evidence page",
    files_changed: 3,
    insertions: 55,
    deletions: 6,
    files: [{ path: "frontend/src/pages/Evidence.tsx", insertions: 55, deletions: 6 }],
  },
];

export const sampleEntireSession = {
  session_id: "7c1d2e9a-55b0-4c3e-9f21-0a8b6d4e3c11",
  agent: "Claude Code",
  checkpoints_total: 3,
  first: "2026-10-11T11:30:00Z",
  last: "2026-10-12T09:14:00Z",
};
