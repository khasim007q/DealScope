import type { IdentityResult, Tone } from "../api/types";
import { StatusPill } from "./ui";

const STATUS_LABEL: Record<IdentityResult["status"], string> = {
  ok: "Matched",
  ambiguous: "Ambiguous",
  mismatch: "Mismatch",
  no_match: "No match",
  error: "Check failed",
};

const STATUS_TONE: Record<IdentityResult["status"], Tone> = {
  ok: "good",
  ambiguous: "caution",
  mismatch: "bad",
  no_match: "bad",
  error: "bad",
};

interface Props {
  results: IdentityResult[];
  onUseDomain: (from: string, to: string) => void;
  disabled?: boolean;
}

export function IdentityTable({ results, onUseDomain, disabled }: Props) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Company identity check results</caption>
        <thead>
          <tr>
            <th scope="col">Domain</th>
            <th scope="col">Resolved company</th>
            <th scope="col">Result</th>
            <th scope="col">What we found</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => {
            const suggestions = r.candidates.filter(
              (c) => c.primary_domain && c.primary_domain.toLowerCase() !== r.domain.toLowerCase(),
            );
            return (
              <tr key={r.domain}>
                <td>
                  <strong>{r.domain}</strong>
                </td>
                <td>{r.resolved_name ?? <span className="muted">Not resolved</span>}</td>
                <td>
                  <StatusPill tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</StatusPill>
                </td>
                <td>
                  <div>{r.message}</div>
                  {!r.ok && suggestions.length > 0 ? (
                    <div style={{ marginTop: 8 }}>
                      <div className="small muted">Did you mean one of these?</div>
                      <ul style={{ listStyle: "none", padding: 0, margin: "4px 0 0" }}>
                        {suggestions.slice(0, 5).map((c) => (
                          <li key={`${c.primary_domain}-${c.name}`} style={{ marginBottom: 6 }}>
                            <button
                              type="button"
                              className="btn small"
                              disabled={disabled}
                              onClick={() => c.primary_domain && onUseDomain(r.domain, c.primary_domain)}
                            >
                              Use {c.primary_domain}
                            </button>{" "}
                            <span className="small muted">
                              {c.name ?? "Unnamed company"}
                              {c.employee_count_range ? `, ${c.employee_count_range} employees` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
