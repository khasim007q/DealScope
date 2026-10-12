import type { CreditsView, VerificationView } from "../api/types";
import { formatCredits, formatInt, formatRate } from "../lib/format";
import { CopyButton, SectionHead, StatusPill } from "./ui";

export function Stat({ k, v, hint }: { k: string; v: string; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-v">{v}</div>
      <div className="stat-k">{k}</div>
      {hint ? <div className="stat-k">{hint}</div> : null}
    </div>
  );
}

function CreditsCard({ credits }: { credits: CreditsView }) {
  return (
    <div className="card" style={{ margin: 0 }}>
      <h3>
        Credits{" "}
        {credits.simulated ? (
          <StatusPill tone="caution">Simulated - no real credits used</StatusPill>
        ) : null}
      </h3>
      <div className="stat-grid">
        <Stat k="Credit cap" v={formatCredits(credits.cap)} />
        <Stat k="Remaining under cap" v={formatCredits(credits.remaining)} />
        <Stat k="Estimated used" v={formatCredits(credits.estimated_used)} hint="Before the provider confirms" />
        <Stat
          k="Confirmed used"
          v={formatCredits(credits.actual_used)}
          hint={credits.simulated ? "Simulated" : "From provider responses"}
        />
        <Stat k="Held in reserve" v={formatCredits(credits.reserved)} hint="Set aside for in-flight calls" />
        <Stat
          k="Calls with unknown cost"
          v={formatInt(credits.unknown_calls)}
          hint={credits.unknown_calls > 0 ? "Cost could not be confirmed" : "All costs confirmed"}
        />
      </div>
    </div>
  );
}

function VerificationCard({ v }: { v: VerificationView | null }) {
  return (
    <div className="card" style={{ margin: 0 }}>
      <h3>Verification</h3>
      {v === null ? (
        <p className="muted">Verification results are not available yet.</p>
      ) : (
        <>
          <p className="muted small" style={{ marginTop: -4 }}>
            Every claim is checked against its cited evidence before it is published.
          </p>
          <div className="stat-grid">
            <Stat k="Published" v={formatInt(v.published)} />
            <Stat k="Verified" v={formatInt(v.verified)} />
            <Stat k="Verified with caveats" v={formatInt(v.with_caveats)} />
            <Stat k="Rejected" v={formatInt(v.rejected)} />
            <Stat k="Grounded in evidence" v={formatRate(v.grounded_rate)} />
          </div>
          {v.rejected_reasons.length > 0 ? (
            <>
              <h4 style={{ marginTop: 14 }}>Why claims were rejected</h4>
              <ul>
                {v.rejected_reasons.map((r, i) => (
                  <li key={i}>
                    {r.reason} <span className="muted">({r.count})</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <p className="small" style={{ marginTop: 10, marginBottom: 0 }}>
            {v.ai_draft_used
              ? "An AI-written draft was used, then verified claim by claim."
              : "The AI write-up was unavailable, so only rule-based findings are shown."}
          </p>
        </>
      )}
    </div>
  );
}

interface Props {
  credits: CreditsView;
  verification: VerificationView | null;
  llmModel: string | null;
  traceIds: string[];
  synthetic: boolean;
}

export function CostTrust({ credits, verification, llmModel, traceIds, synthetic }: Props) {
  return (
    <section className="section" aria-labelledby="cost-h">
      <SectionHead id="cost-h" title="Cost and trust" subtitle="What this run cost and how the claims were checked." />
      <div className="cols-2">
        <CreditsCard credits={credits} />
        <VerificationCard v={verification} />
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Run details</h3>
        <p style={{ marginBottom: 8 }}>
          <strong>Language model:</strong> {llmModel ?? "None used"}
        </p>
        <h4>Trace IDs</h4>
        {traceIds.length === 0 ? (
          <p className="muted small" style={{ marginBottom: 0 }}>
            {synthetic ? "Demo runs may not record traces." : "No traces were recorded for this run."}
          </p>
        ) : (
          <>
            <p className="muted small">Use these to look up the full agent trace in the tracing tool.</p>
            {traceIds.map((t) => (
              <div className="trace-row" key={t}>
                <span className="trace-id">{t}</span>
                <CopyButton text={t} label="Copy" />
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
