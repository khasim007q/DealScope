import { useEffect, useState } from "react";
import { HOW_IT_WORKS } from "../content";
import type { HowItWorksContent, HowItWorksSection } from "../content/types";
import { Kicker, PageHeader } from "../components/ui";
import { useDocumentTitle } from "../lib/hooks";

const CONTENT: HowItWorksContent = HOW_IT_WORKS;
const STEP = /^(\d+)\.\s+/;
const NUMERIC_HEADER = /^(weight|%|credits|cost)/i;

/** Paragraphs that all start "1. ", "2. " ... are rendered as a numbered list. */
function Body({ paragraphs }: { paragraphs: string[] }) {
  if (paragraphs.length > 1 && paragraphs.every((p) => STEP.test(p))) {
    return (
      <ol className="hiw-steps">
        {paragraphs.map((p, i) => {
          const text = p.replace(STEP, "");
          const dot = text.indexOf(". ");
          const head = dot > 0 && dot < 40 ? text.slice(0, dot) : null;
          return (
            <li key={i}>
              {head ? (
                <>
                  <strong>{head}.</strong> {text.slice(dot + 2)}
                </>
              ) : (
                text
              )}
            </li>
          );
        })}
      </ol>
    );
  }
  return (
    <>
      {paragraphs.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </>
  );
}

function Section({ section, n }: { section: HowItWorksSection; n: number }) {
  const table = section.table;
  return (
    <section className="hiw-section" id={section.id} aria-labelledby={`${section.id}-h`}>
      <Kicker accent>Section {n}</Kicker>
      <h2 id={`${section.id}-h`}>{section.title}</h2>
      <p className="summary-line">{section.summary}</p>
      <Body paragraphs={section.paragraphs} />
      {section.bullets && section.bullets.length > 0 ? (
        <ul className="hiw-bullets">
          {section.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      ) : null}
      {table ? (
        <div className="table-wrap hiw-table">
          <table>
            <thead>
              <tr>
                {table.headers.map((h, i) => (
                  <th key={i} scope="col" className={NUMERIC_HEADER.test(h) ? "num" : undefined}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) =>
                    c === 0 ? (
                      <th key={c} scope="row">
                        {cell}
                      </th>
                    ) : (
                      <td key={c} className={NUMERIC_HEADER.test(table.headers[c] ?? "") ? "num" : undefined}>
                        {cell}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function HowItWorks() {
  useDocumentTitle("How it works");
  const sections = CONTENT.sections;
  const [active, setActive] = useState<string>(sections[0]?.id ?? "");

  useEffect(() => {
    const els = sections.map((s) => document.getElementById(s.id)).filter((e): e is HTMLElement => e !== null);
    if (els.length === 0 || typeof IntersectionObserver === "undefined") return;
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) setActive(visible[0].target.id);
      },
      { rootMargin: "-80px 0px -60% 0px", threshold: 0 },
    );
    els.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [sections]);

  return (
    <>
      <PageHeader kicker="Explainer" title="How it works" dek={CONTENT.intro} />
      <div className="hiw">
        <nav className="toc" aria-label="On this page">
          <details className="toc-details" open>
            <summary
              onClick={(e) => {
                if (window.matchMedia("(min-width: 901px)").matches) e.preventDefault();
              }}
            >
              On this page
            </summary>
            <ol>
              {sections.map((s, i) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    className={active === s.id ? "active" : undefined}
                    aria-current={active === s.id ? "location" : undefined}
                    onClick={() => setActive(s.id)}
                  >
                    <span className="toc-n">{i + 1}</span>
                    {s.title}
                  </a>
                </li>
              ))}
            </ol>
          </details>
        </nav>
        <article className="hiw-article">
          {sections.map((s, i) => (
            <Section key={s.id} section={s} n={i + 1} />
          ))}
        </article>
      </div>
    </>
  );
}
