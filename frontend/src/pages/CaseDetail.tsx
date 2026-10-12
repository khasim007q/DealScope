import { Link, useParams } from "react-router-dom";
import { CaseHeader } from "../components/CaseHeader";
import { CostTrust } from "../components/CostTrust";
import { EvidenceTabs } from "../components/EvidenceTabs";
import { FindingsSection } from "../components/FindingsSection";
import { ProgressPanel } from "../components/ProgressPanel";
import { QuestionsSection } from "../components/QuestionsSection";
import { SignalsSection } from "../components/SignalsSection";
import { StepTimeline } from "../components/StepTimeline";
import { SummaryCard } from "../components/SummaryCard";
import { EmptyBox, ErrorBox, Loading, SectionHead } from "../components/ui";
import { useCase, useDocumentTitle } from "../lib/hooks";

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
    <>
      <p className="small" style={{ marginBottom: 10 }}>
        <Link to="/cases">All cases</Link>
      </p>
      {error ? (
        <div style={{ marginBottom: 12 }}>
          <ErrorBox title="Live updates interrupted" message={`${error} Retrying automatically.`} />
        </div>
      ) : null}

      <CaseHeader view={v} onResumed={refresh} />

      {v.running ? <ProgressPanel view={v} /> : null}

      <div className="section" style={{ marginTop: 16 }}>
        <SummaryCard assessment={v.assessment} running={v.running} />
      </div>

      <SignalsSection signals={v.signals} />
      <FindingsSection findings={v.findings} />
      <QuestionsSection questions={v.questions} />

      <section className="section" aria-labelledby="steps-h">
        <SectionHead
          id="steps-h"
          title="How the agent investigated"
          subtitle="A step-by-step record. The AI planner chooses what to look up; the rule-based planner is the fixed fallback; the system handles everything else."
        />
        <div className="card">
          {v.steps.length === 0 ? (
            <EmptyBox>No steps have been recorded yet.</EmptyBox>
          ) : (
            <StepTimeline steps={v.steps} />
          )}
        </div>
      </section>

      <EvidenceTabs companies={v.companies} people={v.people} jobs={v.jobs} />
      <CostTrust
        credits={v.credits}
        verification={v.verification}
        llmModel={v.llm_model}
        traceIds={v.trace_ids}
        synthetic={v.synthetic}
      />
    </>
  );
}
