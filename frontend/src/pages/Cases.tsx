import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { FeaturedCases } from "../components/FeaturedCases";
import { EmptyBox, ErrorBox, Loading, ModeBadge, StatusPill } from "../components/ui";
import { formatDateTime, formatRelative } from "../lib/format";
import { useAsync, useDocumentTitle, useNow } from "../lib/hooks";

export function Cases() {
  useDocumentTitle("Cases");
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
      <div className="page-head">
        <h1>Cases</h1>
        <p>Every investigation that has been run, newest first. Open one to see its summary, evidence and memo.</p>
      </div>

      {loading ? (
        <Loading label="Loading cases..." />
      ) : error ? (
        <ErrorBox title="Could not load cases" message={error} onRetry={reload} />
      ) : items.length === 0 ? (
        <EmptyBox>
          No investigations yet. <Link to="/">Start your first investigation</Link>.
        </EmptyBox>
      ) : (
        <>
          <div className="btn-row" style={{ marginBottom: 10 }}>
            <button type="button" className="btn" onClick={compare} disabled={selected.length !== 2}>
              Compare selected
            </button>
            <span className="small muted" aria-live="polite">
              {selected.length === 2
                ? "Two cases selected."
                : selected.length === 1
                  ? "Select one more case to compare."
                  : "Tick two cases to compare them side by side."}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Investigations</caption>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">Select to compare</span>
                  </th>
                  <th scope="col">Target</th>
                  <th scope="col">Status</th>
                  <th scope="col">Risk result</th>
                  <th scope="col">Data</th>
                  <th scope="col">Last updated</th>
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
                      </td>
                      <td>
                        <StatusPill tone={c.tone}>{c.status_label}</StatusPill>
                      </td>
                      <td>{c.risk_label}</td>
                      <td>
                        <ModeBadge mode={c.mode} />
                      </td>
                      <td>
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
