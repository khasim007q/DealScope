import httpx
import pytest

from dealscope.providers.base import (
    AuthError,
    BadRequestError,
    InsufficientCreditsError,
    ProviderError,
    RetryExhaustedError,
    UnknownOutcomeError,
)
from dealscope.providers.http_retry import execute_with_retry, parse_credits


def seq(*steps):
    """Return a send() that yields responses/raises exceptions in order; records call count."""
    calls = {"n": 0}
    req = httpx.Request("POST", "https://x.invalid/a")

    def send():
        step = steps[min(calls["n"], len(steps) - 1)]
        calls["n"] += 1
        if isinstance(step, Exception):
            raise step
        status, headers = step if isinstance(step, tuple) else (step, {})
        return httpx.Response(
            status, json={"error": {"type": "t", "message": f"m{status}"}}, headers=headers, request=req
        )

    return send, calls


def run(send, **kw):
    sleeps: list[float] = []
    events: list[tuple] = []
    kw.setdefault("max_retries", 2)
    kw.setdefault("deadline_s", 60)
    result = execute_with_retry(send, sleep=sleeps.append, rng=lambda: 0.5, on_retry=lambda *a: events.append(a), **kw)
    return result, sleeps, events


def test_success_first_try():
    send, calls = seq(200)
    (resp, attempts), sleeps, events = run(send)
    assert resp.status_code == 200 and attempts == 1 and calls["n"] == 1 and sleeps == [] and events == []


def test_503_503_200_succeeds_with_bounded_backoff():
    send, calls = seq(503, 503, 200)
    (resp, attempts), sleeps, events = run(send)
    assert attempts == 3 and calls["n"] == 3
    assert sleeps == [0.5 * 0.5 * 1, 0.5 * 0.5 * 2]  # full jitter: rng * base * 2**(n-1)
    assert all(0 <= s <= 8.0 for s in sleeps)
    assert [e[0] for e in events] == [1, 2] and events[0][1] == "http_503"


def test_exhaustion_after_exactly_three_sends():
    send, calls = seq(503)
    with pytest.raises(RetryExhaustedError) as ei:
        run(send)
    assert calls["n"] == 3 and ei.value.attempts == 3 and ei.value.status == 503
    assert "m503" in str(ei.value)


def test_max_retries_zero_means_single_attempt():
    send, calls = seq(503)
    with pytest.raises(RetryExhaustedError):
        run(send, max_retries=0)
    assert calls["n"] == 1


def test_rate_limit_header_honored_and_capped():
    send, _ = seq((429, {"x-ratelimit-reset": "3"}), (429, {"x-ratelimit-reset": "300"}), 200)
    (_, attempts), sleeps, _ = run(send)
    assert attempts == 3 and sleeps == [3.0, 8.0]


def test_retry_after_header_honored():
    send, _ = seq((429, {"retry-after": "2"}), 200)
    _, sleeps, _ = run(send)
    assert sleeps == [2.0]


def test_deadline_stops_retrying():
    clock_values = iter([0.0, 5.0, 50.0, 100.0])
    send, calls = seq((429, {"retry-after": "8"}))
    with pytest.raises(RetryExhaustedError) as ei:
        execute_with_retry(send, max_retries=2, deadline_s=10, sleep=lambda s: None, clock=lambda: next(clock_values))
    assert calls["n"] == 1 and "deadline" in str(ei.value)


@pytest.mark.parametrize(
    ("status", "exc", "code"),
    [
        (401, AuthError, "AUTH"),
        (403, AuthError, "PERMISSION"),
        (400, BadRequestError, "BAD_REQUEST"),
        (402, InsufficientCreditsError, "INSUFFICIENT_CREDITS"),
        (404, ProviderError, "NOT_FOUND"),
    ],
)
def test_permanent_errors_never_retry(status, exc, code):
    send, calls = seq(status)
    with pytest.raises(exc) as ei:
        run(send)
    assert calls["n"] == 1 and ei.value.code == code and ei.value.status == status
    assert ei.value.retryable is False and ei.value.billable_unknown is False


def test_connect_error_retried_then_succeeds():
    req = httpx.Request("POST", "https://x.invalid/a")
    send, calls = seq(httpx.ConnectError("boom", request=req), 200)
    (_, attempts), sleeps, events = run(send)
    assert attempts == 2 and len(sleeps) == 1 and events[0][1] == "ConnectError"


def test_connect_errors_exhaust():
    req = httpx.Request("POST", "https://x.invalid/a")
    send, calls = seq(httpx.ConnectTimeout("boom", request=req))
    with pytest.raises(RetryExhaustedError) as ei:
        run(send)
    assert calls["n"] == 3 and ei.value.billable_unknown is False


def test_read_timeout_is_unknown_outcome_without_retry():
    req = httpx.Request("POST", "https://x.invalid/a")
    send, calls = seq(httpx.ReadTimeout("slow", request=req))
    with pytest.raises(UnknownOutcomeError) as ei:
        run(send)
    assert calls["n"] == 1 and ei.value.billable_unknown is True


def test_dropped_connection_is_unknown_outcome():
    req = httpx.Request("POST", "https://x.invalid/a")
    send, calls = seq(httpx.RemoteProtocolError("dropped", request=req))
    with pytest.raises(UnknownOutcomeError):
        run(send)
    assert calls["n"] == 1


def test_long_error_message_is_truncated_and_redacted():
    req = httpx.Request("POST", "https://x.invalid/a")
    body = {"error": {"type": "unauthorized", "message": "bad key sk-secret " + "x" * 1000}}
    send = lambda: httpx.Response(401, json=body, request=req)  # noqa: E731
    with pytest.raises(AuthError) as ei:
        execute_with_retry(send, max_retries=2, deadline_s=5, redact=("sk-secret",))
    assert len(str(ei.value)) <= 300 and "sk-secret" not in str(ei.value)


def test_parse_credits():
    def r(v):
        return httpx.Response(200, headers={} if v is None else {"X-Credits-Used": v})

    assert str(parse_credits(r("0.03"))) == "0.03"
    assert parse_credits(r(None)) is None
    assert parse_credits(r("abc")) is None
    assert parse_credits(r("-1")) is None
