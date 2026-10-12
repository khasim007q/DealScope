import { Link } from "react-router-dom";
import { api } from "../api/client";
import { formatDate } from "../lib/format";
import { useAsync } from "../lib/hooks";

/** Recorded live runs that open without spending credits. Renders nothing when empty or on error. */
export function FeaturedCases() {
  const { data, error, loading } = useAsync(() => api.featured());
  if (loading || error || !data || data.length === 0) return null;

  return (
    <section className="card featured" aria-labelledby="featured-h">
      <h2 id="featured-h">See a finished live example</h2>
      <p className="muted small">
        These are real investigations that were run earlier and saved with the project. Opening one is instant and
        spends no credits.
      </p>
      <ul className="featured-list">
        {data.map((f) => (
          <li key={f.case_id}>
            <Link className="case-link" to={`/cases/${encodeURIComponent(f.case_id)}`}>
              {f.label}
            </Link>
            <p className="small">{f.description}</p>
            <p className="muted small">
              <span className="badge mode-live">Recorded live run</span>{" "}
              <time dateTime={f.recorded_at}>{formatDate(f.recorded_at)}</time>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
