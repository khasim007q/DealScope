"""Shared provider contracts: normalized result types, provider errors, and the DataSource protocol.

Both the live Crustdata client and the synthetic fixture source return ``ProviderResult`` objects whose
``items`` are already validated into the domain payload models. Raw provider JSON is hashed, never stored.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from dealscope.domain.enums import EvidenceKind
from dealscope.domain.models import CompanyProfilePayload, JobPostingPayload, PersonHistoryPayload

MAX_MESSAGE_CHARS = 300


def truncate(text: object, limit: int = MAX_MESSAGE_CHARS) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """Base class for every provider failure. Messages are sanitized (truncated, key-redacted)."""

    default_code = "PROVIDER_ERROR"
    default_retryable = False
    default_billable_unknown = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        retryable: bool | None = None,
        billable_unknown: bool | None = None,
        attempts: int = 1,
        request_id: str | None = None,
        credits_used: Decimal | None = None,
    ) -> None:
        super().__init__(truncate(message))
        self.code = code or self.default_code
        self.status = status
        self.retryable = self.default_retryable if retryable is None else retryable
        self.billable_unknown = self.default_billable_unknown if billable_unknown is None else billable_unknown
        self.attempts = attempts
        self.request_id = request_id
        self.credits_used = credits_used


class AuthError(ProviderError):
    """401 (code AUTH) / 403 (code PERMISSION). Never retried."""

    default_code = "AUTH"


class BadRequestError(ProviderError):
    """400 or a locally rejected request. Never retried."""

    default_code = "BAD_REQUEST"


class InsufficientCreditsError(ProviderError):
    """402. Terminal."""

    default_code = "INSUFFICIENT_CREDITS"


class RetryExhaustedError(ProviderError):
    """429/5xx/connect failures persisted through every permitted attempt (or the deadline)."""

    default_code = "RETRY_EXHAUSTED"


class UnknownOutcomeError(ProviderError):
    """The request may have been sent but no usable response arrived: billing is unknown."""

    default_code = "UNKNOWN_OUTCOME"
    default_billable_unknown = True


class SchemaError(ProviderError):
    """Response JSON did not match the expected shape."""

    default_code = "SCHEMA"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

Payload = CompanyProfilePayload | PersonHistoryPayload | JobPostingPayload


@dataclass(frozen=True)
class NormalizedItem:
    kind: EvidenceKind
    subject_domain: str
    payload: Payload
    source_url: str | None
    source_record_id: str | None
    valid_from: str | None
    valid_to: str | None
    field_coverage: list[str]
    raw_hash: str
    dedup_key: str
    independence_group: str


@dataclass
class ProviderResult:
    provider: Literal["crustdata", "fixture"]
    endpoint: str
    request_body: dict
    items: list[NormalizedItem]
    result_count: int
    credits_used: Decimal | None
    request_id: str | None
    attempts: int
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class DataSource(Protocol):
    provider_name: str

    def enrich_company(self, domain: str) -> ProviderResult: ...

    def search_people(
        self,
        target_domain: str,
        role_group: str,
        relationship: str,
        competitor_domain: str | None,
        limit: int,
    ) -> ProviderResult: ...

    def search_jobs(self, domain: str, role_terms: list[str], since_date: date, limit: int) -> ProviderResult: ...


# ---------------------------------------------------------------------------
# Helpers shared by both sources
# ---------------------------------------------------------------------------


def canonical_hash(record: object) -> str:
    """sha256 of the canonical JSON form of a raw record (sorted keys, compact separators)."""
    blob = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def payload_coverage(payload: BaseModel) -> list[str]:
    """Names of payload fields that actually carry a value (0 and False count as present)."""
    present: list[str] = []
    for name, value in payload.model_dump().items():
        if value is None or value == {} or value == [] or value == "":
            continue
        present.append(name)
    return present


def person_ref_for(provider_person_id: object) -> str:
    return "p-" + hashlib.sha256(f"crustdata:{provider_person_id}".encode()).hexdigest()[:16]
