import type { EvidenceRef, FindingView, Tone } from "../api/types";
import { formatDate } from "../lib/format";
import { EmptyBox, SectionHead, StatusPill } from "./ui";

type Kind = FindingView["kind"];

const KIND_ORDER: { kind: Kind; title: string; blurb: string }[] = [
  { kind: "Fact", title: "Facts", blurb: "Directly supported by the data." },
  { kind: "Interpretation", title: "Interpretations", blurb: "What the facts probably mean." },
  { kind: "Hypothesis", title: "Hypotheses", blurb: "Plausible explanations to test, not conclusions." },
  { kind: "Question", title: "Questions", blurb: "Things the data cannot answer." },
];

const SEVERITY_TONE: Record<FindingView["severity"], Tone> = {
  low: "neutral",
  medium: "caution",
  high: "bad",
};

function EvidenceItems({ items, counter = false }: { items: EvidenceRef[]; counter?: boolean }) {
  return (
    <ul className="ev-list">
      {items.map((e, i) => (
        <li key={`${e.id}-${i}`} className={`ev-item${counter ? " counter" : ""}`}>
          <div className="ev-label">{e.label}</div>
          <div className="ev-meta">
            {e.date ? `${formatDate(e.date)} - ` : ""}
            {e.source}
          </div>
        </li>
      ))}
    </ul>
  );
}

function FindingCard({ f }: { f: FindingView }) {
  const tone = SEVERITY_TONE[f.severity];
  const caveated = f.verification === "Verified with caveats";
  return (
    <article className={`card finding tone-${tone}`}>
      <div className="finding-top">
        <StatusPill tone={tone}>{`${f.severity.charAt(0).toUpperCase()}${f.severity.slice(1)} severity`}</StatusPill>
        <StatusPill tone={caveated ? "caution" : "good"}>{f.verification}</StatusPill>
      </div>
      <p className="finding-text">{f.text}</p>

      {f.caveats.length > 0 ? (
        <>
          <h4>Caveats</h4>
          <ul>
            {f.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      ) : null}

      {f.alternatives.length > 0 ? (
        <>
          <h4>Other possible explanations</h4>
          <ul>
            {f.alternatives.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </>
      ) : null}

      {f.limitations.length > 0 ? (
        <>
          <h4>Limitations</h4>
          <ul>
            {f.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </>
      ) : null}

      {f.evidence.length + f.counter_evidence.length > 0 ? (
      <details className="disclosure">
        <summary>
          Evidence ({f.evidence.length})
          {f.counter_evidence.length > 0 ? `, counter-evidence (${f.counter_evidence.length})` : ""}
        </summary>
        <div className="disc-body">
          {f.evidence.length > 0 ? (
            <EvidenceItems items={f.evidence} />
          ) : (
            <p className="muted small">No supporting evidence items are attached.</p>
          )}
          {f.counter_evidence.length > 0 ? (
            <>
              <h4>Evidence that points the other way</h4>
              <EvidenceItems items={f.counter_evidence} counter />
            </>
          ) : null}
        </div>
      </details>
      ) : null}
    </article>
  );
}

export function FindingsSection({ findings }: { findings: FindingView[] }) {
  return (
    <section className="section" aria-labelledby="findings-h">
      <SectionHead
        id="findings-h"
        title="Key findings"
        subtitle="Every finding was checked against its evidence before being published."
      />
      {findings.length === 0 ? (
        <EmptyBox>No findings were published for this case.</EmptyBox>
      ) : (
        KIND_ORDER.map(({ kind, title, blurb }) => {
          const group = findings.filter((f) => f.kind === kind);
          if (group.length === 0) return null;
          return (
            <div className="finding-group" key={kind}>
              <h3>
                {title} <span className="muted">{blurb}</span>
              </h3>
              {group.map((f) => (
                <FindingCard key={f.id} f={f} />
              ))}
            </div>
          );
        })
      )}
    </section>
  );
}
