import { api } from "../api/client";
import type { EvidenceSummary } from "../api/types";
import { Dateline, EmptyBox, ErrorBox, Kicker, Loading, PageHeader, SectionHead, Stat, StatGrid } from "../components/ui";
import { formatCredits } from "../lib/format";
import { useAsync, useDocumentTitle } from "../lib/hooks";

function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <section className="section" aria-labelledby="notes-h">
      <h3 id="notes-h" className="kicker">
        Notes
      </h3>
      <ol className="footnotes">
        {notes.map((n, i) => (
          <li key={i}>{n}</li>
        ))}
      </ol>
    </section>
  );
}

function Crustdata({ d }: { d: EvidenceSummary["crustdata"] }) {
  const pctOf = (n: number, of: number) => (of > 0 ? Math.max(0, Math.min(100, (n / of) * 100)) : 0);
  const used = Math.max(0, d.actual_used);
  const remaining = Math.max(0, d.remaining);
  const usedPct = pctOf(d.actual_used, d.spendable);
  const segs = [
    { key: "reserve", label: "Reserve", value: d.reserve, cls: "seg-reserve" },
    { key: "used", label: "Used (confirmed)", value: used, cls: "seg-used" },
    { key: "remaining", label: "Remaining", value: remaining, cls: "seg-remaining" },
  ];
  const aria = `Credit split of ${formatCredits(d.total)} total: ${segs.map((s) => `${s.label} ${formatCredits(s.value)}`).join(", ")}`;
  return (
    <>
      <section className="section" aria-labelledby="crust-h">
        <SectionHead
          id="crust-h"
          title="Crustdata credit governance"
          subtitle="How the credit allowance is split, and what live investigations have actually used."
        />
        <StatGrid>
          <Stat label="Total credits" value={formatCredits(d.total)} />
          <Stat label="Reserve (never spent)" value={formatCredits(d.reserve)} />
          <Stat label="Spendable" value={formatCredits(d.spendable)} />
          <Stat label="Confirmed used" value={formatCredits(d.actual_used)} note="From provider responses" />
          <Stat label="Estimated used" value={formatCredits(d.estimated_used)} note="Before confirmation" />
          <Stat label="Remaining" value={formatCredits(d.remaining)} />
        </StatGrid>

        <figure className="split">
          <figcaption>
            <Kicker>Credit split</Kicker>
          </figcaption>
          <div className="split-bar" role="img" aria-label={aria}>
            {segs.map((s) => (
              <span key={s.key} className={`split-seg ${s.cls}`} style={{ width: `${pctOf(s.value, d.total)}%` }} />
            ))}
          </div>
          <ul className="split-legend">
            {segs.map((s) => (
              <li key={s.key}>
                <span className={`split-key ${s.cls}`} aria-hidden="true" />
                {s.label} <span className="num">{formatCredits(s.value)}</span>
              </li>
            ))}
          </ul>
          <p className="split-note">
            {usedPct.toFixed(0)}% of the spendable allowance has been used. The reserve is never available to the product.
          </p>
        </figure>
      </section>

      {d.prices.length > 0 ? (
        <section className="section" aria-labelledby="price-h">
          <SectionHead id="price-h" title="Price table" subtitle="Credits charged per data lookup." />
          <div className="table-wrap">
            <table className="price-table">
              <caption className="sr-only">Credits per endpoint</caption>
              <thead>
                <tr>
                  <th scope="col">Data lookup</th>
                  <th scope="col" className="num">
                    Credits
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.prices.map((p) => (
                  <tr key={p.endpoint}>
                    <td>{p.endpoint}</td>
                    <td className="num">{p.credits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <Notes notes={d.notes} />
    </>
  );
}

export function Evidence() {
  useDocumentTitle("Evidence");
  const { data, error, loading, reload } = useAsync(() => api.evidenceSummary());

  return (
    <>
      <PageHeader
        kicker="Methodology appendix"
        title="Evidence"
        dek="How the Crustdata credit allowance is governed, and what live investigations have actually used."
      >
        <Dateline items={["Provider: Crustdata", "Unit: credits"]} />
      </PageHeader>

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
