"""Live Crustdata client (API version 2025-11-01) with normalization into DealScope payloads.

Endpoint behaviour follows docs/10-crustdata-api-reference.md exactly. Raw provider JSON is hashed
(``raw_hash``) and discarded; only allowlisted payload fields are kept. No contact data is ever requested.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from dealscope.domain.enums import EvidenceKind
from dealscope.domain.models import (
    CompanyProfilePayload,
    JobPostingPayload,
    PersonHistoryPayload,
    normalize_domain,
)
from dealscope.providers.base import (
    BadRequestError,
    NormalizedItem,
    ProviderError,
    ProviderResult,
    SchemaError,
    canonical_hash,
    payload_coverage,
    person_ref_for,
    truncate,
)
from dealscope.providers.classify import JOB_ROLE_TERM_TITLES, PERSON_ROLE_GROUP_TITLES, classify_title
from dealscope.providers.http_retry import execute_with_retry, parse_credits

log = logging.getLogger(__name__)

PROVIDER = "crustdata"
ENRICH_PATH = "/company/enrich"
PERSON_SEARCH_PATH = "/person/search"
JOB_SEARCH_PATH = "/job/search"
IDENTIFY_PATH = "/company/identify"  # free

MAX_PEOPLE_LIMIT = 100
MAX_JOB_LIMIT = 50

COMPANY_FIELDS = ["basic_info", "headcount", "hiring", "funding"]
PERSON_FIELDS = [
    "crustdata_person_id",
    "experience.employment_details.current",
    "experience.employment_details.past",
]
JOB_FIELDS = [
    "crustdata_job_id",
    "job_details.title",
    "job_details.category",
    "job_details.url",
    "job_details.reposted_job",
    "job_details.number_of_openings",
    "metadata.date_added",
    "metadata.date_updated",
]

_GROWTH_KEY_MAP = {"mom": "1m", "qoq": "3m", "six_months": "6m", "yoy": "12m", "two_years": "24m"}
_ENG_GROWTH_MONTHS = {"3m": 3, "6m": 6, "12m": 12}
_ENG_TOLERANCE_DAYS = 45

_EMP = "experience.employment_details"
_RELATIONSHIP_PATH = {"past_target_employment": "past", "current_target_employment": "current"}


# ---------------------------------------------------------------------------
# Request builders (also used by the fixture source so bodies are identical)
# ---------------------------------------------------------------------------


def _clean_domain(raw: str) -> str:
    try:
        return normalize_domain(raw)
    except ValueError as exc:
        raise BadRequestError(f"invalid domain: {exc}", code="INVALID_DOMAIN") from exc


def build_enrich_body(domain: str) -> dict:
    return {"domains": [_clean_domain(domain)], "fields": list(COMPANY_FIELDS), "exact_match": True}


def build_person_search_body(
    target_domain: str,
    role_group: str,
    relationship: str,
    competitor_domain: str | None,
    limit: int,
) -> dict:
    if role_group not in PERSON_ROLE_GROUP_TITLES:
        raise BadRequestError(f"unsupported role_group: {role_group!r}", code="INVALID_ROLE_GROUP")
    if relationship not in _RELATIONSHIP_PATH:
        raise BadRequestError(f"unsupported relationship: {relationship!r}", code="INVALID_RELATIONSHIP")
    target = _clean_domain(target_domain)
    stage = _RELATIONSHIP_PATH[relationship]
    same_entry = {
        "op": "and",
        "conditions": [
            {"field": f"{_EMP}.{stage}.company_website_domain", "type": "=", "value": target},
            {
                "op": "or",
                "conditions": [
                    {"field": f"{_EMP}.{stage}.title", "type": "[.]", "value": title}
                    for title in PERSON_ROLE_GROUP_TITLES[role_group]
                ],
            },
        ],
    }
    conditions: list[dict] = [same_entry]
    if competitor_domain:
        conditions.append(
            {
                "field": f"{_EMP}.current.company_website_domain",
                "type": "=",
                "value": _clean_domain(competitor_domain),
            }
        )
    return {
        "filters": {"op": "all_of", "conditions": conditions},
        "fields": list(PERSON_FIELDS),
        "sorts": [{"field": "crustdata_person_id", "order": "asc"}],
        "limit": max(1, min(int(limit), MAX_PEOPLE_LIMIT)),
    }


def build_job_search_body(domain: str, role_terms: list[str], since_date: date, limit: int) -> dict:
    unknown = [t for t in role_terms if t not in JOB_ROLE_TERM_TITLES]
    if unknown or not role_terms:
        raise BadRequestError(f"unsupported role_terms: {unknown or role_terms!r}", code="INVALID_ROLE_TERMS")
    titles: list[str] = []
    for term in role_terms:
        for title in JOB_ROLE_TERM_TITLES[term]:
            if title not in titles:
                titles.append(title)
    return {
        "filters": {
            "op": "and",
            "conditions": [
                {"field": "company.basic_info.primary_domain", "type": "=", "value": _clean_domain(domain)},
                {"field": "job_details.category", "type": "=", "value": "Engineering"},
                {"field": "metadata.date_added", "type": "=>", "value": since_date.isoformat()},
                {
                    "op": "or",
                    "conditions": [{"field": "job_details.title", "type": "(.)", "value": t} for t in titles],
                },
            ],
        },
        "fields": list(JOB_FIELDS),
        "sorts": [{"field": "metadata.date_added", "order": "desc"}],
        "limit": max(1, min(int(limit), MAX_JOB_LIMIT)),
    }


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    return None


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _host(value: Any) -> str | None:
    text = _str(value)
    if text is None:
        return None
    try:
        return normalize_domain(text)
    except ValueError:
        return None


def _date_str(value: Any) -> str | None:
    text = _str(value)
    if text is None:
        return None
    if len(text) > 10 and text[10] in " T":
        return text[:10]
    return text


def _parse_date(value: Any) -> date | None:
    text = _str(value)
    if text is None:
        return None
    for candidate in (text, text[:10], text[:7] + "-01"):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None


def _months_before(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def _series_points(series: Any) -> list[tuple[date, int]]:
    points: list[tuple[date, int]] = []
    for entry in _as_list(series):
        d = _parse_date(_as_dict(entry).get("date"))
        n = _int(_as_dict(entry).get("employee_count"))
        if d is not None and n is not None:
            points.append((d, n))
    points.sort(key=lambda p: p[0])
    return points


def _pick_engineering_key(mapping: dict) -> str | None:
    keys = [k for k in mapping if isinstance(k, str) and "engineering" in k.lower()]
    if not keys:
        return None
    exact = [k for k in keys if k.strip().lower() == "engineering"]
    return exact[0] if exact else sorted(keys, key=lambda k: (len(k), k))[0]


def derive_engineering_growth(points: list[tuple[date, int]]) -> dict[str, float]:
    """Growth % of the latest point vs the nearest earlier point N months back (<=45 days of slack)."""
    if not points:
        return {}
    latest_date, latest_count = points[-1]
    growth: dict[str, float] = {}
    for label, months in _ENG_GROWTH_MONTHS.items():
        target = _months_before(latest_date, months)
        earlier = [p for p in points[:-1] if p[0] <= target and (target - p[0]).days <= _ENG_TOLERANCE_DAYS]
        if not earlier:
            continue
        _, base = max(earlier, key=lambda p: p[0])
        if base > 0:
            growth[label] = round((latest_count - base) / base * 100.0, 2)
    return growth


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_company(company_data: dict, domain: str, notes: list[str]) -> NormalizedItem:
    basic = _as_dict(company_data.get("basic_info"))
    headcount = _as_dict(company_data.get("headcount"))
    hiring = _as_dict(company_data.get("hiring"))
    funding = _as_dict(company_data.get("funding"))

    growth: dict[str, float] = {}
    for src_key, label in _GROWTH_KEY_MAP.items():
        value = _num(_as_dict(headcount.get("growth_percent")).get(src_key))
        if value is not None:
            growth[label] = value

    eng_headcount: int | None = None
    eng_growth: dict[str, float] = {}
    by_function = _as_dict(_as_dict(headcount.get("by_function_timeseries")).get("CURRENT_FUNCTION"))
    key = _pick_engineering_key(by_function)
    if key is not None:
        points = _series_points(by_function[key])
        if points:
            eng_headcount = points[-1][1]
            eng_growth = derive_engineering_growth(points)
            notes.append(f"engineering series key used: {key!r} (by_function_timeseries.CURRENT_FUNCTION)")
            if eng_growth:
                notes.append("engineering growth derived from by_function_timeseries")
            else:
                notes.append("engineering series present but too short to derive growth")
    if eng_headcount is None:
        by_role = _as_dict(headcount.get("by_role_absolute"))
        role_key = _pick_engineering_key(by_role)
        if role_key is not None and _int(by_role[role_key]) is not None:
            eng_headcount = _int(by_role[role_key])
            notes.append(f"engineering headcount from by_role_absolute key {role_key!r}")

    industry = None
    for entry in _as_list(basic.get("industries")):
        industry = _str(entry) or _str(_as_dict(entry).get("name"))
        if industry:
            break

    locations = _as_dict(company_data.get("locations"))
    payload = CompanyProfilePayload(
        name=_str(basic.get("name")),
        domain=domain,
        total_headcount=_int(headcount.get("total")),
        total_growth_pct=growth,
        engineering_headcount=eng_headcount,
        engineering_growth_pct=eng_growth,
        job_openings_count=_int(hiring.get("openings_count")),
        funding_total_usd=_num(funding.get("total_investment_usd")),
        industry=industry,
        hq_country=_str(locations.get("country")) or _str(locations.get("hq_country")),
    )
    record_id = company_data.get("crustdata_company_id")
    return NormalizedItem(
        kind=EvidenceKind.COMPANY_PROFILE,
        subject_domain=domain,
        payload=payload,
        source_url=None,
        source_record_id=str(record_id) if record_id is not None else None,
        valid_from=None,
        valid_to=None,
        field_coverage=payload_coverage(payload),
        raw_hash=canonical_hash(company_data),
        dedup_key=f"company:{domain}",
        independence_group=f"crustdata:company_enrich:{domain}",
    )


def _entry_sort_key(entry: dict) -> str:
    return _date_str(entry.get("end_date")) or _date_str(entry.get("start_date")) or ""


def normalize_person(
    profile: dict, target_domain: str, relationship: str, role_group: str | None = None
) -> NormalizedItem | None:
    """Return None when the profile lacks an id or any employment entry at the target (never invented)."""
    person_id = profile.get("crustdata_person_id")
    if person_id is None:
        return None
    employment = _as_dict(_as_dict(profile.get("experience")).get("employment_details"))
    current = [e for e in _as_list(employment.get("current")) if isinstance(e, dict)]
    past = [e for e in _as_list(employment.get("past")) if isinstance(e, dict)]
    stage_entries = current if relationship == "current_target_employment" else past
    at_target = [e for e in stage_entries if _host(e.get("company_website")) == target_domain]
    if not at_target:
        return None
    preferred = [e for e in at_target if role_group and classify_title(_str(e.get("title")))[0] == role_group]
    entry = max(preferred or at_target, key=_entry_sort_key)

    title = _str(entry.get("title"))
    group, capability = classify_title(title)
    is_current = relationship == "current_target_employment"
    currently = True if is_current else any(_host(e.get("company_website")) == target_domain for e in current)
    employer = current[0] if current else {}
    ref = person_ref_for(person_id)
    start = _date_str(entry.get("start_date"))
    end = None if is_current else _date_str(entry.get("end_date"))

    payload = PersonHistoryPayload(
        person_ref=ref,
        role_group=group,
        capability=capability,
        title_at_target=title,
        seniority=_str(entry.get("seniority_level")),
        target_start=start,
        target_end=end,
        currently_at_target=currently,
        current_employer_name=_str(employer.get("name")),
        current_employer_domain=_host(employer.get("company_website")),
        current_title=_str(employer.get("title")),
    )
    return NormalizedItem(
        kind=EvidenceKind.PERSON_HISTORY,
        subject_domain=target_domain,
        payload=payload,
        source_url=None,
        source_record_id=str(person_id),
        valid_from=start,
        valid_to=end,
        field_coverage=payload_coverage(payload),
        raw_hash=canonical_hash(profile),
        dedup_key=f"person:{ref}:{target_domain}:{relationship}",
        independence_group=f"crustdata:person:{ref}",
    )


def normalize_job(listing: dict, domain: str) -> NormalizedItem | None:
    details = _as_dict(listing.get("job_details"))
    meta = _as_dict(listing.get("metadata"))
    title = _str(details.get("title"))
    if title is None:
        return None
    group, capability = classify_title(title)
    category = _str(details.get("category"))
    if group == "non_technical" and category and category.lower() == "engineering":
        group, capability = "other_technical", "general_engineering"
    reposted = details.get("reposted_job")
    payload = JobPostingPayload(
        title=title,
        role_group=group,
        capability=capability,
        date_added=_date_str(meta.get("date_added")),
        date_updated=_date_str(meta.get("date_updated")),
        reposted=reposted if isinstance(reposted, bool) else None,
        number_of_openings=_int(details.get("number_of_openings")),
        url=_str(details.get("url")),
        category=category,
    )
    job_id = listing.get("crustdata_job_id")
    if job_id is not None:
        dedup = f"job:{job_id}"
    else:
        dedup = f"job:{payload.url or f'{title}|{payload.date_added}'}"
    return NormalizedItem(
        kind=EvidenceKind.JOB_POSTING,
        subject_domain=domain,
        payload=payload,
        source_url=payload.url,
        source_record_id=str(job_id) if job_id is not None else None,
        valid_from=payload.date_added,
        valid_to=None,
        field_coverage=payload_coverage(payload),
        raw_hash=canonical_hash(listing),
        dedup_key=dedup,
        independence_group=f"crustdata:job:{domain}",
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityCheck:
    domain: str
    status: str  # ok | ambiguous | mismatch | no_match
    resolved_name: str | None
    match_count: int
    candidates: list[dict]

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class CrustdataClient:
    provider_name = PROVIDER

    def __init__(
        self,
        api_key: str,
        *,
        api_version: str,
        base_url: str,
        timeout_s: float,
        max_retries: int,
        deadline_s: float = 60,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[int, str, float], None] | None = None,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if not api_key:
            raise ValueError("a Crustdata API key is required for live mode")
        self._api_key = api_key
        self._max_retries = max_retries
        self._deadline_s = deadline_s
        self._sleep = sleep
        self._on_retry = on_retry
        self._rng = rng
        self.api_version = api_version
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
                "x-api-version": api_version,
            },
            timeout=httpx.Timeout(connect=min(timeout_s, 10.0), read=timeout_s, write=timeout_s, pool=5.0),
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"CrustdataClient(api_version={self.api_version!r}, base_url={str(self._http.base_url)!r}, api_key=***)"

    __str__ = __repr__

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> CrustdataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _request(
        self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None
    ) -> tuple[Any, httpx.Response, int]:
        def send() -> httpx.Response:
            return self._http.request(method, path, json=json_body, params=params)

        response, attempts = execute_with_retry(
            send,
            max_retries=self._max_retries,
            deadline_s=self._deadline_s,
            sleep=self._sleep,
            rng=self._rng,
            on_retry=self._on_retry,
            redact=(self._api_key,),
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise SchemaError(
                f"{path}: response was not valid JSON",
                status=response.status_code,
                attempts=attempts,
                request_id=response.headers.get("x-request-id"),
                credits_used=parse_credits(response),
            ) from exc
        return data, response, attempts

    def _result(
        self,
        endpoint: str,
        body: dict,
        items: list[NormalizedItem],
        response: httpx.Response,
        attempts: int,
        notes: list[str],
    ) -> ProviderResult:
        return ProviderResult(
            provider="crustdata",
            endpoint=endpoint,
            request_body=body,
            items=items,
            result_count=len(items),
            credits_used=parse_credits(response),
            request_id=response.headers.get("x-request-id"),
            attempts=attempts,
            notes=notes,
        )

    @staticmethod
    def _schema(response: httpx.Response, attempts: int, message: str) -> SchemaError:
        return SchemaError(
            truncate(message),
            status=response.status_code,
            attempts=attempts,
            request_id=response.headers.get("x-request-id"),
            credits_used=parse_credits(response),
        )

    # -- DataSource --------------------------------------------------------

    def enrich_company(self, domain: str) -> ProviderResult:
        body = build_enrich_body(domain)
        wanted = body["domains"][0]
        notes: list[str] = []
        try:
            data, response, attempts = self._request("POST", ENRICH_PATH, json_body=body)
        except ProviderError as exc:
            if exc.status != 404:
                raise
            # The OpenAPI defines 404 for no match although the API returns 200 + empty matches (docs/10 s0).
            result = ProviderResult(
                "crustdata", ENRICH_PATH, body, [], 0, exc.credits_used, exc.request_id, exc.attempts, ["no match"]
            )
            return result

        if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
            raise self._schema(response, attempts, f"{ENRICH_PATH}: expected a top-level array of objects")
        candidates: list[tuple[float, dict]] = []
        for entry in data:
            matches = entry.get("matches")
            if not isinstance(matches, list):
                raise self._schema(response, attempts, f"{ENRICH_PATH}: 'matches' missing or not an array")
            for match in matches:
                if not isinstance(match, dict) or not isinstance(match.get("company_data"), dict):
                    raise self._schema(response, attempts, f"{ENRICH_PATH}: match without company_data object")
                score = _num(match.get("confidence_score"))
                candidates.append((score if score is not None else 0.0, match["company_data"]))
        if not candidates:
            return self._result(ENRICH_PATH, body, [], response, attempts, ["no match"])

        candidates.sort(key=lambda c: c[0], reverse=True)
        chosen: dict | None = None
        for _, company in candidates:
            basic = _as_dict(company.get("basic_info"))
            hosts = {_host(basic.get("primary_domain"))} | {_host(d) for d in _as_list(basic.get("all_domains"))}
            if _host(basic.get("primary_domain")) == wanted or (
                _host(basic.get("primary_domain")) is None and wanted in hosts
            ):
                chosen = company
                break
        if chosen is None:
            return self._result(ENRICH_PATH, body, [], response, attempts, ["no match (primary_domain mismatch)"])
        item = normalize_company(chosen, wanted, notes)
        return self._result(ENRICH_PATH, body, [item], response, attempts, notes)

    def search_people(
        self,
        target_domain: str,
        role_group: str,
        relationship: str,
        competitor_domain: str | None,
        limit: int,
    ) -> ProviderResult:
        body = build_person_search_body(target_domain, role_group, relationship, competitor_domain, limit)
        target = _clean_domain(target_domain)
        data, response, attempts = self._request("POST", PERSON_SEARCH_PATH, json_body=body)
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
            raise self._schema(response, attempts, f"{PERSON_SEARCH_PATH}: expected object with 'profiles' array")
        notes: list[str] = []
        items: list[NormalizedItem] = []
        skipped = 0
        for profile in data["profiles"]:
            item = normalize_person(profile, target, relationship, role_group) if isinstance(profile, dict) else None
            if item is None:
                skipped += 1
            else:
                items.append(item)
        if skipped:
            notes.append(f"{skipped} profile(s) skipped: no usable employment entry at {target}")
        if not data["profiles"]:
            notes.append("no match")
        total = data.get("total_count")
        if isinstance(total, int) and total > len(data["profiles"]):
            notes.append(f"single page only: {len(data['profiles'])} of {total} matching profiles returned")
        return self._result(PERSON_SEARCH_PATH, body, items, response, attempts, notes)

    def search_jobs(self, domain: str, role_terms: list[str], since_date: date, limit: int) -> ProviderResult:
        body = build_job_search_body(domain, role_terms, since_date, limit)
        clean = _clean_domain(domain)
        data, response, attempts = self._request("POST", JOB_SEARCH_PATH, json_body=body)
        if not isinstance(data, dict) or not isinstance(data.get("job_listings"), list):
            raise self._schema(response, attempts, f"{JOB_SEARCH_PATH}: expected object with 'job_listings' array")
        notes: list[str] = []
        items: list[NormalizedItem] = []
        seen: set[str] = set()
        for listing in data["job_listings"]:
            item = normalize_job(listing, clean) if isinstance(listing, dict) else None
            if item is None or item.dedup_key in seen:
                continue
            seen.add(item.dedup_key)
            items.append(item)
        if not data["job_listings"]:
            notes.append("no match")
        return self._result(JOB_SEARCH_PATH, body, items, response, attempts, notes)

    # -- free identity resolution (FR-01) --------------------------------

    def identify_company(self, domain: str) -> IdentityCheck:
        """Resolve a domain with the FREE /company/identify endpoint before any metered call.

        `ok` only when exactly one exact match has this primary domain. Ambiguous domains (e.g. a hosting domain
        that many small companies list as their website) are reported with candidates instead of being enriched."""
        wanted = _clean_domain(domain)
        data, response, attempts = self._request(
            "POST", IDENTIFY_PATH, json_body={"domains": [wanted], "exact_match": True}
        )
        if not isinstance(data, list):
            raise self._schema(response, attempts, f"{IDENTIFY_PATH}: expected a top-level array")
        candidates: list[dict] = []
        for entry in data:
            for match in _as_list(_as_dict(entry).get("matches")):
                basic = _as_dict(_as_dict(_as_dict(match).get("company_data")).get("basic_info"))
                candidates.append(
                    {
                        "name": _str(basic.get("name")),
                        "primary_domain": _host(basic.get("primary_domain")),
                        "employee_count_range": _str(basic.get("employee_count_range")),
                        "confidence": _num(_as_dict(match).get("confidence_score")),
                    }
                )
        exact = [c for c in candidates if c["primary_domain"] == wanted]
        if len(exact) == 1 and len(candidates) <= 3:
            status = "ok"
        elif not candidates:
            status = "no_match"
        elif exact:
            status = "ambiguous"
        else:
            status = "mismatch"
        return IdentityCheck(
            domain=wanted,
            status=status,
            resolved_name=exact[0]["name"] if exact else None,
            match_count=len(candidates),
            candidates=candidates[:5],
        )

    # -- free account helpers ---------------------------------------------

    def account_credits(self) -> dict:
        data, response, attempts = self._request("GET", "/account/credits")
        if not isinstance(data, dict):
            raise self._schema(response, attempts, "/account/credits: expected a JSON object")
        return data

    def endpoint_pricing(self, path: str) -> dict:
        if not re.fullmatch(r"/[A-Za-z0-9_/\-]{1,100}", path or ""):
            raise BadRequestError(f"invalid endpoint path: {path!r}", code="INVALID_PATH")
        data, response, attempts = self._request("GET", "/account/endpoints", params={"path": path})
        if isinstance(data, list):
            return {"endpoints": data}
        if not isinstance(data, dict):
            raise self._schema(response, attempts, "/account/endpoints: expected a JSON object")
        return data


__all__ = [
    "CrustdataClient",
    "build_enrich_body",
    "build_job_search_body",
    "build_person_search_body",
    "derive_engineering_growth",
    "normalize_company",
    "normalize_job",
    "normalize_person",
]
