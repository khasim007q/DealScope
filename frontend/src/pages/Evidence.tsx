import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { EvalRow, EvidenceFile, EvidenceSummary, NeatlogsRun, Tone } from "../api/types";
import { Stat } from "../components/CostTrust";
import { CopyButton, EmptyBox, ErrorBox, Icon, Loading, Meter, SectionHead } from "../components/ui";
import { evidenceUrl, formatCredits, formatInt } from "../lib/format";
import { useAsync, useDocumentTitle } from "../lib/hooks";

const KIND: Record<NeatlogsRun["kind"], { label: string; tone: Tone }> = {
  live: { label: "Live run", tone: "info" },
  failure: { label: "Failure drill", tone: "caution" },
  eval: { label: "Experiment", tone: "neutral" },
};

function TraceId({ id }: { id: string }) {
  return (
    <div className="trace-row">
      <span className="trace-id">{id}</span>
      <CopyButton text={id} label="Copy" />
    </div>
  );
}

function PathText({ path }: { path: string }) {
  return (
    <div className="trace-row">
      <span className="trace-id">{path}</span>
      <CopyButton text={path} label="Copy path" />
    </div>
  );
}

function RunsTable({ runs }: { runs: NeatlogsRun[] }) {
  if (runs.length === 0) return <EmptyBox>No traced runs are recorded yet.</EmptyBox>;
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Traced runs</caption>
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Kind</th>
            <th scope="col">What happened</th>
            <th scope="col">Trace IDs</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r, i) => {
            const k = KIND[r.kind];
            return (
              <tr key={`${r.label}-${i}`}>
                <td>
                  {r.case_id ? (
                    <Link className="case-link" to={`/cases/${encodeURIComponent(r.case_id)}`}>
                      {r.label}
                    </Link>
                  ) : (
                    r.label
                  )}
                </td>
                <td>
                  <span className={`badge tone-${k.tone}`}>{k.label}</span>
                </td>
                <td>{r.summary}</td>
                <td>
                  {r.trace_ids.length === 0 ? (
                    <span className="muted">None recorded</span>
                  ) : (
                    r.trace_ids.map((t) => <TraceId key={t} id={t} />)
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface ScenarioGroup {
  scenario: string;
  baseline?: EvalRow;
  improved?: EvalRow;
}

function groupByScenario(rows: EvalRow[]): ScenarioGroup[] {
  const map = new Map<string, ScenarioGroup>();
  for (const r of rows) {
    const g = map.get(r.scenario) ?? { scenario: r.scenario };
    g[r.variant] = r;
    map.set(r.scenario, g);
  }
  return Array.from(map.values());
}

const METRICS: { label: string; get: (r: EvalRow) => number }[] = [
  { label: "Draft claims", get: (r) => r.draft_claims },
  { label: "Rejected", get: (r) => r.draft_rejected },
  { label: "Verified", get: (r) => r.draft_verified },
  { label: "Verified with caveats", get: (r) => r.draft_with_caveats },
  { label: "Published", get: (r) => r.published },
  { label: "Tool calls", get: (r) => r.tool_calls },
];

function ScenarioRows({ g }: { g: ScenarioGroup }) {
  return (
    <>
      {METRICS.map((m, i) => (
        <tr key={m.label}>
          {i === 0 ? (
            <th scope="rowgroup" rowSpan={METRICS.length + 1} style={{ background: "var(--surface-2)" }}>
              Scenario {g.scenario}
            </th>
          ) : null}
          <td>{m.label}</td>
          <td className="num">{g.baseline ? formatInt(m.get(g.baseline)) : "n/a"}</td>
          <td className="num">{g.improved ? formatInt(m.get(g.improved)) : "n/a"}</td>
        </tr>
      ))}
      <tr>
        <td>Trace ID</td>
        <td>{g.baseline?.trace_id ? <TraceId id={g.baseline.trace_id} /> : <span className="muted">n/a</span>}</td>
        <td>{g.improved?.trace_id ? <TraceId id={g.improved.trace_id} /> : <span className="muted">n/a</span>}</td>
      </tr>
    </>
  );
}

function EvalTable({ rows, reading }: { rows: EvalRow[]; reading: string }) {
  if (rows.length === 0) return <EmptyBox>No improvement experiment results are recorded yet.</EmptyBox>;
  return (
    <>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Baseline compared with improved, by scenario</caption>
          <thead>
            <tr>
              <th scope="col">Scenario</th>
              <th scope="col">Measure</th>
              <th scope="col" className="num">
                Baseline
              </th>
              <th scope="col" className="num">
                Improved
              </th>
            </tr>
          </thead>
          <tbody>
            {groupByScenario(rows).map((g) => (
              <ScenarioRows key={g.scenario} g={g} />
            ))}
          </tbody>
        </table>
      </div>
      {reading ? (
        <div className="infobox">
          <strong>How to read this</strong>
          <p>{reading}</p>
        </div>
      ) : null}
    </>
  );
}

function Screenshots({ items }: { items: EvidenceFile[] }) {
  if (items.length === 0) return <EmptyBox>No screenshots are recorded yet.</EmptyBox>;
  return (
    <ul className="shot-grid">
      {items.map((s) => (
        <li key={s.path}>
          <figure className="shot">
            <a
              href={evidenceUrl(s.path)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${s.label} (opens full size in a new tab)`}
            >
              <img src={evidenceUrl(s.path)} alt={s.label} loading="lazy" />
            </a>
            <figcaption>{s.label}</figcaption>
          </figure>
        </li>
      ))}
    </ul>
  );
}

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

function Neatlogs({ d }: { d: EvidenceSummary["neatlogs"] }) {
  return (
    <section className="section" aria-labelledby="neat-h">
      <SectionHead
        id="neat-h"
        title="neatlogs (run tracing)"
        subtitle="Every agent run is traced. These are the runs behind the claims in this project."
      />
      <RunsTable runs={d.runs} />
      <h3 style={{ marginTop: 22 }}>Improvement experiment</h3>
      <p className="muted small">The same scenarios run with the original and the improved drafting step.</p>
      <EvalTable rows={d.eval_rows} reading={d.eval_reading} />
      <h3 style={{ marginTop: 22 }}>Screenshots</h3>
      <Screenshots items={d.screenshots} />
    </section>
  );
}

function Entire({ d }: { d: EvidenceSummary["entire"] }) {
  return (
    <section className="section" aria-labelledby="entire-h">
      <SectionHead
        id="entire-h"
        title="Entire (coding-session checkpoints)"
        subtitle="Each commit is paired with a checkpoint of the coding session that produced it."
      />
      {d.checkpoints.length === 0 ? (
        <EmptyBox>No checkpoints are recorded yet.</EmptyBox>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Commits and checkpoints</caption>
            <thead>
              <tr>
                <th scope="col">Commit</th>
                <th scope="col">Change</th>
                <th scope="col">Checkpoint</th>
              </tr>
            </thead>
            <tbody>
              {d.checkpoints.map((c) => (
                <tr key={`${c.commit}-${c.checkpoint}`}>
                  <td>
                    <span className="trace-id" title={c.commit}>
                      {c.commit.slice(0, 7)}
                    </span>
                  </td>
                  <td>{c.subject}</td>
                  <td>
                    <TraceId id={c.checkpoint} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.transcript_path ? (
        <div style={{ marginTop: 14 }}>
          <h3>Session transcript</h3>
          <p className="muted small">The transcript lives in the repository. Open it from this path.</p>
          <PathText path={d.transcript_path} />
        </div>
      ) : null}
      <NoteList notes={d.notes} />
    </section>
  );
}

function FileLink({ f }: { f: EvidenceFile }) {
  const isPdf = f.path.toLowerCase().endsWith(".pdf");
  return (
    <li>
      <strong>{f.label}</strong>
      {isPdf ? (
        <div className="trace-row">
          <a className="btn small" href={evidenceUrl(f.path)} target="_blank" rel="noopener noreferrer">
            <Icon name="external" size={14} />
            Open PDF
          </a>
        </div>
      ) : (
        <PathText path={f.path} />
      )}
    </li>
  );
}

function Cfo({ d }: { d: EvidenceSummary["cfo"] }) {
  return (
    <section className="section" aria-labelledby="cfo-h">
      <SectionHead
        id="cfo-h"
        title="cfo.ai (business plan)"
        subtitle="Scenario modelling for the business behind the product."
      />
      {d.scenarios.length === 0 ? (
        <EmptyBox>No business-plan scenarios are recorded yet.</EmptyBox>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Business-plan scenarios</caption>
            <thead>
              <tr>
                <th scope="col">Scenario</th>
                <th scope="col" className="num">
                  Revenue
                </th>
                <th scope="col" className="num">
                  Audits
                </th>
                <th scope="col" className="num">
                  Gross margin
                </th>
                <th scope="col" className="num">
                  Contribution margin
                </th>
                <th scope="col" className="num">
                  Peak funding need
                </th>
              </tr>
            </thead>
            <tbody>
              {d.scenarios.map((s) => (
                <tr key={s.name}>
                  <td>
                    <strong>{s.name}</strong>
                  </td>
                  <td className="num">{s.revenue}</td>
                  <td className="num">{s.audits}</td>
                  <td className="num">{s.gross_margin}</td>
                  <td className="num">{s.contribution_margin}</td>
                  <td className="num">{s.peak_funding_need}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.unit_cost ? (
        <p style={{ marginTop: 14 }}>
          <strong>Unit cost:</strong> {d.unit_cost}
        </p>
      ) : null}
      {d.pricing.length > 0 ? (
        <>
          <h3>Pricing</h3>
          <ul>
            {d.pricing.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </>
      ) : null}
      <NoteList notes={d.notes} />
      {d.files.length > 0 ? (
        <>
          <h3 style={{ marginTop: 18 }}>Files</h3>
          <ul className="file-list">
            {d.files.map((f) => (
              <FileLink key={f.path} f={f} />
            ))}
          </ul>
        </>
      ) : null}
    </section>
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
  useDocumentTitle("Partner evidence");
  const { data, error, loading, reload } = useAsync(() => api.evidenceSummary());

  return (
    <>
      <div className="page-head">
        <h1>Partner evidence</h1>
        <p>
          Proof of how DealScope was built and run: traced agent runs, coding-session checkpoints, the business plan and
          how credits are governed.
        </p>
      </div>

      {loading ? (
        <Loading label="Loading evidence..." />
      ) : error ? (
        <ErrorBox title="Could not load the evidence summary" message={error} onRetry={reload} />
      ) : !data ? (
        <EmptyBox>No evidence has been recorded yet.</EmptyBox>
      ) : (
        <>
          <Neatlogs d={data.neatlogs} />
          <Entire d={data.entire} />
          <Cfo d={data.cfo} />
          <Crustdata d={data.crustdata} />
        </>
      )}
    </>
  );
}
