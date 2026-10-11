"""neatlogs instrumentation behind a tiny facade.

When NEATLOGS_API_KEY is absent the facade becomes a no-op so local/fixture runs keep working,
and the UI reports observability as disconnected. Attributes are passed through `safe_attrs`
so secrets, contact data and long free text never reach traces.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": False, "initialized": False}

_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password|authorization|email|phone)", re.I)
_MAX_STR = 300


def init_tracing(api_key: str | None, workflow_name: str = "dealscope", tags: list[str] | None = None) -> bool:
    """Initialize neatlogs once. Must run before constructing wrapped LLM clients."""
    if _state["initialized"]:
        return _state["enabled"]
    _state["initialized"] = True
    if not api_key:
        log.info("neatlogs not configured; tracing disabled")
        return False
    import neatlogs

    neatlogs.init(api_key=api_key, workflow_name=workflow_name, tags=tags or ["dealscope", "neatHack"])
    _state["enabled"] = True
    return True


def tracing_enabled() -> bool:
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

    def trace_id(self) -> str | None:
        try:
            return format(self._span.get_span_context().trace_id, "032x")
        except Exception:  # pragma: no cover - defensive
            return None


@contextlib.contextmanager
def span(name: str, kind: str = "CHAIN", **attrs: Any) -> Iterator[_SpanHandle | _NullSpan]:
    """Open a named span (kinds: WORKFLOW, AGENT, CHAIN, TOOL, GUARDRAIL)."""
    if not _state["enabled"]:
        yield _NullSpan()
        return
    import neatlogs

    with neatlogs.trace(name, kind=kind) as raw:
        handle = _SpanHandle(raw)
        for k, v in safe_attrs(attrs).items():
            raw.set_attribute(f"dealscope.{k}", v)
        yield handle


def wrap_llm_client(client: Any) -> Any:
    if not _state["enabled"]:
        return client
    import neatlogs

    return neatlogs.wrap(client)


def flush() -> None:
    if _state["enabled"]:
        import neatlogs

        neatlogs.flush()


def shutdown() -> None:
    if _state["enabled"]:
        import neatlogs

        neatlogs.flush()
        neatlogs.shutdown()
        _state["enabled"] = False
        _state["initialized"] = False
