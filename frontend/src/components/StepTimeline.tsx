import type { StepView, Tone } from "../api/types";
import { formatTime } from "../lib/format";

function actorTone(actor: string): Tone {
  const a = actor.toLowerCase();
  if (a.startsWith("ai")) return "info";
  if (a.startsWith("rule")) return "caution";
  if (a.startsWith("retry")) return "caution";
  return "neutral";
}

export function StepTimeline({ steps, newestFirst = false }: { steps: StepView[]; newestFirst?: boolean }) {
  const ordered = newestFirst ? [...steps].reverse() : steps;
  return (
    <ol className="timeline">
      {ordered.map((s) => (
        <li key={s.n} className={`tone-${s.tone}`}>
          <span className="tl-dot" aria-hidden="true" />
          <div className="tl-top">
            <span className="tl-title">{s.title}</span>
            <span className={`actor tone-${actorTone(s.actor)}`}>{s.actor}</span>
          </div>
          {s.detail ? <p className="tl-detail">{s.detail}</p> : null}
          <div className="tl-meta">
            <span>Step {s.n}</span>
            {s.at ? (
              <time dateTime={s.at}>{formatTime(s.at)}</time>
            ) : null}
            {s.credits ? <span>{s.credits}</span> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
