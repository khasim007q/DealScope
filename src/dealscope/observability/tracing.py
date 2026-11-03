"""Tracing facade over OpenTelemetry with a local SQLite recorder.

When no trace store is configured the facade is a no-op so tests and scripts keep working.
Attributes are passed through `safe_attrs` so secrets, contact data and long free text never reach traces.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": False, "initialized": False, "provider": None}

_SECRET_KEY = re.compile(r"(api[_-]?key|token(?!s$)|secret|password|authorization|email|phone)", re.I)
_MAX_STR = 300


def init_tracing(
    workflow_name: str = "dealscope",
    record_to: Path | str | None = None,
) -> bool:
    """Initialize tracing once; returns whether spans are being recorded.

    A plain OpenTelemetry provider is created. When `record_to` is given, a local recorder stores each run's spans
    per case in SQLite for the UI waterfall. Without it, spans are no-ops."""
    if _state["initialized"]:
        return _state["enabled"]
    if record_to is None:
        log.info("no trace store configured; tracing disabled")
        return False
    _state["initialized"] = True
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from dealscope.observability.recorder import TraceRecorder

    provider = TracerProvider(resource=Resource.create({"service.name": workflow_name}))
    provider.add_span_processor(SimpleSpanProcessor(TraceRecorder(record_to)))
    _state.update(provider=provider, enabled=True)
    return True


def tracing_enabled() -> bool:
    """True when spans are recorded to the local trace store."""
    return bool(_state["enabled"])


def safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if value is None or _SECRET_KEY.search(key):
            continue
        if isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, list | tuple):
            out[key] = [str(v)[:80] for v in value][:20]
        else:
            out[key] = str(value)[:_MAX_STR]
    return out


class _NullSpan:
    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401 - no-op
        return None

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None

    def trace_id(self) -> str | None:
        return None

    def set_io(self, input_text: str | None = None, output_text: str | None = None) -> None:
        return None


class _SpanHandle:
    def __init__(self, span: Any) -> None:
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        for k, v in safe_attrs({key: value}).items():
            self._span.set_attribute(f"dealscope.{k}", v)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self._span.add_event(name, attributes=safe_attrs(attributes or {}))

    def record_exception(self, exc: BaseException) -> None:
        self._span.record_exception(exc)

    def set_io(self, input_text: str | None = None, output_text: str | None = None) -> None:
        """Short, non-sensitive summaries shown as the span input/output."""
        if input_text is not None:
            self._span.set_attribute("input.value", str(input_text)[:_MAX_STR])
        if output_text is not None:
            self._span.set_attribute("output.value", str(output_text)[:_MAX_STR])

    def trace_id(self) -> str | None:
        try:
            return format(self._span.get_span_context().trace_id, "032x")
        except Exception:  # pragma: no cover - defensive
            return None


@contextlib.contextmanager
def span(name: str, kind: str = "CHAIN", **attrs: Any) -> Iterator[_SpanHandle | _NullSpan]:
    """Open a named span (kinds: WORKFLOW, AGENT, CHAIN, TOOL, GUARDRAIL, LLM)."""
    provider = _state.get("provider")
    if _state["enabled"] and provider is not None:
        tracer = provider.get_tracer("dealscope")
        with tracer.start_as_current_span(name, attributes={"openinference.span.kind": kind}) as raw:
            handle = _SpanHandle(raw)
            for k, v in safe_attrs(attrs).items():
                raw.set_attribute(f"dealscope.{k}", v)
            yield handle
        return
    yield _NullSpan()


def flush() -> None:
    provider = _state.get("provider")
    if provider is not None:
        try:
            provider.force_flush()
        except Exception:  # pragma: no cover - best effort
            pass


def shutdown() -> None:
    provider = _state.get("provider")
    if provider is not None:
        try:
            provider.shutdown()
        except Exception:  # pragma: no cover - best effort
            pass
    _state.update(enabled=False, initialized=False, provider=None)
