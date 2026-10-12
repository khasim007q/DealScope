import { useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../lib/hooks";
import { CopyButton, EmptyBox, ErrorBox, Loading, SectionHead } from "./ui";
import { TraceWaterfall } from "./TraceWaterfall";

export function CaseTraces({ caseId, traceIds, running }: { caseId: string; traceIds: string[]; running: boolean }) {
  const { data, error, loading, reload } = useAsync(() => api.getCaseTraces(caseId));
  const [selected, setSelected] = useState(0);
  // Intentionally loaded once per page visit; reload when a running case finishes so the trace appears.
  const [wasRunning, setWasRunning] = useState(running);
  if (wasRunning !== running) {
    setWasRunning(running);
    if (!running) reload();
  }

  const traces = data ?? [];
  const idx = Math.min(selected, Math.max(traces.length - 1, 0));
  const current = traces[idx];

  return (
    <section className="section" aria-labelledby="trace-h">
      <SectionHead
        id="trace-h"
        title="Trace of this run"
        subtitle="The real sequence of steps the agent executed, with timing. The same trace is in the neatlogs dashboard."
      />
      {loading && !data ? (
        <Loading label="Loading trace..." />
      ) : error ? (
        <ErrorBox title="Could not load the trace" message={error} onRetry={reload} />
      ) : !current ? (
        <EmptyBox>
          <p style={{ margin: 0 }}>
            No recorded trace for this run. Runs started before trace recording was added only have their trace in the
            neatlogs dashboard.
          </p>
          {traceIds.length > 0 ? (
            <div style={{ marginTop: 10 }}>
              {traceIds.map((t) => (
                <div className="trace-row" key={t} style={{ justifyContent: "center" }}>
                  <span className="trace-id">{t}</span>
                  <CopyButton text={t} label="Copy" />
                </div>
              ))}
            </div>
          ) : null}
        </EmptyBox>
      ) : (
        <div className="card">
          {traces.length > 1 ? (
            <div className="tabs" role="tablist" aria-label="Runs of this case">
              {traces.map((t, i) => (
                <button
                  key={t.trace_id}
                  type="button"
                  role="tab"
                  id={`run-tab-${i}`}
                  className="tab"
                  aria-selected={i === idx}
                  aria-controls="run-tabpanel"
                  tabIndex={i === idx ? 0 : -1}
                  onClick={() => setSelected(i)}
                >
                  {i === 0 ? "Run 1" : `Run ${i + 1} (resume)`}
                </button>
              ))}
            </div>
          ) : null}
          <div id="run-tabpanel" role={traces.length > 1 ? "tabpanel" : undefined} aria-labelledby={traces.length > 1 ? `run-tab-${idx}` : undefined}>
            <TraceWaterfall key={current.trace_id} trace={current} />
          </div>
        </div>
      )}
    </section>
  );
}
