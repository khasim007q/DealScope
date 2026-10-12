import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { EntireCommitCheckpoint, EvalRow, EvidenceFile, EvidenceSummary, EvidenceTrace, NeatlogsRun, Tone } from "../api/types";
import { Stat } from "../components/CostTrust";
import { TraceWaterfall } from "../components/TraceWaterfall";
import { CopyButton, Disclosure, EmptyBox, ErrorBox, Icon, Loading, Meter, SectionHead } from "../components/ui";
import { evidenceUrl, formatCredits, formatDateTime, formatInt, plural } from "../lib/format";
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

function RecordedFlows({ traces }: { traces: EvidenceTrace[] }) {
  const [selected, setSelected] = useState(0);
  if (traces.length === 0) {
    return (
      <EmptyBox>
        No recorded agent flows are available yet. The neatlogs dashboard screenshots below show the same runs.
      </EmptyBox>
    );
  }
  const idx = Math.min(selected, traces.length - 1);
  const current = traces[idx];
  return (
    <div className="card">
      <div className="tabs" role="tablist" aria-label="Recorded agent flows">
        {traces.map((t, i) => (
          <button
            key={`${t.trace.trace_id}-${i}`}
            type="button"
            role="tab"
            id={`flow-tab-${i}`}
            className="tab"
            aria-selected={i === idx}
            aria-controls="flow-tabpanel"
            tabIndex={i === idx ? 0 : -1}
            onClick={() => setSelected(i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div id="flow-tabpanel" role="tabpanel" aria-labelledby={`flow-tab-${idx}`}>
        {current.description ? <p className="tw-desc">{current.description}</p> : null}
        <TraceWaterfall key={`${current.trace.trace_id}-${idx}`} trace={current.trace} />
      </div>
    </div>
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
      <h3>Recorded agent flows</h3>
      <p className="muted small">
        Real traces of the agent, recorded locally from the same spans that are exported to neatlogs. The trace ids match
        the neatlogs dashboard.
      </p>
      <RecordedFlows traces={d.traces ?? []} />
      <h3 style={{ marginTop: 22 }}>Traced runs</h3>
      <RunsTable runs={d.runs} />
      <h3 style={{ marginTop: 22 }}>Improvement experiment</h3>
      <p className="muted small">The same scenarios run with the original and the improved drafting step.</p>
      <EvalTable rows={d.eval_rows} reading={d.eval_reading} />
      <Disclosure summary="neatlogs dashboard screenshots (independent proof from neatlogs)">
        <Screenshots items={d.screenshots} />
      </Disclosure>
    </section>
  );
}

function DiffBar({ ins, del, max }: { ins: number; del: number; max: number }) {
  const total = ins + del;
  const widthPct = max > 0 ? Math.max(6, (total / max) * 100) : 0;
  const insPct = total > 0 ? (ins / total) * 100 : 0;
  return (
    <span className="diff-bar" aria-hidden="true">
      <span className="diff-bar-inner" style={{ width: `${widthPct}%` }}>
        <span className="diff-ins" style={{ width: `${insPct}%` }} />
        <span className="diff-del" style={{ width: `${100 - insPct}%` }} />
      </span>
    </span>
  );
}

function FlowNode({ c }: { c: EntireCommitCheckpoint }) {
  const maxChange = c.files.reduce((m, f) => Math.max(m, f.insertions + f.deletions), 0);
  return (
    <li>
      <span className="flow-dot" aria-hidden="true" />
      <div className="flow-top">
        <time className="flow-date" dateTime={c.date}>
          {formatDateTime(c.date)}
        </time>
        <span className="trace-id" title={c.commit}>
          {c.commit.slice(0, 7)}
        </span>
      </div>
      <p className="flow-subject">{c.subject}</p>
      <div className="flow-meta">
        <span className="muted small">Checkpoint</span>
        <span className="trace-id">{c.checkpoint}</span>
        <CopyButton text={c.checkpoint} label="Copy" />
      </div>
      <p className="flow-diff small">
        {formatInt(c.files_changed)} {plural(c.files_changed, "file")},{" "}
        <span className="pos">+{formatInt(c.insertions)}</span> / <span className="neg">-{formatInt(c.deletions)}</span>
      </p>
      {c.files.length > 0 ? (
        <Disclosure summary={`Show ${c.files.length} largest ${plural(c.files.length, "change")}`}>
          <ul className="flow-files">
            {c.files.map((f) => (
              <li key={f.path}>
                <span className="mono flow-path">{f.path}</span>
                <span className="flow-counts small">
                  <span className="pos">+{formatInt(f.insertions)}</span> <span className="neg">-{formatInt(f.deletions)}</span>
                </span>
                <DiffBar ins={f.insertions} del={f.deletions} max={maxChange} />
              </li>
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </li>
  );
}

function SessionCard({ s }: { s: NonNullable<EvidenceSummary["entire"]["session"]> }) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="stat-grid">
        <Stat k="Agent" v={s.agent} />
        <Stat k="Checkpoints" v={formatInt(s.checkpoints_total)} />
        <Stat k="First checkpoint" v={formatDateTime(s.first)} />
        <Stat k="Latest checkpoint" v={formatDateTime(s.last)} />
      </div>
      <div className="trace-row" style={{ marginTop: 12 }}>
        <span className="muted small">Session id</span>
        <span className="trace-id">{s.session_id}</span>
        <CopyButton text={s.session_id} label="Copy" />
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        Every commit below is linked to the Claude Code session that produced it.
      </p>
    </div>
  );
}

function Entire({ d }: { d: EvidenceSummary["entire"] }) {
  const flow = d.flow ?? [];
  return (
    <section className="section" aria-labelledby="entire-h">
      <SectionHead
        id="entire-h"
        title="Entire (coding-session checkpoints)"
        subtitle="Each commit is paired with a checkpoint of the coding session that produced it."
      />
      {d.session ? <SessionCard s={d.session} /> : null}
      <h3>Entire commit flow</h3>
      {flow.length > 0 ? (
        <ol className="flow">
          {flow.map((c) => (
            <FlowNode key={`${c.commit}-${c.checkpoint}`} c={c} />
          ))}
        </ol>
      ) : d.checkpoints.length === 0 ? (
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
      {d.screenshots.length > 0 ? (
        <Disclosure summary="Entire session timeline screenshot (backup)">
          <Screenshots items={d.screenshots} />
        </Disclosure>
      ) : null}
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
