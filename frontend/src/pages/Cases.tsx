import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { FeaturedCases } from "../components/FeaturedCases";
import { ErrorBox, Loading, PageHeader, StatusPill } from "../components/ui";
import { formatDateTime, formatRelative, verdictWord } from "../lib/format";
import { useAsync, useDocumentTitle, useNow } from "../lib/hooks";

export function Cases() {
  useDocumentTitle("History");
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(() => api.listCases());
  const now = useNow();
  const [selected, setSelected] = useState<string[]>([]);

  const items = data ? [...data].sort((a, b) => b.updated_at.localeCompare(a.updated_at)) : [];

  const toggle = (id: string) =>
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  const compare = () => {
    if (selected.length !== 2) return;
    const [a, b] = selected;
    navigate(`/compare?a=${encodeURIComponent(a as string)}&b=${encodeURIComponent(b as string)}`);
  };

  return (
    <>
      <PageHeader title="History" dek="Every search you have run, newest first." />

      {loading ? (
        <Loading label="Loading history..." />
      ) : error ? (
        <ErrorBox title="Could not load history" message={error} onRetry={reload} />
      ) : items.length === 0 ? (
        <div className="index-empty">
          <p className="index-empty-title">Nothing here yet.</p>
          <p>
            <Link to="/">Search for a company</Link> to run your first analysis.
          </p>
        </div>
      ) : (
        <>
          {items.length > 1 ? (
            <div className="btn-row index-tools">
              <button type="button" className="btn" onClick={compare} disabled={selected.length !== 2}>
                Compare two
              </button>
              <span className="small muted" aria-live="polite">
                {selected.length === 2
                  ? "Two selected."
                  : selected.length === 1
                    ? "Tick one more to compare."
                    : "Tick two rows to compare them side by side."}
              </span>
            </div>
          ) : null}
          <div className="table-wrap">
            <table className="index-table">
              <caption className="sr-only">Searches</caption>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">Select to compare</span>
                  </th>
                  <th scope="col">Company</th>
                  <th scope="col">Verdict</th>
                  <th scope="col">Date</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => {
                  const checked = selected.includes(c.case_id);
                  return (
                    <tr key={c.case_id}>
                      <td>
                        <input
                          type="checkbox"
                          className="row-check"
                          checked={checked}
                          disabled={!checked && selected.length >= 2}
                          onChange={() => toggle(c.case_id)}
                          aria-label={`Select ${c.target} to compare`}
                        />
                      </td>
                      <td>
                        <Link className="case-link" to={`/cases/${encodeURIComponent(c.case_id)}`}>
                          {c.target}
                        </Link>
                        {c.mode === "synthetic" ? <span className="demo-tag">Demo</span> : null}
                      </td>
                      <td>
                        <StatusPill tone={c.tone}>{c.status_label === "Complete" ? verdictWord(c.risk_label) : c.status_label}</StatusPill>
                      </td>
                      <td className="index-date">
                        <time dateTime={c.updated_at} title={formatDateTime(c.updated_at)}>
                          {formatRelative(c.updated_at, now)}
                        </time>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <FeaturedCases />
    </>
  );
}
