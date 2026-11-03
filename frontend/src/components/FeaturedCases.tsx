import { Link } from "react-router-dom";
import { api } from "../api/client";
import { formatDate } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { Kicker } from "./ui";

/** Recorded live runs that open without spending credits, shown as a short "recent notes" list. Renders nothing when empty or on error. */
export function FeaturedCases() {
  const { data, error, loading } = useAsync(() => api.featured());
  if (loading || error || !data || data.length === 0) return null;

  return (
    <section className="notes" aria-labelledby="featured-h">
      <Kicker accent>Recent notes</Kicker>
      <h2 id="featured-h">See a finished live example</h2>
      <p className="notes-lede">
        Real investigations that were run earlier and saved with the project. Opening one is instant and spends no
        credits.
      </p>
      <ul className="notes-list">
        {data.map((f) => (
          <li key={f.case_id}>
            <Link className="case-link notes-title" to={`/cases/${encodeURIComponent(f.case_id)}`}>
              {f.label}
            </Link>
            <p className="notes-desc">{f.description}</p>
            <p className="notes-meta">
              <span className="badge mode-live">Recorded live run</span>
              <time dateTime={f.recorded_at}>{formatDate(f.recorded_at)}</time>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
