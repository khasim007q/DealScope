import type { StepView, Tone } from "../api/types";
import { formatTime } from "../lib/format";

function actorTone(actor: string): Tone {
  const a = actor.toLowerCase();
  if (a.startsWith("ai")) return "info";
  if (a.startsWith("rule")) return "caution";
  if (a.startsWith("retry")) return "caution";
  return "neutral";
}

/** Quiet log of agent steps: step number, title with actor, detail, time and credits. */
export function StepTimeline({ steps, newestFirst = false }: { steps: StepView[]; newestFirst?: boolean }) {
  const ordered = newestFirst ? [...steps].reverse() : steps;
  return (
    <ol className="steplog">
      {ordered.map((s) => (
        <li key={s.n} className={`tone-${s.tone}`}>
          <span className="sl-n" aria-hidden="true">
            {s.n}
          </span>
          <div className="sl-body">
            <div className="sl-top">
              <span className="sl-title">
                <span className="sr-only">Step {s.n}: </span>
                {s.title}
              </span>
              <span className={`actor tone-${actorTone(s.actor)}`}>{s.actor}</span>
            </div>
            {s.detail ? <p className="sl-detail">{s.detail}</p> : null}
            <div className="sl-meta">
              {s.at ? <time dateTime={s.at}>{formatTime(s.at)}</time> : null}
              {s.credits ? <span>{s.credits}</span> : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
