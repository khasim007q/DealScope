import { useEffect, useState } from "react";
import { HOW_IT_WORKS } from "../content";
import type { HowItWorksContent, HowItWorksSection } from "../content/types";
import { useDocumentTitle } from "../lib/hooks";

const CONTENT: HowItWorksContent = HOW_IT_WORKS;

function Section({ section }: { section: HowItWorksSection }) {
  return (
    <section className="hiw-section card" id={section.id} aria-labelledby={`${section.id}-h`}>
      <h2 id={`${section.id}-h`}>{section.title}</h2>
      <p className="summary-line">{section.summary}</p>
      {section.paragraphs.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
      {section.bullets && section.bullets.length > 0 ? (
        <ul>
          {section.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      ) : null}
      {section.table ? (
        <div className="table-wrap" style={{ margin: "12px 0" }}>
          <table>
            <thead>
              <tr>
                {section.table.headers.map((h, i) => (
                  <th key={i} scope="col">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.table.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c}>{cell}</td>
                  ))}
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
      <div className="page-head">
        <h1>How it works</h1>
        <p className="hiw-intro">{CONTENT.intro}</p>
      </div>
      <div className="hiw">
        <nav className="toc" aria-label="On this page">
          <h2>On this page</h2>
          <ol>
            {sections.map((s) => (
              <li key={s.id} style={{ margin: 0 }}>
                <a
                  href={`#${s.id}`}
                  className={active === s.id ? "active" : undefined}
                  aria-current={active === s.id ? "location" : undefined}
                  onClick={() => setActive(s.id)}
                >
                  {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div>
          {sections.map((s) => (
            <Section key={s.id} section={s} />
          ))}
        </div>
      </div>
    </>
  );
}
