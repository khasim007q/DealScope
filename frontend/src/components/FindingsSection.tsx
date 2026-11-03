import type { EvidenceRef, FindingView, Tone } from "../api/types";
import { formatDate } from "../lib/format";
import { EmptyBox, StatusPill } from "./ui";
import { ReportHead } from "./ReportHead";

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

interface Note {
  n: number;
  ref: EvidenceRef;
  counter: boolean;
}

/** Footnote-style evidence references, numbered continuously across the whole section. */
function numberNotes(group: FindingView[], start: number): { notes: Map<string, Note[]>; next: number } {
  const notes = new Map<string, Note[]>();
  let n = start;
  for (const f of group) {
    const list: Note[] = [];
    for (const ref of f.evidence) list.push({ n: n++, ref, counter: false });
    for (const ref of f.counter_evidence) list.push({ n: n++, ref, counter: true });
    notes.set(f.id, list);
  }
  return { notes, next: n };
}

function SubList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="finding-sub">
      <h4>{title}</h4>
      <ul>
        {items.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </div>
  );
}

function Finding({ f, notes }: { f: FindingView; notes: Note[] }) {
  const tone = SEVERITY_TONE[f.severity];
  const caveated = f.verification === "Verified with caveats";
  return (
    <article className={`finding tone-${tone}`}>
      <div className="finding-top">
        <StatusPill tone={tone}>{`${f.severity.charAt(0).toUpperCase()}${f.severity.slice(1)} severity`}</StatusPill>
        <StatusPill tone={caveated ? "caution" : "good"}>{f.verification}</StatusPill>
      </div>
      <p className="finding-text">
        {f.text}
        {notes.map((nt) => (
          <sup key={nt.n} className={`fn-mark${nt.counter ? " counter" : ""}`}>
            <a href={`#fn-${f.id}-${nt.n}`} aria-label={`${nt.counter ? "Counter-evidence" : "Evidence"} ${nt.n}`}>
              {nt.counter ? `c${nt.n}` : nt.n}
            </a>
          </sup>
        ))}
      </p>

      <SubList title="Caveats" items={f.caveats} />
      <SubList title="Other possible explanations" items={f.alternatives} />
      <SubList title="Limitations" items={f.limitations} />

      {notes.length > 0 ? (
        <ol className="fn-list" aria-label="Evidence references">
          {notes.map((nt) => (
            <li key={nt.n} id={`fn-${f.id}-${nt.n}`} value={nt.n} className={nt.counter ? "counter" : undefined}>
              <span className="fn-label">
                {nt.counter ? <strong>Points the other way: </strong> : null}
                {nt.ref.label}
              </span>
              <span className="fn-meta">
                {nt.ref.date ? `${formatDate(nt.ref.date)} - ` : ""}
                {nt.ref.source}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}

export function FindingsSection({ findings }: { findings: FindingView[] }) {
  let counter = 1;
  return (
    <section className="section" aria-labelledby="findings-h">
      <ReportHead
        num={2}
        title="Key findings"
        subtitle="Every finding was checked against its evidence before being published. Numbered marks refer to the evidence listed under each claim."
      />
      {findings.length === 0 ? (
        <EmptyBox>No findings were published for this case.</EmptyBox>
      ) : (
        KIND_ORDER.map(({ kind, title, blurb }) => {
          const group = findings.filter((f) => f.kind === kind);
          if (group.length === 0) return null;
          const { notes, next } = numberNotes(group, counter);
          counter = next;
          return (
            <div className="finding-group" key={kind}>
              <h3>
                {title} <span className="muted">{blurb}</span>
              </h3>
              {group.map((f) => (
                <Finding key={f.id} f={f} notes={notes.get(f.id) ?? []} />
              ))}
            </div>
          );
        })
      )}
    </section>
  );
}
