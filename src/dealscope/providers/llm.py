"""Configurable runtime LLM adapter.

The LLM is used only to (a) choose the next investigative action from an allowlist and
(b) draft cited findings. Its output is untrusted: callers validate it against pydantic
schemas, the tool allowlist, the credit governor, and the deterministic claim verifier.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Protocol

from pydantic import BaseModel, ValidationError

from dealscope.config import Settings
from dealscope.observability import tracing

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, system: str, prompt: str, schema: type[BaseModel], *, escalate: bool = False) -> str:
        """Return a raw JSON string intended to match `schema` (caller validates)."""
        ...


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, api_key: str, model: str, escalation_model: str | None = None, fallback_models: list[str] | None = None
    ) -> None:
        from google import genai
        from google.genai import types

        # Construct after tracing.init_tracing() so neatlogs can instrument the client.
        # Bounded request time (ms); a cold model was observed to take ~45 s on the first call.
        http = types.HttpOptions(timeout=60_000)
        self._client = tracing.wrap_llm_client(genai.Client(api_key=api_key, http_options=http))
        self.model = model
        self.escalation_model = escalation_model
        self.fallback_models = list(fallback_models or [])
        self.last_model: str | None = None  # model that produced the most recent successful response
        self.tokens_used = 0  # total tokens reported by the provider across successful calls
        self.calls_made = 0
        self.sleep = time.sleep

    def generate_json(self, system: str, prompt: str, schema: type[BaseModel], *, escalate: bool = False) -> str:
        from google.genai import types

        model = self.escalation_model if (escalate and self.escalation_model) else self.model
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.1,
            response_mime_type="application/json",
            response_json_schema=gemini_schema(schema),
            max_output_tokens=8192,
        )
        chain = [model, *[m for m in self.fallback_models if m != model]]
        failures: list[str] = []
        for candidate in chain:
            try:
                text = self._call_model(candidate, prompt, config)
            except LLMError as exc:
                failures.append(f"{candidate}: {str(exc)[:120]}")
                log.warning("LLM model %s failed, trying next in chain: %s", candidate, str(exc)[:120])
                continue
            self.last_model = candidate
            return text
        raise LLMError("all models failed: " + " | ".join(failures))

    def _call_model(self, model: str, prompt: str, config: object) -> str:
        last: Exception | None = None
        for attempt in range(TRANSIENT_RETRIES + 1):
            try:
                resp = self._client.models.generate_content(model=model, contents=prompt, config=config)
            except Exception as exc:  # SDK raises several error types; normalize them
                last = exc
                delay = _retry_delay(exc, attempt)
                if attempt < TRANSIENT_RETRIES and delay is not None:
                    self.sleep(delay)
                    continue
                raise LLMError(f"gemini call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
            text = getattr(resp, "text", None)
            if not text:
                raise LLMError("gemini returned empty response")
            usage = getattr(resp, "usage_metadata", None)
            self.tokens_used += int(getattr(usage, "total_token_count", 0) or 0)
            self.calls_made += 1
            return text
        raise LLMError(f"gemini call failed: {last}")  # pragma: no cover - loop always returns or raises


TRANSIENT_RETRIES = 1


MAX_RATE_LIMIT_WAIT_S = 40.0


def _retry_delay(exc: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying, or None when the error is not worth retrying.

    429 per-minute limits carry an advised delay ("retry in 12.3s" / retryDelay "12s"); daily free-tier quota
    advises hours, which we do not wait for."""
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        m = re.search(r"retry in ([0-9.]+)s", msg) or re.search(r"retryDelay'?\"?:\s*'?\"?([0-9.]+)s", msg)
        if "h" in msg.split("retry in", 1)[-1][:12] and "retry in" in msg:
            return None  # e.g. "retry in 9h36m..." -> daily quota exhausted
        advised = float(m.group(1)) if m else 20.0
        return advised + 1.0 if advised <= MAX_RATE_LIMIT_WAIT_S else None
    if any(code in msg for code in ("503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED")):
        return 2.0 * (attempt + 1)
    return None


def gemini_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema simplified for Gemini structured output: `$defs`/`$ref` inlined,
    `anyOf [T, null]` collapsed to T, titles/defaults dropped, and array-size bounds removed — `maxItems` was observed
    to trigger 400 INVALID_ARGUMENT on gemini-3.8-flash. Bounds are still enforced by pydantic when parsing."""
    raw = schema.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            if "anyOf" in node:
                options = [o for o in node["anyOf"] if o.get("type") != "null"]
                if len(options) == 1:
                    merged = {k: v for k, v in node.items() if k != "anyOf"}
                    merged.update(options[0])
                    return walk(merged)
            return {k: walk(v) for k, v in node.items() if k not in ("title", "default", "maxItems", "minItems")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(raw)


class ScriptedProvider:
    """Deterministic provider for tests/eval: returns queued JSON strings in order."""

    name = "scripted"

    def __init__(self, responses: list[str | dict], model: str = "scripted-v1") -> None:
        self._responses = list(responses)
        self.model = model
        self.calls: list[dict[str, str]] = []

    def generate_json(self, system: str, prompt: str, schema: type[BaseModel], *, escalate: bool = False) -> str:
        self.calls.append({"system": system, "prompt": prompt, "schema": schema.__name__})
        if not self._responses:
            raise LLMUnavailable("scripted provider exhausted")
        item = self._responses.pop(0)
        return item if isinstance(item, str) else json.dumps(item)


def build_provider(settings: Settings) -> LLMProvider | None:
    """Return the configured provider, or None when no runtime key is configured."""
    if settings.llm_api_key is None:
        return None
    if settings.llm_provider.lower() in {"gemini", "google"}:
        return GeminiProvider(
            settings.llm_api_key.get_secret_value(),
            settings.llm_model,
            settings.llm_escalation_model,
            settings.llm_fallback_list,
        )
    raise LLMError(f"unsupported LLM_PROVIDER={settings.llm_provider!r}")


def parse_structured[T: BaseModel](raw: str, schema: type[T]) -> T:
    """Validate an LLM JSON string; strips markdown fences defensively."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        raise LLMError(f"structured output failed validation: {exc.error_count()} errors") from exc
