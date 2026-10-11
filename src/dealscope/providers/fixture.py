"""Synthetic data source with the same interface as the live Crustdata client.

Fixture file format (``fixtures/scenario_a.json`` / ``scenario_b.json``)::

    {
      "mode": "synthetic",
      "synthetic_banner": "SYNTHETIC DEMO DATA - NOT A REAL COMPANY ASSESSMENT",
      "case": {"case_id", "target_domain", "competitor_domains", "deal_thesis", "lookback_months"},
      "companies": {"<domain>": {<CompanyProfilePayload fields>, "source_record_id"?}},
      "people": [{"person_ref": "p-syn-...", "subject_domain"?: <defaults to case.target_domain>,
                  "relationship_tags": ["past_target_employment" | "current_target_employment"],
                  <PersonHistoryPayload fields>}],
      "jobs": {"<domain>": [{<JobPostingPayload fields>, "source_record_id"?}]}
    }

The legacy evidence-list format (``fixtures/synthetic_case.json``: ``company_headcount`` /
``peer_headcount`` / ``person_history`` / ``job_posting`` evidence entries) is converted on load.

Queries filter the data the way the live API would (role_group, relationship, competitor current employer,
since_date, role_terms, limit). ``faults`` injects failures per method (``{"enrich_company": [503, 503]}``,
status ints, ``"timeout"`` or ``"connect"``), consumed one per attempt and routed through
``execute_with_retry`` with fake ``httpx.Response`` objects, so retry/backoff/error mapping matches live.

Fixture calls are free: ``credits_used`` is always ``None``. The orchestrator must treat any credit figure
for fixture calls as simulated estimates, never as actual spend.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from dealscope.domain.enums import EvidenceKind
from dealscope.domain.models import (
    CompanyProfilePayload,
    JobPostingPayload,
    PersonHistoryPayload,
)
from dealscope.providers.base import (
    NormalizedItem,
    ProviderResult,
    SchemaError,
    canonical_hash,
    payload_coverage,
)
from dealscope.providers.classify import JOB_ROLE_TERM_TITLES, classify_title
from dealscope.providers.crustdata import (
    ENRICH_PATH,
    JOB_SEARCH_PATH,
    MAX_JOB_LIMIT,
    MAX_PEOPLE_LIMIT,
    PERSON_SEARCH_PATH,
    build_enrich_body,
    build_job_search_body,
    build_person_search_body,
)
from dealscope.providers.http_retry import execute_with_retry

SYNTHETIC_BANNER = "SYNTHETIC DEMO DATA - NOT A REAL COMPANY ASSESSMENT"
_PERSON_FIELDS = set(PersonHistoryPayload.model_fields)
_JOB_FIELDS = set(JobPostingPayload.model_fields)
_COMPANY_FIELDS = set(CompanyProfilePayload.model_fields)
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _convert_legacy(doc: dict) -> dict:
    """Convert the original evidence-list fixture into the scenario format."""
    companies: dict[str, dict] = {}
    people: list[dict] = []
    jobs: dict[str, list[dict]] = {}
    target = doc.get("case", {}).get("target_domain")
    for ev in doc.get("evidence", []):
        kind = ev.get("kind")
        domain = ev.get("subject_domain")
        p = ev.get("normalized_payload", {}) or {}
        if kind in ("company_headcount", "peer_headcount") and domain:
            rec: dict[str, Any] = {"name": None, "domain": domain, "source_record_id": ev.get("evidence_id")}
            if "total_headcount" in p:
                rec["total_headcount"] = p["total_headcount"]
            if "total_growth_6m_pct" in p:
                rec["total_growth_pct"] = {"6m": float(p["total_growth_6m_pct"])}
            if "engineering_growth_6m_pct" in p:
                rec["engineering_growth_pct"] = {"6m": float(p["engineering_growth_6m_pct"])}
            companies[domain] = rec
        elif kind == "person_history" and domain:
            people.append(
                {
                    "person_ref": f"p-syn-{ev.get('evidence_id', len(people))}",
                    "subject_domain": domain or target,
                    "relationship_tags": ["past_target_employment"],
                    "role_group": p.get("role_group", "other_technical"),
                    "capability": p.get("capability", "general_engineering"),
                    "target_end": p.get("employment_end_month"),
                    "currently_at_target": False,
                    "current_employer_domain": p.get("current_employer_domain"),
                }
            )
        elif kind == "job_posting" and domain:
            title = p.get("title", "")
            group, capability = classify_title(title)
            jobs.setdefault(domain, []).append(
                {
                    "source_record_id": ev.get("evidence_id"),
                    "title": title,
                    "role_group": group,
                    "capability": capability,
                    "date_added": p.get("date_added"),
                    "date_updated": p.get("date_updated"),
                    "reposted": p.get("reposted"),
                    "number_of_openings": p.get("number_of_openings"),
                    "url": p.get("url"),
                    "category": p.get("category", "Engineering"),
                }
            )
    return {
        "mode": doc.get("mode", "synthetic"),
        "synthetic_banner": doc.get("synthetic_banner", SYNTHETIC_BANNER),
        "case": doc.get("case", {}),
        "companies": companies,
        "people": people,
        "jobs": jobs,
        "_legacy": True,
    }


class FixtureDataSource:
    provider_name = "fixture"

    def __init__(
        self,
        path: Path,
        faults: dict[str, list[int | str]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
        *,
        deadline_s: float = 60,
        on_retry: Callable[[int, str, float], None] | None = None,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.path = Path(path)
        self._faults: dict[str, list[int | str]] = {k: list(v) for k, v in (faults or {}).items()}
        self._sleep = sleep
        self._max_retries = max_retries
        self._deadline_s = deadline_s
        self._on_retry = on_retry
        self._rng = rng
        self._load()

    # -- loading -----------------------------------------------------------

    def _load(self) -> None:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SchemaError(f"cannot read fixture {self.path.name}: {exc}", code="FIXTURE") from exc
        if not isinstance(doc, dict):
            raise SchemaError("fixture root must be an object", code="FIXTURE")
        if "evidence" in doc and "companies" not in doc:
            doc = _convert_legacy(doc)
        self.legacy = bool(doc.get("_legacy"))
        self.synthetic_banner: str = doc.get("synthetic_banner") or SYNTHETIC_BANNER
        self.case: dict = doc.get("case", {}) or {}
        self._default_target: str | None = self.case.get("target_domain")
        try:
            self._companies: dict[str, tuple[dict, CompanyProfilePayload]] = {}
            for domain, rec in (doc.get("companies") or {}).items():
                fields = {k: v for k, v in rec.items() if k in _COMPANY_FIELDS}
                fields.setdefault("domain", domain)
                self._companies[domain] = (rec, CompanyProfilePayload(**fields))
            self._people: list[tuple[dict, PersonHistoryPayload]] = []
            for rec in doc.get("people") or []:
                self._people.append(
                    (rec, PersonHistoryPayload(**{k: v for k, v in rec.items() if k in _PERSON_FIELDS}))
                )
            self._jobs: dict[str, list[tuple[dict, JobPostingPayload]]] = {}
            for domain, recs in (doc.get("jobs") or {}).items():
                self._jobs[domain] = [
                    (rec, JobPostingPayload(**{k: v for k, v in rec.items() if k in _JOB_FIELDS})) for rec in recs
                ]
        except (ValidationError, TypeError, AttributeError) as exc:
            raise SchemaError(f"fixture {self.path.name} is malformed: {exc}", code="FIXTURE") from exc

    # -- fault injection through the shared retry path -----------------------

    def _guard(self, method: str, endpoint: str) -> int:
        request = httpx.Request("POST", f"https://fixture.invalid{endpoint}")

        def send() -> httpx.Response:
            queue = self._faults.get(method)
            if not queue:
                return httpx.Response(200, json={}, request=request)
            fault = queue.pop(0)
            if fault == "timeout":
                raise httpx.ReadTimeout("injected read timeout", request=request)
            if fault == "connect":
                raise httpx.ConnectError("injected connect error", request=request)
            status = int(fault)
            return httpx.Response(
                status,
                json={"error": {"type": "injected_fault", "message": f"injected fault {status}"}},
                request=request,
            )

        _, attempts = execute_with_retry(
            send,
            max_retries=self._max_retries,
            deadline_s=self._deadline_s,
            sleep=self._sleep,
            rng=self._rng,
            on_retry=self._on_retry,
        )
        return attempts

    def _result(
        self, endpoint: str, body: dict, items: list[NormalizedItem], attempts: int, notes: list[str]
    ) -> ProviderResult:
        if self.legacy:
            notes.append("legacy fixture format converted")
        if not items:
            notes.insert(0, "no match")
        return ProviderResult(
            provider="fixture",
            endpoint=endpoint,
            request_body=body,
            items=items,
            result_count=len(items),
            credits_used=None,
            request_id=None,
            attempts=attempts,
            notes=notes,
        )

    # -- DataSource --------------------------------------------------------

    def enrich_company(self, domain: str) -> ProviderResult:
        body = build_enrich_body(domain)
        wanted = body["domains"][0]
        attempts = self._guard("enrich_company", ENRICH_PATH)
        items: list[NormalizedItem] = []
        if wanted in self._companies:
            rec, payload = self._companies[wanted]
            items.append(
                NormalizedItem(
                    kind=EvidenceKind.COMPANY_PROFILE,
                    subject_domain=wanted,
                    payload=payload,
                    source_url=None,
                    source_record_id=rec.get("source_record_id"),
                    valid_from=None,
                    valid_to=None,
                    field_coverage=payload_coverage(payload),
                    raw_hash=canonical_hash(rec),
                    dedup_key=f"company:{wanted}",
                    independence_group=f"fixture:company_enrich:{wanted}",
                )
            )
        return self._result(ENRICH_PATH, body, items, attempts, [])

    def search_people(
        self,
        target_domain: str,
        role_group: str,
        relationship: str,
        competitor_domain: str | None,
        limit: int,
    ) -> ProviderResult:
        body = build_person_search_body(target_domain, role_group, relationship, competitor_domain, limit)
        target = body["filters"]["conditions"][0]["conditions"][0]["value"]
        competitor = competitor_domain and body["filters"]["conditions"][-1]["value"]
        cap = body["limit"]
        attempts = self._guard("search_people", PERSON_SEARCH_PATH)
        matched = [
            (rec, payload)
            for rec, payload in self._people
            if (rec.get("subject_domain") or self._default_target) == target
            and relationship in (rec.get("relationship_tags") or [])
            and payload.role_group == role_group
            and (not competitor or payload.current_employer_domain == competitor)
        ]
        matched.sort(key=lambda rp: rp[1].person_ref)
        items = [
            NormalizedItem(
                kind=EvidenceKind.PERSON_HISTORY,
                subject_domain=target,
                payload=payload,
                source_url=None,
                source_record_id=payload.person_ref,
                valid_from=payload.target_start,
                valid_to=payload.target_end,
                field_coverage=payload_coverage(payload),
                raw_hash=canonical_hash(rec),
                dedup_key=f"person:{payload.person_ref}:{target}:{relationship}",
                independence_group=f"fixture:person:{payload.person_ref}",
            )
            for rec, payload in matched[: min(cap, MAX_PEOPLE_LIMIT)]
        ]
        notes = []
        if len(matched) > len(items):
            notes.append(f"single page only: {len(items)} of {len(matched)} matching profiles returned")
        return self._result(PERSON_SEARCH_PATH, body, items, attempts, notes)

    def search_jobs(self, domain: str, role_terms: list[str], since_date: date, limit: int) -> ProviderResult:
        body = build_job_search_body(domain, role_terms, since_date, limit)
        clean = body["filters"]["conditions"][0]["value"]
        cap = min(body["limit"], MAX_JOB_LIMIT)
        title_words = [_words(t) for term in role_terms for t in JOB_ROLE_TERM_TITLES[term]]
        attempts = self._guard("search_jobs", JOB_SEARCH_PATH)
        matched: list[tuple[dict, JobPostingPayload]] = []
        for rec, payload in self._jobs.get(clean, []):
            if payload.category is not None and payload.category.lower() != "engineering":
                continue
            if payload.date_added is None or date.fromisoformat(payload.date_added[:10]) < since_date:
                continue
            words = _words(payload.title)
            if not any(tw <= words for tw in title_words):
                continue
            matched.append((rec, payload))
        matched.sort(key=lambda rp: rp[1].date_added or "", reverse=True)
        items = []
        for rec, payload in matched[:cap]:
            record_id = rec.get("source_record_id")
            dedup = f"job:{record_id or payload.url or f'{payload.title}|{payload.date_added}'}"
            items.append(
                NormalizedItem(
                    kind=EvidenceKind.JOB_POSTING,
                    subject_domain=clean,
                    payload=payload,
                    source_url=payload.url,
                    source_record_id=record_id,
                    valid_from=payload.date_added,
                    valid_to=None,
                    field_coverage=payload_coverage(payload),
                    raw_hash=canonical_hash(rec),
                    dedup_key=dedup,
                    independence_group=f"fixture:job:{clean}",
                )
            )
        notes = [f"{len(matched) - len(items)} further matching posting(s) beyond limit"] if len(matched) > cap else []
        return self._result(JOB_SEARCH_PATH, body, items, attempts, notes)
