"""Gemini provider fallback chain (no network: fake SDK client)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from dealscope.providers.llm import GeminiProvider, LLMError

DAILY = Exception("429 RESOURCE_EXHAUSTED quota exceeded. Please retry in 9h12m3s.")
OVERLOADED = Exception("503 UNAVAILABLE high demand")


class Out(BaseModel):
    ok: bool


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


class _Models:
    def __init__(self, script: dict[str, list]) -> None:
        self.script = script
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        step = self.script[model].pop(0)
        if isinstance(step, Exception):
            raise step
        return _Resp(step)


def provider(script: dict[str, list], primary: str, fallbacks: list[str]) -> tuple[GeminiProvider, _Models]:
    p = GeminiProvider.__new__(GeminiProvider)  # bypass real SDK client construction
    models = _Models(script)
    p._client = type("C", (), {"models": models})()
    p.model, p.escalation_model, p.fallback_models, p.last_model = primary, None, fallbacks, None
    p.sleep = lambda s: None
    return p, models


def test_daily_quota_falls_through_to_next_model():
    p, m = provider({"a": [DAILY], "b": ['{"ok": true}']}, "a", ["b", "c"])
    assert p.generate_json("sys", "prompt", Out) == '{"ok": true}'
    assert p.last_model == "b" and m.calls == ["a", "b"]  # daily quota: no wasted retry on "a"


def test_transient_error_retried_then_next_model():
    p, m = provider({"a": [OVERLOADED, OVERLOADED], "b": ['{"ok": true}']}, "a", ["b"])
    p.generate_json("sys", "prompt", Out)
    assert m.calls == ["a", "a", "b"] and p.last_model == "b"


def test_all_models_fail_raises_with_each_reason():
    p, _ = provider({"a": [DAILY], "b": [DAILY]}, "a", ["b"])
    with pytest.raises(LLMError) as exc:
        p.generate_json("sys", "prompt", Out)
    assert "a:" in str(exc.value) and "b:" in str(exc.value)


def test_primary_success_does_not_touch_fallbacks():
    p, m = provider({"a": ['{"ok": true}']}, "a", ["b"])
    p.generate_json("sys", "prompt", Out)
    assert m.calls == ["a"] and p.last_model == "a"
