import type { CaseView } from "../api/types";
import { plural } from "../lib/format";
import { StepTimeline } from "./StepTimeline";

export function ProgressPanel({ view }: { view: CaseView }) {
  const recent = view.steps.slice(-12);
  return (
    <section className="progress" aria-labelledby="progress-h">
      <div className="progress-rule" aria-hidden="true">
        <span />
      </div>
      <p className="kicker accent">Live</p>
      <h2 id="progress-h">Investigation in progress</h2>
      <p className="progress-q" aria-live="polite">
        {view.current_question ? (
          <>
            <span className="micro-label">Working on</span>
            {view.current_question}
          </>
        ) : (
          "Planning the next step..."
        )}
      </p>
      <p className="muted small">
        {view.planner_turns} planning {plural(view.planner_turns, "step")}, {view.tool_calls} data{" "}
        {plural(view.tool_calls, "lookup")} so far. This page updates automatically.
      </p>
      {recent.length > 0 ? (
        <div className="live-steps" role="log" aria-live="off" aria-label="Latest investigation steps">
          <StepTimeline steps={recent} newestFirst />
        </div>
      ) : (
        <p className="muted">No steps yet.</p>
      )}
    </section>
  );
}
