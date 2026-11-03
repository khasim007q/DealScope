import type { ReactNode } from "react";

/** Numbered sections of the case report; the single source for headings and the side index. */
export const REPORT_SECTIONS = [
  { num: 1, id: "signals-h", label: "Signals" },
  { num: 2, id: "findings-h", label: "Findings" },
  { num: 3, id: "questions-h", label: "Questions to validate" },
  { num: 4, id: "evidence-h", label: "Evidence" },
  { num: 5, id: "cost-h", label: "Method and cost" },
  { num: 6, id: "trace-h", label: "Run trace" },
] as const;

/** Section opener: heavy rule, "Section N" kicker, serif title, optional dek. */
export function ReportHead({ num, title, subtitle }: { num: (typeof REPORT_SECTIONS)[number]["num"]; title: string; subtitle?: ReactNode }) {
  const s = REPORT_SECTIONS.find((x) => x.num === num);
  return (
    <div className="report-head">
      <p className="kicker">Section {num}</p>
      <h2 id={s?.id}>{title}</h2>
      {subtitle ? <p className="report-dek">{subtitle}</p> : null}
    </div>
  );
}
