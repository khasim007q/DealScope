import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseView, SignalView } from "../api/types";
import { Banner, Disclosure, EmptyBox, ErrorBox, Loading, ModeBadge, SectionHead, StatusPill } from "../components/ui";
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

/** One comparison row: label across the top, then the two sides (stacked on narrow screens). */
function Row({ label, a, b }: { label: ReactNode; a: ReactNode; b: ReactNode }) {
  return (
    <div className="cmp-row">
      <div className="cmp-label">{label}</div>
      <div className="cmp-cell">{a}</div>
      <div className="cmp-cell">{b}</div>
    </div>
  );
}

function Who({ v }: { v: CaseView }) {
  return <div className="cmp-who">{v.target}</div>;
}

function SignalCell({ v, s }: { v: CaseView; s: SignalView | undefined }) {
  if (!s) {
    return (
      <>
        <Who v={v} />
        <p className="muted">This signal is not in this case.</p>
      </>
    );
  }
  const hasScore = s.scored && s.score !== null;
  const pct = hasScore ? Math.max(0, Math.min(100, s.score as number)) : 0;
  return (
    <div className={`tone-${s.tone}`}>
      <Who v={v} />
      <div className="bar-row">
        <div
          className="bar-track"
          role="meter"
          aria-label={`${s.name} score for ${v.target}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={hasScore ? Math.round(pct) : undefined}
          aria-valuetext={hasScore ? `${Math.round(pct)} out of 100` : "Not scored"}
        >
          {hasScore ? <div className="bar-fill" style={{ width: `${pct}%` }} /> : null}
        </div>
        <span className="bar-val">{hasScore ? `${Math.round(pct)} / 100` : "Not scored"}</span>
      </div>
      <Disclosure summary="Finding">
        <p style={{ margin: 0 }}>{s.finding}</p>
      </Disclosure>
    </div>
  );
}

function SummaryCell({ v }: { v: CaseView }) {
  const a = v.assessment;
  if (!a) {
    return (
      <>
        <Who v={v} />
        <p className="muted">No assessment yet.</p>
      </>
    );
  }
  return (
    <>
      <Who v={v} />
      <div className={`cmp-score tone-${a.risk_tone}`}>
        {a.risk_score !== null ? (
          <>
            <span className="cmp-score-num">{Math.round(a.risk_score)}</span>
            <span className="cmp-score-band">{a.risk_band ?? ""}</span>
          </>
        ) : (
          <span className="cmp-score-band">Not enough evidence to score</span>
        )}
      </div>
      <p className="small" style={{ margin: "6px 0 0" }}>
        Coverage: <strong>{Math.round(a.coverage_pct)}%</strong> ({a.coverage_label})
      </p>
      <p className="small" style={{ margin: 0 }}>
        Confidence: <strong>{Math.round(a.confidence)}</strong> ({a.confidence_label})
      </p>
    </>
  );
}

function CreditsCell({ v }: { v: CaseView }) {
  const c = v.credits;
  return (
    <>
      <Who v={v} />
      {c.simulated ? (
        <p style={{ margin: 0 }}>
          <StatusPill tone="caution">Simulated</StatusPill> <span className="small muted">No real credits used</span>
        </p>
      ) : (
        <p style={{ margin: 0 }}>
          <strong>{formatCredits(c.actual_used)}</strong> confirmed used
        </p>
      )}
      <p className="small muted" style={{ margin: 0 }}>
        Cap: {formatCredits(c.cap)}
      </p>
    </>
  );
}

function VerificationCell({ v }: { v: CaseView }) {
  const ver = v.verification;
  return (
    <>
      <Who v={v} />
      {ver ? (
        <>
          <p style={{ margin: 0 }}>
            <strong>{formatInt(ver.published)}</strong> published, <strong>{formatInt(ver.rejected)}</strong> rejected
          </p>
          <p className="small muted" style={{ margin: 0 }}>
            Grounded in evidence: {formatRate(ver.grounded_rate)}
          </p>
        </>
      ) : (
        <p className="muted">Not available yet.</p>
      )}
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

      <div className="cmp">
        <div className="cmp-row cmp-heads">
          <div className="cmp-label sr-only">Case</div>
          {[a, b].map((v) => (
            <div className="cmp-cell card" key={v.case_id}>
              <div className="case-meta">
                <ModeBadge mode={v.mode} />
                <StatusPill tone={v.status_tone}>{v.status_label}</StatusPill>
              </div>
              <h2 style={{ marginBottom: 4, wordBreak: "break-word" }}>{v.target}</h2>
              <p className="small peer-list">
                <strong>Compared with:</strong> {v.peers.length > 0 ? v.peers.join(", ") : "no peers listed"}
              </p>
              <p className="small" style={{ margin: 0 }}>
                {caseLink(v)}
              </p>
            </div>
          ))}
        </div>

        <Row label="Overall result" a={<SummaryCell v={a} />} b={<SummaryCell v={b} />} />

        <div className="cmp-section-title">
          <SectionHead title="Signals" subtitle="Scores run from 0 to 100; a higher score means a stronger risk signal." />
        </div>
        {ids.length === 0 ? (
          <EmptyBox>Neither case has signals yet.</EmptyBox>
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
                    <span className="muted">{id}</span> {name}
                  </>
                }
                a={<SignalCell v={a} s={sa} />}
                b={<SignalCell v={b} s={sb} />}
              />
            );
          })
        )}

        <div className="cmp-section-title">
          <SectionHead title="Cost and trust" />
        </div>
        <Row label="Credits" a={<CreditsCell v={a} />} b={<CreditsCell v={b} />} />
        <Row label="Verification" a={<VerificationCell v={a} />} b={<VerificationCell v={b} />} />
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
      <div className="page-head">
        <h1>Compare cases</h1>
        <p>Two investigations side by side: overall result, each risk signal, credits and verification.</p>
      </div>
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
