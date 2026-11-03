import { Link, useParams } from "react-router-dom";
import { CaseHeader } from "../components/CaseHeader";
import { CaseTraces } from "../components/CaseTraces";
import { CostTrust } from "../components/CostTrust";
import { EvidenceTabs } from "../components/EvidenceTabs";
import { FindingsSection } from "../components/FindingsSection";
import { ProgressPanel } from "../components/ProgressPanel";
import { QuestionsSection } from "../components/QuestionsSection";
import { REPORT_SECTIONS } from "../components/ReportHead";
import { SignalsSection } from "../components/SignalsSection";
import { StepTimeline } from "../components/StepTimeline";
import { SummaryCard } from "../components/SummaryCard";
import { EmptyBox, ErrorBox, Kicker, Loading } from "../components/ui";
import { useCase, useDocumentTitle } from "../lib/hooks";
import type { CaseView } from "../api/types";
import { formatPct } from "../lib/format";

/** Sticky side index and key figures; shown only on wide screens. */
function CaseRail({ v }: { v: CaseView }) {
  const a = v.assessment;
  const scored = v.signals.filter((s) => s.scored && s.score !== null).length;
  return (
    <aside className="case-rail" aria-label="Report index and key figures">
      <nav aria-label="Report sections">
        <Kicker>In this report</Kicker>
        <ol className="rail-index">
          {REPORT_SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>
                <span className="rail-n">{s.num}</span>
                {s.label}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <dl className="rail-figs">
        <div>
          <dt>Risk score</dt>
          <dd>{a && a.risk_score !== null ? `${a.risk_score} / 100` : "Not scored"}</dd>
        </div>
        {a ? (
          <>
            <div>
              <dt>Coverage</dt>
              <dd>{formatPct(a.coverage_pct)}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{a.confidence_label}</dd>
            </div>
          </>
        ) : null}
        <div>
          <dt>Signals scored</dt>
          <dd>
            {scored} of {v.signals.length}
          </dd>
        </div>
        <div>
          <dt>Findings</dt>
          <dd>{v.findings.length}</dd>
        </div>
      </dl>
    </aside>
  );
}

export function CaseDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const { data, error, loading, refresh } = useCase(id);
  useDocumentTitle(data ? `${data.target} investigation` : "Case");

  if (loading && !data) {
    return <Loading label="Loading case..." />;
  }
  if (!data) {
    return (
      <>
        <ErrorBox title="Could not load this case" message={error ?? "The case was not found."} onRetry={refresh} />
        <p style={{ marginTop: 14 }}>
          <Link to="/cases">Back to all cases</Link>
        </p>
      </>
    );
  }

  const v = data;
  return (
    <div className="case">
      <p className="small case-back">
        <Link to="/cases">All cases</Link>
      </p>
      {error ? (
        <div style={{ marginBottom: 12 }}>
          <ErrorBox title="Live updates interrupted" message={`${error} Retrying automatically.`} />
        </div>
      ) : null}

      <CaseHeader view={v} onResumed={refresh} />

      {v.running ? <ProgressPanel view={v} /> : null}

      <div className="case-layout">
        <div className="case-main">
          <SummaryCard assessment={v.assessment} running={v.running} />
          <SignalsSection signals={v.signals} />
          <FindingsSection findings={v.findings} />
          <QuestionsSection questions={v.questions} />
          <EvidenceTabs companies={v.companies} people={v.people} jobs={v.jobs} />
          <CostTrust
            credits={v.credits}
            verification={v.verification}
            llmModel={v.llm_model}
            traceIds={v.trace_ids}
            synthetic={v.synthetic}
          >
            <div className="method-log">
              <h3 id="steps-h" className="fig-h">
                How the agent investigated
              </h3>
              <p className="muted small">
                A step-by-step record. The AI planner chooses what to look up; the rule-based planner is the fixed fallback; the
                system handles everything else.
              </p>
              {v.steps.length === 0 ? <EmptyBox>No steps have been recorded yet.</EmptyBox> : <StepTimeline steps={v.steps} />}
            </div>
          </CostTrust>
          <CaseTraces caseId={v.case_id} traceIds={v.trace_ids} running={v.running} />
        </div>
        <CaseRail v={v} />
      </div>
    </div>
  );
}
