import type { Assessment } from "../api/types";
import { formatPct } from "../lib/format";
import { Stat, StatGrid } from "./ui";

export function SummaryCard({ assessment, running }: { assessment: Assessment | null; running: boolean }) {
  if (!assessment) {
    return (
      <section className="verdict" aria-labelledby="summary-h">
        <h2 id="summary-h" className="verdict-kicker">
          Verdict
        </h2>
        <p className="muted" style={{ marginBottom: 0 }}>
          {running ? "The summary appears once the agent has scored the first evidence." : "No summary was produced for this case."}
        </p>
      </section>
    );
  }
  const a = assessment;
  const scored = a.risk_score !== null;
  return (
    <section className="verdict" aria-labelledby="summary-h">
      <h2 id="summary-h" className="verdict-kicker">
        Verdict
      </h2>
      <div className="verdict-grid">
        <div className={`verdict-fig tone-${a.risk_tone}`}>
          <div className="verdict-cap">Organizational risk</div>
          {scored ? (
            <>
              <div className="verdict-num" aria-label={`Risk score ${a.risk_score} out of 100`}>
                {a.risk_score}
                <small>/100</small>
              </div>
              {a.risk_band ? <div className="verdict-band">{a.risk_band}</div> : null}
            </>
          ) : (
            <div className="verdict-none">Not enough evidence to score</div>
          )}
        </div>
        <div>
          <p className="verdict-lede">{a.headline}</p>
          <StatGrid>
            <Stat value={formatPct(a.coverage_pct)} label="Coverage" note={`${a.coverage_label}. How much of the needed evidence was found.`} />
            <Stat
              value={a.confidence_label}
              unit={`(${Math.round(a.confidence)})`}
              label="Confidence"
              note="How reliable the evidence found is."
            />
          </StatGrid>
          <p className="verdict-how">
            <strong>How to read this.</strong> {a.explainer}
          </p>
        </div>
      </div>
    </section>
  );
}
