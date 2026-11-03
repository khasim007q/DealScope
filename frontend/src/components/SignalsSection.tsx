import type { SignalView } from "../api/types";
import { formatPct } from "../lib/format";
import { Disclosure, EmptyBox, StatusPill } from "./ui";
import { ReportHead } from "./ReportHead";

function SignalRow({ s }: { s: SignalView }) {
  const hasScore = s.scored && s.score !== null;
  const pct = hasScore ? Math.max(0, Math.min(100, s.score as number)) : 0;
  return (
    <article className={`signal tone-${s.tone}`} aria-labelledby={`sig-${s.id}`}>
      <div className="signal-fig" aria-hidden="true">
        {hasScore ? (
          <>
            <span className="signal-score">{Math.round(pct)}</span>
            <span className="signal-of">/100</span>
          </>
        ) : (
          <span className="signal-of">n/s</span>
        )}
      </div>
      <div className="signal-body">
        <div className="signal-head">
          <h3 className="signal-name" id={`sig-${s.id}`}>
            {s.name}
          </h3>
          <StatusPill tone={s.tone}>{s.status_label}</StatusPill>
        </div>
        <p className="signal-q">{s.question}</p>

        <div className="bar-row">
          <div
            className="bar-track"
            role="meter"
            aria-label={`${s.name} score`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={hasScore ? Math.round(pct) : undefined}
            aria-valuetext={hasScore ? `${Math.round(pct)} out of 100${s.band ? `, ${s.band}` : ""}` : "Not scored"}
          >
            {hasScore ? <div className="bar-fill" style={{ width: `${pct}%` }} /> : null}
          </div>
          <span className="bar-val">{hasScore ? `${Math.round(pct)} / 100` : "Not scored"}</span>
        </div>
        <p className="kv">
          {hasScore && s.band ? <span>Band: {s.band}</span> : null}
          <span>Weight: {formatPct(s.weight_pct)}</span>
          <span>Confidence: {Math.round(s.confidence)}</span>
        </p>

        <p className="signal-finding">{s.finding}</p>
        <p className="signal-why">
          <span className="micro-label">Why it matters</span> {s.why_it_matters}
        </p>
        {s.limitations.length > 0 ? (
          <div className="signal-lim">
            <span className="micro-label">Limitations</span>
            <ul>
              {s.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <Disclosure summary="Technical details">
          <dl className="tech-list">
            <dt>State</dt>
            <dd>{s.technical.state}</dd>
            <dt>Reason codes</dt>
            <dd>{s.technical.reason_codes.length > 0 ? s.technical.reason_codes.join(", ") : "none"}</dd>
          </dl>
        </Disclosure>
      </div>
    </article>
  );
}

export function SignalsSection({ signals }: { signals: SignalView[] }) {
  return (
    <section className="section" aria-labelledby="signals-h">
      <ReportHead
        num={1}
        title="The five risk signals"
        subtitle="Each signal answers one question about the target's organization. Signals with thin data are shown but not scored."
      />
      {signals.length === 0 ? (
        <EmptyBox>No signals have been computed yet.</EmptyBox>
      ) : (
        <div className="signals">
          {signals.map((s) => (
            <SignalRow key={s.id} s={s} />
          ))}
        </div>
      )}
    </section>
  );
}
