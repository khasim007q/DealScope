import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { CaseView } from "../api/types";
import { answerFor } from "../lib/answer";
import { formatDuration } from "../lib/format";
import { useNow } from "../lib/hooks";
import { RunControls } from "./CaseControls";
import { Icon, Kicker, StatusPill } from "./ui";

/** When this run (or its latest resume) began, from the recorded step timestamps. */
function runStart(v: CaseView): number | null {
  const resumes = v.steps.filter((x) => x.kind === "resume");
  const first = resumes.length > 0 ? resumes[resumes.length - 1] : v.steps[0];
  const t = first ? Date.parse(first.at) : NaN;
  return Number.isNaN(t) ? null : t;
}

/** One honest progress line: the step reached, what it is doing, and elapsed time. No invented totals. */
function progressLine(v: CaseView, now: number): string {
  const n = v.steps.length;
  const doing = (v.current_question ?? v.steps[n - 1]?.title ?? "").replace(/[.\s]+$/, "");
  const parts: string[] = [];
  if (n > 0) parts.push(`Step ${n}`);
  parts.push(doing ? `${doing}...` : "Getting started...");
  const start = runStart(v);
  if (start !== null && now - start >= 1000) parts.push(formatDuration(Math.floor((now - start) / 1000) * 1000));
  return parts.join(" · ");
}

/** A next step that is really about setup (keys, config) is a quiet note, not the call to action. */
const SETUP_HINT = /\b(api[ -]?keys?|keys?|config(?:ure|uration)?|\.env|credentials?|tokens?|environment variables?|set ?up)\b/i;

function RunningPanel({ view }: { view: CaseView }) {
  const now = useNow(1000);
  return (
    <div className="answer-wait">
      <div className="answer-progress" aria-hidden="true">
        <span />
      </div>
      <p className="answer-line">{progressLine(view, now)}</p>
      <div className="skeleton" aria-hidden="true">
        <i style={{ width: "92%" }} />
        <i style={{ width: "74%" }} />
        <i style={{ width: "48%" }} />
      </div>
      <p className="small muted">This takes a minute or two. You can leave this page open; it updates by itself.</p>
    </div>
  );
}

/** The first thing on the case page: the answer, what to ask, what to do next. Skeleton plus one calm line while running. */
export function AnswerCard({ view, onChanged }: { view: CaseView; onChanged: () => void }) {
  const ans = answerFor(view);
  const running = view.running;
  const setupNote = !!ans.next_step && SETUP_HINT.test(ans.next_step);

  return (
    <section className={`answer tone-${running ? "info" : ans.tone}`} aria-labelledby="answer-h">
      <Kicker accent>{running ? "Investigating" : "Result"}</Kicker>
      <h1 id="answer-h" className="answer-target">
        {view.target}
      </h1>

      {running ? (
        <RunningPanel view={view} />
      ) : (
        <>
          <p className="answer-headline">{ans.headline}</p>
          <p className="answer-level">
            {ans.level ? (
              <StatusPill tone={ans.tone}>{ans.level}</StatusPill>
            ) : (
              <StatusPill tone="neutral">Not enough evidence</StatusPill>
            )}
            {ans.score !== null ? (
              <span className="answer-score" aria-label={`Risk score ${ans.score} out of 100`}>
                {ans.score}
                <small>/100 risk</small>
              </span>
            ) : null}
          </p>
          {ans.coverage_note ? (
            <p className="answer-note">
              <strong>Coverage.</strong> {ans.coverage_note}
            </p>
          ) : null}

          {ans.top_questions.length > 0 ? (
            <div className="answer-questions">
              <h2>Ask management</h2>
              <ol>
                {ans.top_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ol>
            </div>
          ) : null}

          {ans.next_step && !setupNote ? (
            <p className="answer-next">
              <strong>Next step.</strong> {ans.next_step}
            </p>
          ) : null}
          {ans.next_step && setupNote ? <p className="small muted answer-info">{ans.next_step}</p> : null}
        </>
      )}

      {view.status_detail && !running && view.status_tone !== "good" ? (
        <p className="small muted answer-status">{view.status_detail}</p>
      ) : null}

      <div className="btn-row answer-actions">
        {view.report_available && !running ? (
          <a className="btn primary" href={api.reportUrl(view.case_id)} download>
            <Icon name="download" size={16} />
            Download memo
          </a>
        ) : null}
        <Link className={view.report_available && !running ? "btn" : "btn primary"} to="/">
          New search
        </Link>
        <RunControls view={view} onResumed={onChanged} />
      </div>
    </section>
  );
}
