import { useMemo, useState } from "react";
import type { RecordedTrace, TraceSpan } from "../api/types";
import { formatDateTime, formatDuration, plural } from "../lib/format";
import { CopyButton } from "./ui";

interface Node {
  span: TraceSpan;
  children: Node[];
}

interface Row {
  node: Node;
  depth: number;
}

const KIND_CLASS: Record<string, string> = {
  WORKFLOW: "k-workflow",
  AGENT: "k-agent",
  TOOL: "k-tool",
  CHAIN: "k-chain",
  GUARDRAIL: "k-guardrail",
  LLM: "k-llm",
};

function kindClass(kind: string): string {
  return KIND_CLASS[kind.toUpperCase()] ?? "k-other";
}

function buildTree(spans: TraceSpan[]): Node[] {
  const nodes = new Map<string, Node>();
  for (const s of spans) nodes.set(s.span_id, { span: s, children: [] });
  const roots: Node[] = [];
  for (const s of spans) {
    const n = nodes.get(s.span_id);
    if (!n) continue;
    const parent = s.parent_id ? nodes.get(s.parent_id) : undefined;
    if (parent && parent !== n) parent.children.push(n);
    else roots.push(n);
  }
  const sort = (list: Node[]) => {
    list.sort((a, b) => a.span.start_ms - b.span.start_ms);
    list.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

/** Span ids that should stay visible when only failures are shown: failed spans and all their ancestors. */
function failureKeepSet(spans: TraceSpan[]): Set<string> {
  const byId = new Map(spans.map((s) => [s.span_id, s] as const));
  const keep = new Set<string>();
  for (const s of spans) {
    if (s.status !== "error") continue;
    let cur: TraceSpan | undefined = s;
    while (cur && !keep.has(cur.span_id)) {
      keep.add(cur.span_id);
      cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
    }
  }
  return keep;
}

function flatten(
  nodes: Node[],
  depth: number,
  collapsed: Set<string>,
  keep: Set<string> | null,
  out: Row[],
): void {
  for (const n of nodes) {
    if (keep && !keep.has(n.span.span_id)) continue;
    out.push({ node: n, depth });
    if (!collapsed.has(n.span.span_id)) flatten(n.children, depth + 1, collapsed, keep, out);
  }
}

function pct(n: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (n / total) * 100));
}

function eventLabel(e: TraceSpan["events"][number]): string {
  const attrs = Object.entries(e.attributes)
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(", ");
  return `${e.name} at ${formatDuration(e.at_ms)}${attrs ? ` (${attrs})` : ""}`;
}

function SpanDetails({ span, id }: { span: TraceSpan; id: string }) {
  const attrs = Object.entries(span.attributes).filter(([k]) => !k.startsWith("neatlogs."));
  return (
    <div className="tw-details" id={id}>
      <div className="tw-detail-meta">
        Starts at {formatDuration(span.start_ms)}, runs for {formatDuration(span.duration_ms)}
      </div>
      {attrs.length > 0 ? (
        <table className="tw-attrs">
          <caption className="sr-only">Attributes of {span.name}</caption>
          <tbody>
            {attrs.map(([k, v]) => (
              <tr key={k}>
                <th scope="row">{k}</th>
                <td>{String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted small" style={{ margin: 0 }}>
          No recorded attributes for this step.
        </p>
      )}
      {span.events.length > 0 ? (
        <>
          <h4 className="tw-h">Events</h4>
          <ul className="tw-events">
            {span.events.map((e, i) => (
              <li key={i}>{eventLabel(e)}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function SpanRow({
  row,
  total,
  prefix,
  expanded,
  collapsed,
  onToggleExpanded,
  onToggleCollapsed,
}: {
  row: Row;
  total: number;
  prefix: string;
  expanded: boolean;
  collapsed: boolean;
  onToggleExpanded: () => void;
  onToggleCollapsed: () => void;
}) {
  const { node, depth } = row;
  const s = node.span;
  const failed = s.status === "error";
  const left = pct(s.start_ms, total);
  const width = Math.min(pct(s.duration_ms, total), 100 - left);
  const detailsId = `${prefix}-${s.span_id}-details`;
  const domain = typeof s.attributes["dealscope.domain"] === "string" ? String(s.attributes["dealscope.domain"]) : null;
  const hasChildren = node.children.length > 0;
  const indent = { paddingLeft: depth * 18 };

  return (
    <li className={`tw-item${failed ? " failed" : ""}`}>
      <div className="tw-line" style={indent}>
        {hasChildren ? (
          <button
            type="button"
            className="tw-toggle"
            onClick={onToggleCollapsed}
            aria-expanded={!collapsed}
            aria-label={`${collapsed ? "Show" : "Hide"} ${node.children.length} child ${plural(node.children.length, "step")} of ${s.name}`}
          >
            <span className={`tw-chevron${collapsed ? "" : " open"}`} aria-hidden="true" />
          </button>
        ) : (
          <span className="tw-toggle-spacer" aria-hidden="true" />
        )}
        <button
          type="button"
          className="tw-main"
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          aria-controls={expanded ? detailsId : undefined}
        >
          <span className={`tw-kind ${kindClass(s.kind)}`}>{s.kind}</span>
          <span className="tw-name">
            <span className="tw-name-text">{s.name}</span>
            {domain ? <span className="tw-sub">{domain}</span> : null}
            {failed ? <span className="tw-failed">Failed</span> : null}
          </span>
          <span className="tw-track" aria-hidden="true">
            <span
              className={`tw-bar${failed ? " failed" : ""} ${kindClass(s.kind)}`}
              style={{ left: `${left}%`, width: `max(2px, ${width}%)` }}
            />
            {s.events.map((e, i) => (
              <span
                key={i}
                className="tw-tick"
                style={{ left: `${pct(e.at_ms, total)}%` }}
                title={eventLabel(e)}
              />
            ))}
          </span>
          <span className="tw-dur">{formatDuration(s.duration_ms)}</span>
        </button>
      </div>
      {failed && s.error ? (
        <div className="tw-error" style={{ marginLeft: depth * 18 + 26 }}>
          {s.error}
        </div>
      ) : null}
      {expanded ? (
        <div style={{ marginLeft: depth * 18 + 26 }}>
          <SpanDetails span={s} id={detailsId} />
        </div>
      ) : null}
    </li>
  );
}

export function TraceWaterfall({ trace, compact = false }: { trace: RecordedTrace; compact?: boolean }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [onlyFailures, setOnlyFailures] = useState(false);

  const tree = useMemo(() => buildTree(trace.spans), [trace.spans]);
  const total = useMemo(() => {
    const maxEnd = trace.spans.reduce((m, s) => Math.max(m, s.start_ms + s.duration_ms), 0);
    return Math.max(trace.duration_ms, maxEnd, 1);
  }, [trace]);
  const keep = useMemo(() => (onlyFailures ? failureKeepSet(trace.spans) : null), [onlyFailures, trace.spans]);
  const rows = useMemo(() => {
    const out: Row[] = [];
    flatten(tree, 0, collapsed, keep, out);
    return out;
  }, [tree, collapsed, keep]);

  const flip = (set: Set<string>, id: string): Set<string> => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };

  const prefix = `tw-${trace.trace_id.slice(0, 8)}`;

  return (
    <div className={`tw${compact ? " compact" : ""}`}>
      <div className="tw-head">
        <div className="tw-id">
          <span className="muted small">neatlogs trace</span>
          <span className="trace-id">{trace.trace_id}</span>
          <CopyButton text={trace.trace_id} label="Copy" />
        </div>
        <div className="tw-stats">
          <span>
            <strong>{formatDuration(trace.duration_ms)}</strong> total
          </span>
          <span>
            <strong>{trace.span_count}</strong> {plural(trace.span_count, "step")}
          </span>
          {trace.error_count > 0 ? (
            <span className="pill tone-bad">
              {trace.error_count} failed {plural(trace.error_count, "step")}
            </span>
          ) : (
            <span className="pill tone-good">No failed steps</span>
          )}
          <span className="muted">Started {formatDateTime(trace.started_at)}</span>
        </div>
      </div>

      <div className="tw-controls">
        {compact ? null : (
          <p className="tw-legend">Each bar is one step the agent took. Red steps failed; the run continued where it could.</p>
        )}
        <label className="check tw-filter">
          <input
            type="checkbox"
            checked={onlyFailures}
            onChange={(e) => setOnlyFailures(e.target.checked)}
            disabled={trace.error_count === 0}
          />
          <span>Show only failures</span>
        </label>
      </div>

      {rows.length === 0 ? (
        <div className="empty-box">No steps to show.</div>
      ) : (
        <ul className="tw-list">
          {rows.map((r) => (
            <SpanRow
              key={r.node.span.span_id}
              row={r}
              total={total}
              prefix={prefix}
              expanded={expanded.has(r.node.span.span_id)}
              collapsed={collapsed.has(r.node.span.span_id)}
              onToggleExpanded={() => setExpanded((s) => flip(s, r.node.span.span_id))}
              onToggleCollapsed={() => setCollapsed((s) => flip(s, r.node.span.span_id))}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
