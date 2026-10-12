import type { Assessment } from "../api/types";
import { formatPct } from "../lib/format";
import { Meter } from "./ui";

export function SummaryCard({ assessment, running }: { assessment: Assessment | null; running: boolean }) {
  if (!assessment) {
    return (
      <section className="card" aria-labelledby="summary-h">
        <h2 id="summary-h">Summary</h2>
        <p className="muted" style={{ marginBottom: 0 }}>
          {running ? "The summary appears once the agent has scored the first evidence." : "No summary was produced for this case."}
        </p>
      </section>
    );
  }
  const a = assessment;
  const scored = a.risk_score !== null;
  return (
    <section className="card" aria-labelledby="summary-h">
      <h2 id="summary-h" className="sr-only">
        Summary
      </h2>
      <div className="summary">
        <div className={`score-box tone-${a.risk_tone}`}>
          <div className="score-cap">Organizational risk</div>
          {scored ? (
            <>
              <div className="score-num" aria-label={`Risk score ${a.risk_score} out of 100`}>
                {a.risk_score}
                <small> / 100</small>
              </div>
              {a.risk_band ? <div className="score-band">{a.risk_band}</div> : null}
            </>
          ) : (
            <div className="score-none">Not enough evidence to score</div>
          )}
        </div>
        <div>
          <p className="headline">{a.headline}</p>
          <div className="meters">
            <Meter
              name="Coverage"
              valueText={formatPct(a.coverage_pct)}
              percent={a.coverage_pct}
              tone="info"
              sub={`${a.coverage_label}. How much of the needed evidence was found.`}
            />
            <Meter
              name="Confidence"
              valueText={`${a.confidence_label} (${Math.round(a.confidence)})`}
              percent={a.confidence}
              tone="info"
              sub="How reliable the evidence found is."
            />
          </div>
          <div className="infobox">
            <strong>How to read this</strong>
            <p>{a.explainer}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
