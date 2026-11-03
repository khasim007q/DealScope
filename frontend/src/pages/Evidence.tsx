import { api } from "../api/client";
import type { EvidenceSummary } from "../api/types";
import { Stat } from "../components/CostTrust";
import { EmptyBox, ErrorBox, Loading, Meter, SectionHead } from "../components/ui";
import { formatCredits } from "../lib/format";
import { useAsync, useDocumentTitle } from "../lib/hooks";

function NoteList({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <ul style={{ marginTop: 12 }}>
      {notes.map((n, i) => (
        <li key={i}>{n}</li>
      ))}
    </ul>
  );
}

function Crustdata({ d }: { d: EvidenceSummary["crustdata"] }) {
  const pctOf = (n: number, of: number) => (of > 0 ? (n / of) * 100 : 0);
  const usedPct = pctOf(d.actual_used, d.spendable);
  return (
    <section className="section" aria-labelledby="crust-h">
      <SectionHead
        id="crust-h"
        title="Crustdata (credit governance)"
        subtitle="How the credit allowance is split, and what live investigations have actually used."
      />
      <div className="card">
        <div className="stat-grid">
          <Stat k="Total credits" v={formatCredits(d.total)} />
          <Stat k="Reserve (never spent)" v={formatCredits(d.reserve)} />
          <Stat k="Spendable" v={formatCredits(d.spendable)} />
          <Stat k="Confirmed actual used" v={formatCredits(d.actual_used)} hint="From provider responses" />
          <Stat k="Estimated used" v={formatCredits(d.estimated_used)} hint="Before confirmation" />
          <Stat k="Remaining" v={formatCredits(d.remaining)} />
        </div>
        <div className="meters" style={{ marginTop: 18 }}>
          <Meter
            name="Reserve held back"
            valueText={`${formatCredits(d.reserve)} of ${formatCredits(d.total)}`}
            percent={pctOf(d.reserve, d.total)}
            tone="info"
            sub="Never available to the product."
          />
          <Meter
            name="Spendable used (confirmed)"
            valueText={`${formatCredits(d.actual_used)} of ${formatCredits(d.spendable)}`}
            percent={usedPct}
            tone={usedPct >= 80 ? "caution" : "good"}
            sub={`${formatCredits(d.remaining)} remaining.`}
          />
        </div>
      </div>
      {d.prices.length > 0 ? (
        <>
          <h3 style={{ marginTop: 18 }}>Price table</h3>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Credits per endpoint</caption>
              <thead>
                <tr>
                  <th scope="col">Data lookup</th>
                  <th scope="col">Credits</th>
                </tr>
              </thead>
              <tbody>
                {d.prices.map((p) => (
                  <tr key={p.endpoint}>
                    <td>{p.endpoint}</td>
                    <td>{p.credits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      <NoteList notes={d.notes} />
    </section>
  );
}

export function Evidence() {
  useDocumentTitle("Evidence");
  const { data, error, loading, reload } = useAsync(() => api.evidenceSummary());

  return (
    <>
      <div className="page-head">
        <h1>Evidence</h1>
        <p>How the Crustdata credit allowance is governed, and what live investigations have actually used.</p>
      </div>

      {loading ? (
        <Loading label="Loading evidence..." />
      ) : error ? (
        <ErrorBox title="Could not load the evidence summary" message={error} onRetry={reload} />
      ) : !data ? (
        <EmptyBox>No evidence has been recorded yet.</EmptyBox>
      ) : (
        <Crustdata d={data.crustdata} />
      )}
    </>
  );
}
