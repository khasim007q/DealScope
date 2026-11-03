import type { ReactNode } from "react";
import type { CreditsView, VerificationView } from "../api/types";
import { formatCredits, formatInt, formatRate } from "../lib/format";
import { CopyButton, StatusPill } from "./ui";
import { ReportHead } from "./ReportHead";

interface Fig {
  k: string;
  v: string;
  note?: string;
}

/** Compact two-or-three column table of labelled figures. */
function FigTable({ caption, rows }: { caption: string; rows: Fig[] }) {
  return (
    <div className="table-wrap figs">
      <table>
        <caption className="sr-only">{caption}</caption>
        <tbody>
          {rows.map((r) => (
            <tr key={r.k}>
              <th scope="row">{r.k}</th>
              <td className="num">{r.v}</td>
              <td className="fig-note">{r.note ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CreditsBlock({ credits }: { credits: CreditsView }) {
  return (
    <div>
      <h3 className="fig-h">
        Credits{" "}
        {credits.simulated ? <StatusPill tone="caution">Simulated - no real credits used</StatusPill> : null}
      </h3>
      <FigTable
        caption="Credit usage for this run"
        rows={[
          { k: "Credit cap", v: formatCredits(credits.cap) },
          { k: "Remaining under cap", v: formatCredits(credits.remaining) },
          { k: "Estimated used", v: formatCredits(credits.estimated_used), note: "Before the provider confirms" },
          {
            k: "Confirmed used",
            v: formatCredits(credits.actual_used),
            note: credits.simulated ? "Simulated" : "From provider responses",
          },
          { k: "Held in reserve", v: formatCredits(credits.reserved), note: "Set aside for in-flight calls" },
          {
            k: "Calls with unknown cost",
            v: formatInt(credits.unknown_calls),
            note: credits.unknown_calls > 0 ? "Cost could not be confirmed" : "All costs confirmed",
          },
        ]}
      />
    </div>
  );
}

function VerificationBlock({ v }: { v: VerificationView | null }) {
  return (
    <div>
      <h3 className="fig-h">Verification</h3>
      {v === null ? (
        <p className="muted">Verification results are not available yet.</p>
      ) : (
        <>
          <p className="muted small">Every claim is checked against its cited evidence before it is published.</p>
          <FigTable
            caption="Claim verification results"
            rows={[
              { k: "Published", v: formatInt(v.published) },
              { k: "Verified", v: formatInt(v.verified) },
              { k: "Verified with caveats", v: formatInt(v.with_caveats) },
              { k: "Rejected", v: formatInt(v.rejected) },
              { k: "Grounded in evidence", v: formatRate(v.grounded_rate) },
            ]}
          />
          {v.rejected_reasons.length > 0 ? (
            <>
              <h4 className="fig-sub">Why claims were rejected</h4>
              <ul>
                {v.rejected_reasons.map((r, i) => (
                  <li key={i}>
                    {r.reason} <span className="muted">({r.count})</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <p className="small fig-foot">
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
  /** Optional lead-in content (the step-by-step investigation log) shown before the figures. */
  children?: ReactNode;
}

export function CostTrust({ credits, verification, llmModel, traceIds, synthetic, children }: Props) {
  return (
    <section className="section" aria-labelledby="cost-h">
      <ReportHead num={5} title="Method and cost" subtitle="How the agent investigated, what this run cost and how the claims were checked." />
      {children}
      <div className="cols-2 fig-cols">
        <CreditsBlock credits={credits} />
        <VerificationBlock v={verification} />
      </div>
      <div className="run-details">
        <h3 className="fig-h">Run details</h3>
        <p>
          <strong>Language model:</strong> {llmModel ?? "None used"}
        </p>
        <h4 className="fig-sub">Trace IDs</h4>
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
