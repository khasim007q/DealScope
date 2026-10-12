import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyBox, ErrorBox, Loading, ModeBadge, StatusPill } from "../components/ui";
import { formatDateTime, formatRelative } from "../lib/format";
import { useAsync, useDocumentTitle, useNow } from "../lib/hooks";

export function Cases() {
  useDocumentTitle("Cases");
  const { data, error, loading, reload } = useAsync(() => api.listCases());
  const now = useNow();

  const items = data ? [...data].sort((a, b) => b.updated_at.localeCompare(a.updated_at)) : [];

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
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Investigations</caption>
            <thead>
              <tr>
                <th scope="col">Target</th>
                <th scope="col">Status</th>
                <th scope="col">Risk result</th>
                <th scope="col">Data</th>
                <th scope="col">Last updated</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.case_id}>
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
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
