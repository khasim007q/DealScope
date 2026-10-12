import type { SignalView } from "../api/types";
import { formatPct } from "../lib/format";
import { Disclosure, EmptyBox, SectionHead, StatusPill } from "./ui";

function SignalCard({ s }: { s: SignalView }) {
  const hasScore = s.scored && s.score !== null;
  const pct = hasScore ? Math.max(0, Math.min(100, s.score as number)) : 0;
  return (
    <article className={`card signal tone-${s.tone}`} aria-labelledby={`sig-${s.id}`}>
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
      <div className="kv">
        {hasScore && s.band ? <span>Band: {s.band}</span> : null}
        <span>Weight: {formatPct(s.weight_pct)}</span>
        <span>Confidence: {Math.round(s.confidence)}</span>
      </div>

      <p className="finding-text-plain" style={{ fontWeight: 500 }}>
        {s.finding}
      </p>
      <h4>Why it matters</h4>
      <p style={{ marginBottom: 4 }}>{s.why_it_matters}</p>
      {s.limitations.length > 0 ? (
        <>
          <h4>Limitations</h4>
          <ul className="lim">
            {s.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </>
      ) : null}

      <div style={{ marginTop: "auto" }}>
        <Disclosure summary="Technical details">
          <dl className="tech-list" style={{ margin: 0 }}>
            <dt>State</dt>
            <dd style={{ margin: "0 0 6px" }}>{s.technical.state}</dd>
            <dt>Reason codes</dt>
            <dd style={{ margin: 0 }}>{s.technical.reason_codes.length > 0 ? s.technical.reason_codes.join(", ") : "none"}</dd>
          </dl>
        </Disclosure>
      </div>
    </article>
  );
}

export function SignalsSection({ signals }: { signals: SignalView[] }) {
  return (
    <section className="section" aria-labelledby="signals-h">
      <SectionHead
        id="signals-h"
        title="The five risk signals"
        subtitle="Each signal answers one question about the target's organization. Signals with thin data are shown but not scored."
      />
      {signals.length === 0 ? (
        <EmptyBox>No signals have been computed yet.</EmptyBox>
      ) : (
        <div className="signals">
          {signals.map((s) => (
            <SignalCard key={s.id} s={s} />
          ))}
        </div>
      )}
    </section>
  );
}
