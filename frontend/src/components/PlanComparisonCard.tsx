import type { PlanComparison } from "../api/types";
import { formatInt } from "../lib/format";
import { StatusPill } from "./ui";

function usd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(n: number | null): string {
  return n === null ? "-" : `${n.toFixed(1)}%`;
}

/** This case's real cost next to the cfo.ai business plan's per-audit assumptions. */
export function PlanComparisonCard({ pc }: { pc: PlanComparison }) {
  const dataDiff = pc.data_cost_case - pc.data_cost_plan;
  const aiNote =
    pc.llm_tokens !== null && pc.llm_tokens > 0
      ? `${formatInt(pc.llm_tokens)} tokens over ${formatInt(pc.llm_calls ?? 0)} calls${
          pc.llm_model ? ` (${pc.llm_model})` : ""
        }; plan figure used`
      : "No AI usage recorded for the latest run; plan figure used";
  const rows: { label: string; detail: string; caseV: string; planV: string; emphasis?: boolean }[] = [
    {
      label: "Company data (Crustdata)",
      detail: `${pc.credits_used} ${pc.credits_basis} vs ${pc.plan_credits_per_audit} assumed, at ${usd(
        pc.dollars_per_credit,
      )} per credit`,
      caseV: usd(pc.data_cost_case),
      planV: usd(pc.data_cost_plan),
    },
    { label: "AI planning and writing", detail: aiNote, caseV: usd(pc.llm_cost_plan), planV: usd(pc.llm_cost_plan) },
    { label: "Human review", detail: "Analyst checks the memo before delivery", caseV: usd(pc.review_cost), planV: usd(pc.review_cost) },
    { label: "Tooling and delivery", detail: "Storage, export, delivery", caseV: usd(pc.tooling_cost), planV: usd(pc.tooling_cost) },
    { label: "Cost per audit", detail: "", caseV: usd(pc.total_case), planV: usd(pc.total_plan), emphasis: true },
    { label: "Price per audit (base plan)", detail: "", caseV: usd(pc.price), planV: usd(pc.price) },
    { label: "Gross margin", detail: "", caseV: pct(pc.margin_case_pct), planV: pct(pc.margin_plan_pct), emphasis: true },
  ];
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3>
        Cost vs business plan{" "}
        {pc.simulated ? <StatusPill tone="caution">Demo data - simulated credits</StatusPill> : null}
      </h3>
      <p className="muted small" style={{ marginTop: -4 }}>
        Compares what this investigation used with the per-audit assumptions in the cfo.ai business plan.
      </p>
      <p>
        <StatusPill tone={dataDiff <= 0 ? "good" : "caution"}>
          {dataDiff <= 0 ? "Data cost under plan" : "Data cost over plan"}
        </StatusPill>{" "}
        {pc.summary}
      </p>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Case cost compared with the business plan</caption>
          <thead>
            <tr>
              <th scope="col">Cost line</th>
              <th scope="col">This case</th>
              <th scope="col">Business plan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <td>
                  {r.emphasis ? <strong>{r.label}</strong> : r.label}
                  {r.detail ? <div className="muted small">{r.detail}</div> : null}
                </td>
                <td>{r.emphasis ? <strong>{r.caseV}</strong> : r.caseV}</td>
                <td>{r.emphasis ? <strong>{r.planV}</strong> : r.planV}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="muted small" style={{ marginBottom: 0 }}>
        {pc.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}
