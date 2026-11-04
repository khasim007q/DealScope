import type { AnswerView, CaseView } from "../api/types";

/** The server's plain-language answer, or one derived from the older assessment fields when absent. */
export function answerFor(v: CaseView): AnswerView {
  if (v.answer) return v.answer;
  const a = v.assessment;
  if (v.running && !a) {
    return { headline: "Investigating...", level: "Pending", tone: "info", score: null, top_questions: [], coverage_note: "", next_step: "" };
  }
  return {
    headline: a?.headline ?? v.status_detail ?? v.status_label,
    level: a ? (a.risk_band ?? null) : v.status_label,
    tone: a?.risk_tone ?? v.status_tone,
    score: a?.risk_score ?? null,
    top_questions: v.questions.slice(0, 3),
    coverage_note: a ? `${a.coverage_label} (${Math.round(a.coverage_pct)}% of the evidence we looked for was found).` : "",
    next_step: v.can_resume
      ? "Resume the search to fill the gaps."
      : "Open the full report below, then put these questions to management.",
  };
}
