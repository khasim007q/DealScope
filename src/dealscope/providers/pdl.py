"""People Data Labs client (free tier) for company and person data.

* Company enrich: ``GET /v5/company/enrich?website=<domain>`` -> ``CompanyProfilePayload``.
* Person search: ``POST /v5/person/search`` (Elasticsearch query) -> ``PersonHistoryPayload`` with dated
  employment intervals at the target company.

Nothing is invented: engineering headcount/growth is filled only when PDL returns a per-role breakdown;
otherwise those fields stay empty and the downstream signal is "not scored".

PDL's free tier is small, so every record consumed is counted in a per-month JSON counter
(``PdlUsageCounter``, one shared instance per file, guarded by a process-wide lock) and calls beyond
``PDL_MONTHLY_LIMIT`` or the per-case cap are refused locally with a clear message. A corrupt counter file
fails CLOSED (treated as quota exhausted). Company-enrich results are cached on disk (``PdlCompanyCache``) so
the identity check and the investigation that follows cost one record between them.
Error mapping: 401/403 -> AuthError, 402 -> InsufficientCreditsError (fatal for the agent),
429 -> retried then RetryExhaustedError, 404 -> "no match" (empty result, never an error).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from dealscope.domain.enums import EvidenceKind
from dealscope.domain.models import CompanyProfilePayload, PersonHistoryPayload, normalize_domain
from dealscope.providers.base import (
    BadRequestError,
    NormalizedItem,
    ProviderError,
    ProviderResult,
    SchemaError,
    canonical_hash,
    payload_coverage,
)
from dealscope.providers.classify import PERSON_ROLE_GROUP_TITLES, classify_title
from dealscope.providers.crustdata import IdentityCheck
from dealscope.providers.http_retry import execute_with_retry

PROVIDER = "free"
COMPANY_ENRICH_PATH = "/v5/company/enrich"
PERSON_SEARCH_PATH = "/v5/person/search"
GROWTH_PERIODS = {1: "1m", 3: "3m", 6: "6m", 12: "12m", 24: "24m"}
_RELATIONSHIPS = ("past_target_employment", "current_target_employment")


class PdlNotConfiguredError(BadRequestError):
    """No PDL key: people/company data is unavailable; the agent should mark those signals not scored."""

    default_code = "NOT_CONFIGURED"


class PdlQuotaExhaustedError(BadRequestError):
    """Local free-tier guard: the monthly PDL request allowance is used up."""

    default_code = "PDL_MONTHLY_LIMIT"


# ---------------------------------------------------------------------------
# Monthly usage guard
# ---------------------------------------------------------------------------


class PdlUsageCorruptError(Exception):
    """The usage counter file exists but cannot be trusted."""


_USAGE_LOCK = threading.RLock()  # one lock for every counter in the process (they may share a file)
_COUNTERS: dict[str, PdlUsageCounter] = {}


class PdlUsageCounter:
    """Per-calendar-month record counter persisted as ``{"month", "used", "cases": {case_id: n}}`` in JSON.

    Fails CLOSED: a file that exists but is unreadable or malformed counts as quota exhausted (never as 0), so a
    damaged counter cannot silently allow unlimited PDL use. Delete the file to reset it deliberately.
    """

    def __init__(self, path: Path | str, limit: int, today: Callable[[], date] = date.today) -> None:
        self.path = Path(path)
        self.limit = int(limit)
        self._today = today
        self._lock = _USAGE_LOCK

    def _month(self) -> str:
        return self._today().strftime("%Y-%m")

    def _load(self) -> tuple[int, dict[str, int]]:
        """``(used, per_case)`` for this month. Missing file / other month -> zeros. Corrupt -> raises."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return 0, {}
        except OSError as exc:
            raise PdlUsageCorruptError(f"cannot read {self.path}: {exc}") from exc
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise PdlUsageCorruptError(f"{self.path} is not valid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("month"), str):
            raise PdlUsageCorruptError(f"{self.path} has an unexpected shape")
        used = data.get("used")
        if isinstance(used, bool) or not isinstance(used, int) or used < 0:
            raise PdlUsageCorruptError(f"{self.path} has an invalid 'used' count")
        if data["month"] != self._month():
            return 0, {}
        cases = data.get("cases", {})
        if not isinstance(cases, dict) or any(
            not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) or v < 0 for k, v in cases.items()
        ):
            raise PdlUsageCorruptError(f"{self.path} has an invalid 'cases' map")
        return used, dict(cases)

    def _corrupt_error(self, exc: Exception) -> PdlQuotaExhaustedError:
        return PdlQuotaExhaustedError(
            f"The PDL usage counter ({self.path}) is unreadable ({exc}); PDL lookups are paused so the free quota "
            "cannot be overspent. Fix or delete that file to resume.",
            code="PDL_MONTHLY_LIMIT",
        )

    def used(self) -> int:
        with self._lock:
            try:
                return self._load()[0]
            except PdlUsageCorruptError:
                return self.limit  # fail closed

    def remaining(self) -> int:
        return max(0, self.limit - self.used())

    def case_used(self, case_id: str) -> int:
        with self._lock:
            try:
                return self._load()[1].get(case_id, 0)
            except PdlUsageCorruptError:
                return 0

    def consume(self, n: int = 1, case_id: str | None = None) -> int:
        """Add ``n`` records to this month's count (and the case's) and return the new total."""
        with self._lock:
            try:
                used, cases = self._load()
            except PdlUsageCorruptError:
                return self.limit  # never overwrite an untrusted file
            n = max(0, int(n))
            total = used + n
            if case_id:
                cases[case_id] = cases.get(case_id, 0) + n
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps({"month": self._month(), "used": total, "cases": cases}), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                tmp.unlink(missing_ok=True)  # a read-only disk must not break an analysis; PDL's own quota applies
            return total

    def require(self, needed: int = 1, case_id: str | None = None, case_cap: int | None = None) -> int:
        """Raise unless at least one record remains (monthly and per-case); returns the allowed record count."""
        with self._lock:
            try:
                used, cases = self._load()
            except PdlUsageCorruptError as exc:
                raise self._corrupt_error(exc) from exc
        remaining = max(0, self.limit - used)
        if remaining < max(1, needed):
            raise PdlQuotaExhaustedError(
                f"PDL monthly free-tier limit reached ({self.limit} records used for {self._month()}). "
                "Raise PDL_MONTHLY_LIMIT if your plan allows, or wait until next month.",
                code="PDL_MONTHLY_LIMIT",
            )
        if case_id and case_cap is not None:
            case_left = case_cap - cases.get(case_id, 0)
            if case_left < max(1, needed):
                raise PdlQuotaExhaustedError(
                    f"PDL per-case limit reached ({case_cap} records for this investigation). "
                    "Raise PDL_MAX_RECORDS_PER_CASE if you want more people data for one case.",
                    code="PDL_MONTHLY_LIMIT",
                )
            remaining = min(remaining, case_left)
        return remaining


def shared_usage_counter(path: Path | str, limit: int) -> PdlUsageCounter:
    """One counter per file for the whole process (identity checks and runs must not each keep their own)."""
    key = str(Path(path).resolve())
    with _USAGE_LOCK:
        counter = _COUNTERS.get(key)
        if counter is None:
            counter = _COUNTERS[key] = PdlUsageCounter(path, limit)
        counter.limit = int(limit)
        return counter


class PdlCompanyCache:
    """On-disk (SQLite) cache of company-enrich responses, shared by every client in every process.

    ``get`` returns ``(found, data)``; a stored 404 is ``(True, None)``. Entries expire after ``ttl_s``."""

    def __init__(self, path: Path | str, ttl_s: float = 24 * 3600, negative_ttl_s: float = 600) -> None:
        self.path = Path(path)
        self.ttl_s = ttl_s
        self.negative_ttl_s = negative_ttl_s
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS pdl_company (domain TEXT PRIMARY KEY, fetched_at REAL NOT NULL, body TEXT)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get(self, domain: str) -> tuple[bool, dict | None]:
        with self._lock:
            try:
                conn = self._connect()
                try:
                    row = conn.execute("SELECT fetched_at, body FROM pdl_company WHERE domain=?", (domain,)).fetchone()
                finally:
                    conn.close()
            except sqlite3.Error:
                return False, None
        if row is None:
            return False, None
        fetched_at, body = row
        age = time.time() - fetched_at
        if body is None:
            return (age < self.negative_ttl_s), None
        if age >= self.ttl_s:
            return False, None
        try:
            data = json.loads(body)
        except ValueError:
            return False, None
        return (True, data) if isinstance(data, dict) else (False, None)

    def put(self, domain: str, data: dict | None) -> None:
        with self._lock:
            try:
                conn = self._connect()
                try:
                    with conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO pdl_company (domain, fetched_at, body) VALUES (?,?,?)",
                            (domain, time.time(), None if data is None else json.dumps(data)),
                        )
                finally:
                    conn.close()
            except sqlite3.Error:
                pass  # caching is best-effort


class _MemoryCompanyCache:
    """Process-local fallback when no on-disk cache is configured (10 minute reuse)."""

    def __init__(self, ttl_s: float = 600) -> None:
        self.ttl_s = ttl_s
        self._items: dict[str, tuple[float, dict | None]] = {}

    def get(self, domain: str) -> tuple[bool, dict | None]:
        hit = self._items.get(domain)
        if hit and time.monotonic() - hit[0] < self.ttl_s:
            return True, hit[1]
        return False, None

    def put(self, domain: str, data: dict | None) -> None:
        self._items[domain] = (time.monotonic(), data)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _str(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    return None


def _num(v: Any) -> float | None:
    return None if isinstance(v, bool) or not isinstance(v, (int, float)) else float(v)


def _host(v: Any) -> str | None:
    text = _str(v)
    if text is None:
        return None
    try:
        return normalize_domain(text)
    except ValueError:
        return None


def _month_index(key: str) -> int | None:
    m = re.match(r"^(\d{4})-(\d{2})", key)
    if not m:
        return None
    return int(m.group(1)) * 12 + int(m.group(2)) - 1


def series_points(series: Any) -> list[tuple[int, int]]:
    """``{"2024-05": 120, ...}`` -> sorted ``[(month_index, count)]`` (non-integer values skipped)."""
    if not isinstance(series, dict):
        return []
    pts = []
    for k, v in series.items():
        idx = _month_index(k) if isinstance(k, str) else None
        n = _int(v)
        if idx is not None and n is not None and n >= 0:
            pts.append((idx, n))
    return sorted(pts)


def growth_from_series(points: list[tuple[int, int]]) -> dict[str, float]:
    """Latest vs the point exactly N months earlier (or the nearest earlier one within 1 month)."""
    if len(points) < 2:
        return {}
    latest_idx, latest = points[-1]
    out: dict[str, float] = {}
    for months, label in GROWTH_PERIODS.items():
        target = latest_idx - months
        earlier = [p for p in points[:-1] if p[0] <= target and target - p[0] <= 1]
        if not earlier:
            continue
        base = max(earlier, key=lambda p: p[0])[1]
        if base > 0:
            out[label] = round((latest - base) / base * 100.0, 2)
    return out


def _engineering_series(by_role: Any) -> list[tuple[int, int]]:
    """Engineering headcount series from ``{"YYYY-MM": {"engineering": n, ...}}`` if PDL returns it."""
    if not isinstance(by_role, dict):
        return []
    pts: list[tuple[int, int]] = []
    for month, roles in by_role.items():
        idx = _month_index(month) if isinstance(month, str) else None
        if idx is None or not isinstance(roles, dict):
            continue
        keys = [k for k in roles if isinstance(k, str) and "engineering" in k.lower()]
        if not keys:
            continue
        exact = [k for k in keys if k.lower() == "engineering"]
        n = _int(roles[(exact or sorted(keys))[0]])
        if n is not None:
            pts.append((idx, n))
    return sorted(pts)


def normalize_company(data: dict, domain: str, notes: list[str]) -> NormalizedItem:
    monthly = series_points(data.get("employee_count_by_month"))
    growth = growth_from_series(monthly)
    if monthly and not growth:
        notes.append("employee_count_by_month too short to derive growth")
    eng_pts = _engineering_series(data.get("employee_count_by_month_by_role"))
    eng_headcount = eng_pts[-1][1] if eng_pts else None
    eng_growth = growth_from_series(eng_pts)
    if eng_pts:
        notes.append("engineering headcount/growth derived from employee_count_by_month_by_role")
    else:
        notes.append("PDL returned no engineering role breakdown; engineering headcount/growth left unknown")
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    country = _str(location.get("country"))
    payload = CompanyProfilePayload(
        name=_str(data.get("display_name")) or _str(data.get("name")),
        domain=domain,
        total_headcount=_int(data.get("employee_count")),
        total_growth_pct=growth,
        engineering_headcount=eng_headcount,
        engineering_growth_pct=eng_growth,
        job_openings_count=None,
        funding_total_usd=_num(data.get("total_funding_raised")),
        industry=_str(data.get("industry")),
        hq_country=country.title() if country else None,
    )
    rid = data.get("id")
    return NormalizedItem(
        kind=EvidenceKind.COMPANY_PROFILE,
        subject_domain=domain,
        payload=payload,
        source_url=None,
        source_record_id=str(rid) if rid is not None else None,
        valid_from=None,
        valid_to=None,
        field_coverage=payload_coverage(payload),
        raw_hash=canonical_hash(data),
        dedup_key=f"company:{domain}",
        independence_group=f"pdl:company_enrich:{domain}",
    )


def _person_ref(pid: object) -> str:
    return "p-" + hashlib.sha256(f"pdl:{pid}".encode()).hexdigest()[:16]


def _entry_title(entry: dict) -> str | None:
    t = entry.get("title")
    return _str(t.get("name")) if isinstance(t, dict) else _str(t)


def _entry_host(entry: dict) -> str | None:
    c = entry.get("company")
    return _host(c.get("website")) if isinstance(c, dict) else None


def _date_prefix(v: Any) -> str | None:
    text = _str(v)
    return text[:10] if text and re.match(r"\d{4}(-\d{2}(-\d{2})?)?", text) else None


def normalize_person(profile: dict, target: str, relationship: str, role_group: str | None) -> NormalizedItem | None:
    """None when the profile has no id or no usable dated entry at the target (never invented)."""
    pid = profile.get("id")
    if pid is None:
        return None
    entries = [e for e in profile.get("experience") or [] if isinstance(e, dict) and _entry_host(e) == target]
    want_current = relationship == "current_target_employment"
    entries = [e for e in entries if (_date_prefix(e.get("end_date")) is None) == want_current]
    if not entries:
        return None
    preferred = [e for e in entries if role_group and classify_title(_entry_title(e))[0] == role_group]
    entry = max(
        preferred or entries, key=lambda e: _date_prefix(e.get("end_date")) or _date_prefix(e.get("start_date")) or ""
    )
    title = _entry_title(entry)
    group, capability = classify_title(title)
    start = _date_prefix(entry.get("start_date"))
    end = None if want_current else _date_prefix(entry.get("end_date"))
    currently = _host(profile.get("job_company_website")) == target or want_current
    levels = entry.get("title", {}).get("levels") if isinstance(entry.get("title"), dict) else None
    ref = _person_ref(pid)
    payload = PersonHistoryPayload(
        person_ref=ref,
        role_group=group,
        capability=capability,
        title_at_target=title,
        seniority=_str(levels[0]) if isinstance(levels, list) and levels else None,
        target_start=start,
        target_end=end,
        currently_at_target=currently,
        current_employer_name=_str(profile.get("job_company_name")),
        current_employer_domain=_host(profile.get("job_company_website")),
        current_title=_str(profile.get("job_title")),
    )
    return NormalizedItem(
        kind=EvidenceKind.PERSON_HISTORY,
        subject_domain=target,
        payload=payload,
        source_url=None,
        source_record_id=str(pid),
        valid_from=start,
        valid_to=end,
        field_coverage=payload_coverage(payload),
        raw_hash=canonical_hash(profile),
        dedup_key=f"person:{ref}:{target}:{relationship}",
        independence_group=f"pdl:person:{ref}",
    )


def build_person_query(target: str, role_group: str, relationship: str, competitor: str | None) -> dict:
    if role_group not in PERSON_ROLE_GROUP_TITLES:
        raise BadRequestError(f"unsupported role_group: {role_group!r}", code="INVALID_ROLE_GROUP")
    if relationship not in _RELATIONSHIPS:
        raise BadRequestError(f"unsupported relationship: {relationship!r}", code="INVALID_RELATIONSHIP")
    current = relationship == "current_target_employment"
    title_field = "job_title" if current else "experience.title.name"
    must: list[dict] = [
        {"term": {"job_company_website" if current else "experience.company.website": target}},
        {
            "bool": {
                "should": [{"match_phrase": {title_field: t.lower()}} for t in PERSON_ROLE_GROUP_TITLES[role_group]],
                "minimum_should_match": 1,
            }
        },
    ]
    bool_q: dict[str, Any] = {"must": must}
    if not current:
        bool_q["must_not"] = [{"term": {"job_company_website": target}}]
    if competitor:
        must.append({"term": {"job_company_website": competitor}})
    return {"bool": bool_q}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PdlClient:
    provider_name = PROVIDER

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.peopledatalabs.com",
        timeout_s: float = 25.0,
        max_retries: int = 2,
        deadline_s: float = 60.0,
        max_people_results: int = 10,
        usage: PdlUsageCounter | None = None,
        cache: PdlCompanyCache | _MemoryCompanyCache | None = None,
        max_records_per_case: int | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[int, str, float], None] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("a PDL API key is required")
        self._api_key = api_key
        self._max_retries = max_retries
        self._deadline_s = deadline_s
        self._sleep = sleep
        self._on_retry = on_retry
        self.max_people_results = max(1, int(max_people_results))
        self.usage = usage
        self._cache = cache if cache is not None else _MemoryCompanyCache()
        self.max_records_per_case = max_records_per_case
        self.case_id: str | None = None  # set by the executor so usage is also counted per case
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Api-Key": api_key, "content-type": "application/json", "accept": "application/json"},
            timeout=httpx.Timeout(connect=min(timeout_s, 10.0), read=timeout_s, write=timeout_s, pool=5.0),
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"PdlClient(base_url={str(self._http.base_url)!r}, api_key=***)"

    __str__ = __repr__

    def close(self) -> None:
        self._http.close()

    # -- transport --------------------------------------------------------

    def _call(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None):
        """Returns ``(json | None, attempts)``; ``None`` means HTTP 404 (no match)."""

        def send() -> httpx.Response:
            return self._http.request(method, path, params=params, json=body)

        try:
            response, attempts = execute_with_retry(
                send,
                max_retries=self._max_retries,
                deadline_s=self._deadline_s,
                sleep=self._sleep,
                on_retry=self._on_retry,
                redact=(self._api_key,),
            )
        except ProviderError as exc:
            if exc.status == 404:
                return None, exc.attempts
            raise
        try:
            return response.json(), attempts
        except ValueError as exc:
            raise SchemaError(f"{path}: response was not valid JSON", status=response.status_code) from exc

    def _require(self, needed: int = 1) -> int:
        if self.usage is None:
            return 10**9
        return self.usage.require(needed, self.case_id, self.max_records_per_case)

    def _consume(self, n: int) -> None:
        if self.usage is not None:
            self.usage.consume(n, self.case_id)

    def _enrich_raw(self, domain: str) -> tuple[dict | None, int, bool]:
        """Company record for a domain from the shared on-disk cache or PDL (identity check + enrich = 1 record)."""
        found, cached = self._cache.get(domain)
        if found:
            return cached, 0, True
        self._require(1)
        data, attempts = self._call("GET", COMPANY_ENRICH_PATH, params={"website": domain})
        if data is not None and not isinstance(data, dict):
            raise SchemaError(f"{COMPANY_ENRICH_PATH}: expected a JSON object")
        if data is not None:
            self._consume(1)
        self._cache.put(domain, data)
        return data, attempts, False

    # -- DataSource --------------------------------------------------------

    def enrich_company(self, domain: str) -> ProviderResult:
        wanted = normalize_domain(domain)
        body = {"website": wanted}
        data, attempts, cached = self._enrich_raw(wanted)
        notes: list[str] = ["people data labs company enrich" + (" (reused recent lookup)" if cached else "")]
        if data is None:
            return ProviderResult(
                PROVIDER, COMPANY_ENRICH_PATH, body, [], 0, Decimal("0"), None, attempts, ["no match"]
            )
        returned = _host(data.get("website"))
        if returned is not None and returned != wanted:
            notes.append(f"no match (PDL resolved website {returned})")
            return ProviderResult(PROVIDER, COMPANY_ENRICH_PATH, body, [], 0, Decimal("0"), None, attempts, notes)
        item = normalize_company(data, wanted, notes)
        return ProviderResult(PROVIDER, COMPANY_ENRICH_PATH, body, [item], 1, Decimal("0"), None, attempts, notes)

    def search_people(
        self,
        target_domain: str,
        role_group: str,
        relationship: str,
        competitor_domain: str | None,
        limit: int,
    ) -> ProviderResult:
        target = normalize_domain(target_domain)
        competitor = normalize_domain(competitor_domain) if competitor_domain else None
        query = build_person_query(target, role_group, relationship, competitor)
        size = max(1, min(int(limit), self.max_people_results))
        size = min(size, self._require(1))
        body = {
            "query": query,
            "size": size,
            "fields": ["id", "job_title", "job_company_name", "job_company_website", "experience"],
        }
        data, attempts = self._call("POST", PERSON_SEARCH_PATH, body=body)
        if data is None:
            return ProviderResult(PROVIDER, PERSON_SEARCH_PATH, body, [], 0, Decimal("0"), None, attempts, ["no match"])
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise SchemaError(f"{PERSON_SEARCH_PATH}: expected object with 'data' array")
        profiles = data["data"]
        self._consume(len(profiles))
        items: list[NormalizedItem] = []
        skipped = 0
        for profile in profiles:
            item = normalize_person(profile, target, relationship, role_group) if isinstance(profile, dict) else None
            if item is None:
                skipped += 1
            else:
                items.append(item)
        notes = ["people data labs person search"]
        if skipped:
            notes.append(f"{skipped} profile(s) skipped: no usable dated entry at {target}")
        total = data.get("total")
        if isinstance(total, int) and total > len(profiles):
            notes.append(f"single page only: {len(profiles)} of {total} matching profiles returned")
        if not profiles:
            notes.append("no match")
        return ProviderResult(
            PROVIDER, PERSON_SEARCH_PATH, body, items, len(items), Decimal("0"), None, attempts, notes
        )

    def search_jobs(self, domain: str, role_terms: list[str], since_date: date, limit: int) -> ProviderResult:
        raise BadRequestError("PDL does not provide job postings", code="UNSUPPORTED")

    # -- identity ----------------------------------------------------------

    def identify_company(self, domain: str) -> IdentityCheck:
        """PDL enrich-by-website returns one company or 404: exactly-one / no-match. Costs 1 PDL record."""
        wanted = normalize_domain(domain)
        data, _, _ = self._enrich_raw(wanted)
        if data is None:
            return IdentityCheck(wanted, "no_match", None, 0, [])
        returned = _host(data.get("website"))
        candidate = {
            "name": _str(data.get("display_name")) or _str(data.get("name")),
            "primary_domain": returned,
            "employee_count_range": _str(data.get("size")),
            "confidence": _num(data.get("likelihood")),
        }
        if returned == wanted:
            return IdentityCheck(wanted, "ok", candidate["name"], 1, [candidate])
        return IdentityCheck(wanted, "mismatch", None, 1, [candidate])


__all__ = [
    "PdlClient",
    "PdlCompanyCache",
    "PdlNotConfiguredError",
    "PdlQuotaExhaustedError",
    "PdlUsageCounter",
    "shared_usage_counter",
    "growth_from_series",
    "normalize_company",
    "normalize_person",
]
