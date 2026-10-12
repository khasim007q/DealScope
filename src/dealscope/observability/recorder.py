"""Local copy of each run's trace.

The same OpenTelemetry spans that neatlogs exports are also passed to this exporter, which keeps them per trace and,
when the root span (investigation_workflow) ends, stores a sanitized copy in SQLite keyed by case. The UI renders it as
a waterfall under the same trace id that appears in the neatlogs dashboard. neatlogs has no read API in its SDK, so
this is how the flow becomes visible in the product.

Sanitization: only DealScope's own attributes and model/token/cost metadata are kept. LLM prompt and response text
(`input.value` / `output.value` on model spans) is dropped, because it can contain profile titles.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

log = logging.getLogger(__name__)

_KEEP_PREFIXES = (
    "dealscope.",
    "llm.model_name",
    "llm.token_count.",
    "llm.provider",
    "llm.cost",
    "gen_ai.usage.",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "neatlogs.cost",
    "neatlogs.llm.",
)
_ROOT_IO = ("input.value", "output.value")  # kept on the workflow root only (our own short summaries)
_MAX_VALUE = 300


_DROP_MARKERS = ("message", "content", "prompt", "completion", "input", "output")  # never keep model I/O text


def _clean(attrs: dict[str, Any], is_root: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        root_summary = is_root and k in _ROOT_IO  # our own short input/output summaries on the workflow root
        keep = k.startswith(_KEEP_PREFIXES) and not any(m in k.lower() for m in _DROP_MARKERS)
        if not (root_summary or keep):
            continue
        out[k] = v if isinstance(v, bool | int | float) else str(v)[:_MAX_VALUE]
    return out


def _hex(n: int, width: int) -> str:
    return format(n, f"0{width}x")


def serialize_trace(spans: list[ReadableSpan]) -> dict[str, Any]:
    root = next((s for s in spans if s.parent is None), spans[0])
    t0 = min(s.start_time or 0 for s in spans)
    t1 = max(s.end_time or s.start_time or 0 for s in spans)
    rows = []
    parents = {x.context.span_id: (x.parent.span_id if x.parent else None) for x in spans}

    def depth(span_id: int) -> int:
        d, cur = 0, parents.get(span_id)
        while cur is not None and d < 64:
            d, cur = d + 1, parents.get(cur)
        return d

    # Timer resolution can give a parent and its first child the same start time: break ties by tree depth.
    for s in sorted(spans, key=lambda x: (x.start_time or 0, depth(x.context.span_id))):
        attrs = dict(s.attributes or {})
        error = None
        if s.status.status_code == StatusCode.ERROR:
            error = (s.status.description or "")[:_MAX_VALUE] or None
        events = []
        for e in s.events:
            ea = dict(e.attributes or {})
            if e.name == "exception" and error is None:
                error = str(ea.get("exception.message", ""))[:_MAX_VALUE] or "exception"
            events.append(
                {
                    "name": e.name,
                    "at_ms": round(((e.timestamp or t0) - t0) / 1e6, 2),
                    "attributes": {
                        k: (v if isinstance(v, bool | int | float) else str(v)[:120])
                        for k, v in ea.items()
                        if not k.startswith("exception.stacktrace")
                    },
                }
            )
        failed = s.status.status_code == StatusCode.ERROR or any(e["name"] == "exception" for e in events)
        name, kind = s.name, str(attrs.get("openinference.span.kind", "CHAIN")).upper()
        if "generate_content" in name or kind == "LLM":
            kind = "LLM"
            model = (
                attrs.get("neatlogs.llm.model_name")
                or attrs.get("llm.model_name")
                or attrs.get("gen_ai.request.model")
                or attrs.get("gen_ai.response.model")
            )
            name = f"Gemini call ({model})" if model else "Gemini call"
        rows.append(
            {
                "span_id": _hex(s.context.span_id, 16),
                "parent_id": _hex(s.parent.span_id, 16) if s.parent else None,
                "name": name,
                "kind": kind,
                "start_ms": round(((s.start_time or t0) - t0) / 1e6, 2),
                "duration_ms": round(((s.end_time or s.start_time or t0) - (s.start_time or t0)) / 1e6, 2),
                "status": "error" if failed else "ok",
                "error": error if failed else None,
                "attributes": _clean(attrs, s is root),
                "events": events,
            }
        )
    return {
        "trace_id": _hex(root.context.trace_id, 32),
        "started_at": datetime.fromtimestamp(t0 / 1e9, tz=UTC).isoformat(),
        "duration_ms": round((t1 - t0) / 1e6, 2),
        "span_count": len(rows),
        "error_count": sum(1 for r in rows if r["status"] == "error"),
        "spans": rows,
    }


class TraceRecorder(SpanExporter):
    """Buffers finished spans per trace; persists the trace when its root span ends."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        self._buf: dict[int, list[ReadableSpan]] = {}
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for s in spans:
            tid = s.context.trace_id
            with self._lock:
                self._buf.setdefault(tid, []).append(s)
                done = s.parent is None
                batch = self._buf.pop(tid) if done else None
            if batch:
                self._persist(batch)
        return SpanExportResult.SUCCESS

    def _persist(self, spans: list[ReadableSpan]) -> None:
        root = next((s for s in spans if s.parent is None), None)
        case_id = (root.attributes or {}).get("dealscope.case_id") if root else None
        if not case_id:
            return  # not an investigation trace (e.g. a delivery probe)
        try:
            from dealscope.persistence.repository import Repository

            trace = serialize_trace(spans)
            repo = Repository(self.db_path)
            try:
                repo.save_trace(trace["trace_id"], str(case_id), trace["started_at"], json.dumps(trace))
            finally:
                repo.close()
        except Exception:  # recording must never break a run
            log.exception("failed to record trace locally")

    def shutdown(self) -> None:
        with self._lock:
            self._buf.clear()
