import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseView, SignalView } from "../api/types";
import { Banner, Disclosure, EmptyBox, ErrorBox, Loading, ModeBadge, PageHeader, StatusPill } from "../components/ui";
import { formatCredits, formatInt, formatRate } from "../lib/format";
import { useAsync, useDocumentTitle } from "../lib/hooks";

const LOW_COVERAGE = 60;

function caseLink(v: CaseView) {
  return (
    <Link className="case-link" to={`/cases/${encodeURIComponent(v.case_id)}`}>
      Open this case
    </Link>
  );
}

/** One comparison row: row label, then one cell per case. */
function Row({ label, a, b }: { label: ReactNode; a: ReactNode; b: ReactNode }) {
  return (
    <tr>
      <th scope="row" className="cmp-label">
        {label}
      </th>
      <td className="cmp-cell">{a}</td>
      <td className="cmp-cell">{b}</td>
    </tr>
  );
}

function GroupRow({ children }: { children: ReactNode }) {
  return (
    <tr className="cmp-group">
      <th scope="rowgroup" colSpan={3}>
        {children}
      </th>
    </tr>
  );
}

function SignalCell({ v, s }: { v: CaseView; s: SignalView | undefined }) {
  if (!s) return <span className="muted small">Not in this case</span>;
  const hasScore = s.scored && s.score !== null;
  const pct = hasScore ? Math.max(0, Math.min(100, s.score as number)) : 0;
  return (
    <div className={`tone-${s.tone}`}>
      <div className="cmp-fig">
        <span className="cmp-num">{hasScore ? Math.round(pct) : "n/s"}</span>
        <span className="cmp-unit">{hasScore ? "/ 100" : "Not scored"}</span>
      </div>
      <div
        className="cmp-rule"
        role="meter"
        aria-label={`${s.name} score for ${v.target}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={hasScore ? Math.round(pct) : undefined}
        aria-valuetext={hasScore ? `${Math.round(pct)} out of 100` : "Not scored"}
      >
        {hasScore ? <div className="cmp-rule-fill" style={{ width: `${pct}%` }} /> : null}
      </div>
      <Disclosure summary="Finding">
        <p style={{ margin: 0 }}>{s.finding}</p>
      </Disclosure>
    </div>
  );
}

function SummaryCell({ v }: { v: CaseView }) {
  const a = v.assessment;
  if (!a) return <span className="muted small">No assessment yet.</span>;
  return (
    <div className={`tone-${a.risk_tone}`}>
      {a.risk_score !== null ? (
        <div className="cmp-fig">
          <span className="cmp-num cmp-num-lg">{Math.round(a.risk_score)}</span>
          <span className="cmp-band">{a.risk_band ?? ""}</span>
        </div>
      ) : (
        <div className="cmp-band">Not enough evidence to score</div>
      )}
      <p className="small muted cmp-sub">
        Coverage <strong className="num">{Math.round(a.coverage_pct)}%</strong> ({a.coverage_label})
      </p>
      <p className="small muted cmp-sub">
        Confidence <strong className="num">{Math.round(a.confidence)}</strong> ({a.confidence_label})
      </p>
    </div>
  );
}

function CreditsCell({ v }: { v: CaseView }) {
  const c = v.credits;
  return (
    <>
      {c.simulated ? (
        <p className="cmp-sub">
          <StatusPill tone="caution">Simulated</StatusPill> <span className="small muted">No real credits used</span>
        </p>
      ) : (
        <p className="cmp-sub">
          <strong className="cmp-num">{formatCredits(c.actual_used)}</strong>{" "}
          <span className="small muted">confirmed used</span>
        </p>
      )}
      <p className="small muted cmp-sub">Cap {formatCredits(c.cap)}</p>
    </>
  );
}

function VerificationCell({ v }: { v: CaseView }) {
  const ver = v.verification;
  if (!ver) return <span className="muted small">Not available yet.</span>;
  return (
    <>
      <p className="cmp-sub">
        <strong className="num">{formatInt(ver.published)}</strong> published, <strong className="num">{formatInt(ver.rejected)}</strong> rejected
      </p>
      <p className="small muted cmp-sub">Grounded in evidence {formatRate(ver.grounded_rate)}</p>
    </>
  );
}

function warnings(a: CaseView, b: CaseView): string[] {
  const out: string[] = [];
  if (a.synthetic !== b.synthetic) {
    out.push("One case uses live data and the other uses synthetic demo data. Their scores are not directly comparable.");
  }
  for (const v of [a, b]) {
    const asm = v.assessment;
    if (!asm || asm.risk_score === null) {
      out.push(`${v.target} has no risk score, so there is no overall result to compare.`);
    } else if (asm.coverage_pct < LOW_COVERAGE) {
      out.push(`${v.target} has coverage below ${LOW_COVERAGE}%, so its score is provisional.`);
    }
  }
  return out;
}

function CompareView({ a, b }: { a: CaseView; b: CaseView }) {
  const warn = warnings(a, b);
  const mixed = a.synthetic !== b.synthetic;

  // Union of signal ids in S1..S5 order, taking names from whichever case has the signal.
  const ids = Array.from(new Set([...a.signals.map((s) => s.id), ...b.signals.map((s) => s.id)])).sort();
  const find = (v: CaseView, id: string) => v.signals.find((s) => s.id === id);

  return (
    <>
      {warn.length > 0 ? (
        <Banner tone="caution" title={mixed ? "Comparing live and demo data" : "Read this comparison with care"}>
          {warn.join(" ")}
        </Banner>
      ) : null}

      <div className="table-wrap cmp-wrap">
        <table className="cmp">
          <caption className="sr-only">
            Side-by-side comparison of {a.target} and {b.target}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="sr-only">
                Measure
              </th>
              {[a, b].map((v) => (
                <th scope="col" key={v.case_id} className="cmp-head">
                  <div className="case-meta">
                    <ModeBadge mode={v.mode} />
                    <StatusPill tone={v.status_tone}>{v.status_label}</StatusPill>
                  </div>
                  <div className="cmp-title">{v.target}</div>
                  <div className="cmp-peers">Peers: {v.peers.length > 0 ? v.peers.join(", ") : "none listed"}</div>
                  <div className="cmp-open">{caseLink(v)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <GroupRow>Overall result</GroupRow>
            <Row label="Risk" a={<SummaryCell v={a} />} b={<SummaryCell v={b} />} />
            <GroupRow>Signals (0 to 100; a higher score is a stronger risk signal)</GroupRow>
            {ids.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  Neither case has signals yet.
                </td>
              </tr>
            ) : (
              ids.map((id) => {
                const sa = find(a, id);
                const sb = find(b, id);
                const name = sa?.name ?? sb?.name ?? id;
                return (
                  <Row
                    key={id}
                    label={
                      <>
                        <span className="cmp-id">{id}</span> {name}
                      </>
                    }
                    a={<SignalCell v={a} s={sa} />}
                    b={<SignalCell v={b} s={sb} />}
                  />
                );
              })
            )}
            <GroupRow>Cost and trust</GroupRow>
            <Row label="Credits" a={<CreditsCell v={a} />} b={<CreditsCell v={b} />} />
            <Row label="Verification" a={<VerificationCell v={a} />} b={<VerificationCell v={b} />} />
          </tbody>
        </table>
      </div>
    </>
  );
}

function CompareLoader({ idA, idB }: { idA: string; idB: string }) {
  const { data, error, loading, reload } = useAsync(() => Promise.all([api.getCase(idA), api.getCase(idB)]));
  if (loading) return <Loading label="Loading both cases..." />;
  if (error || !data) {
    return (
      <>
        <ErrorBox title="Could not load one of the cases" message={error ?? "The cases were not found."} onRetry={reload} />
        <p style={{ marginTop: 14 }}>
          <Link to="/cases">Back to all cases</Link>
        </p>
      </>
    );
  }
  return <CompareView a={data[0]} b={data[1]} />;
}

export function Compare() {
  useDocumentTitle("Compare cases");
  const [params] = useSearchParams();
  const idA = params.get("a")?.trim() ?? "";
  const idB = params.get("b")?.trim() ?? "";
  const valid = idA.length > 0 && idB.length > 0 && idA !== idB;

  return (
    <>
      <p className="small" style={{ marginBottom: 10 }}>
        <Link to="/cases">All cases</Link>
      </p>
      <PageHeader
        kicker="Side by side"
        title="Compare cases"
        dek="Two investigations set against each other: overall result, each risk signal, credits and verification."
      />
      {valid ? (
        <CompareLoader key={`${idA}|${idB}`} idA={idA} idB={idB} />
      ) : (
        <EmptyBox>
          Pick two different cases to compare. <Link to="/cases">Go to Cases</Link>, tick two rows and choose
          &ldquo;Compare selected&rdquo;.
        </EmptyBox>
      )}
    </>
  );
}
