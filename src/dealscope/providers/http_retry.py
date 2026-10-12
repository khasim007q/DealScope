"""Bounded retry for HTTP calls.

Policy:
* Retry only 429/500/502/503/504 and connect failures (request provably not sent).
* 400/401/402/403 and other 4xx raise a mapped error immediately; no retry.
* Read timeouts / dropped connections after the request was sent raise ``UnknownOutcomeError``
  (potentially billed) and are never replayed.
* Full-jitter exponential backoff; ``Retry-After`` / ``x-ratelimit-reset`` (seconds) are honored but capped
  by ``max_delay`` and the remaining deadline. ``max_retries=2`` means at most 3 attempts.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation

import httpx

from dealscope.providers.base import (
    AuthError,
    BadRequestError,
    InsufficientCreditsError,
    ProviderError,
    RetryExhaustedError,
    UnknownOutcomeError,
    truncate,
)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def parse_credits(response: httpx.Response) -> Decimal | None:
    raw = response.headers.get("x-credits-used")
    if raw is None:
        return None
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value >= 0 else None


def error_message(response: httpx.Response, redact: Sequence[str] = ()) -> str:
    """Best-effort sanitized message from an error envelope (``{"error":{"type","message"}}``)."""
    text = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            parts = [str(err.get(k)) for k in ("type", "message") if err.get(k)]
            text = ": ".join(parts)
        elif isinstance(err, str):
            text = err
        elif body.get("message"):
            text = str(body["message"])
    if not text:
        try:
            text = response.text[:300]
        except Exception:  # noqa: BLE001 - never fail while building an error message
            text = ""
    for secret in redact:
        if secret:
            text = text.replace(secret, "***")
    return truncate(text) or f"HTTP {response.status_code}"


def _extras(response: httpx.Response) -> dict:
    return {
        "status": response.status_code,
        "request_id": response.headers.get("x-request-id"),
        "credits_used": parse_credits(response),
    }


def map_error(response: httpx.Response, redact: Sequence[str] = (), attempts: int = 1) -> ProviderError:
    status = response.status_code
    msg = f"HTTP {status}: {error_message(response, redact)}"
    extras = _extras(response)
    if status == 401:
        return AuthError(msg, code="AUTH", attempts=attempts, **extras)
    if status == 403:
        return AuthError(msg, code="PERMISSION", attempts=attempts, **extras)
    if status == 402:
        return InsufficientCreditsError(msg, attempts=attempts, **extras)
    if status == 400:
        return BadRequestError(msg, attempts=attempts, **extras)
    if status == 404:
        return ProviderError(msg, code="NOT_FOUND", attempts=attempts, **extras)
    return ProviderError(msg, code=f"HTTP_{status}", attempts=attempts, **extras)


def _header_delay(response: httpx.Response) -> float | None:
    for name in ("retry-after", "x-ratelimit-reset"):
        raw = response.headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw.strip())
        except ValueError:
            continue  # HTTP-date form of Retry-After is not parsed; fall back to jitter
        if value >= 0:
            return value
    return None


def execute_with_retry(
    send: Callable[[], httpx.Response],
    *,
    max_retries: int,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    deadline_s: float,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    on_retry: Callable[[int, str, float], None] | None = None,
    redact: Sequence[str] = (),
    clock: Callable[[], float] = time.monotonic,
) -> tuple[httpx.Response, int]:
    """Run ``send`` with bounded retries. Returns ``(response, attempts)`` for any non-error response."""
    max_retries = max(0, int(max_retries))
    started = clock()
    attempt = 0
    while True:
        attempt += 1
        response: httpx.Response | None = None
        header_delay: float | None = None
        try:
            response = send()
        except _NOT_SENT_ERRORS as exc:
            reason = type(exc).__name__
            last_detail = truncate(f"{reason}: {exc}")
        except httpx.TransportError as exc:
            # ReadTimeout / WriteTimeout / dropped connection: the request may have reached the provider.
            raise UnknownOutcomeError(
                f"{type(exc).__name__}: request may have been processed (billing unknown)",
                attempts=attempt,
            ) from exc
        else:
            if response.status_code < 400:
                return response, attempt
            if response.status_code not in RETRYABLE_STATUS:
                raise map_error(response, redact, attempt)
            reason = f"http_{response.status_code}"
            last_detail = f"HTTP {response.status_code}: {error_message(response, redact)}"
            header_delay = _header_delay(response)

        extras = _extras(response) if response is not None else {}
        if attempt > max_retries:
            raise RetryExhaustedError(f"gave up after {attempt} attempt(s): {last_detail}", attempts=attempt, **extras)
        if header_delay is not None:
            delay = min(header_delay, max_delay)
        else:
            delay = rng() * min(max_delay, base_delay * (2 ** (attempt - 1)))
        remaining = deadline_s - (clock() - started)
        if remaining <= 0 or delay >= remaining:
            raise RetryExhaustedError(
                f"retry deadline ({deadline_s}s) reached after {attempt} attempt(s): {last_detail}",
                attempts=attempt,
                **extras,
            )
        if on_retry is not None:
            on_retry(attempt, reason, delay)
        sleep(delay)
