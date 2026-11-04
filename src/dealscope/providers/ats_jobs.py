"""Job postings from public, keyless ATS job-board APIs (Greenhouse, Lever, Ashby).

No credentials and no credits. Candidate board slugs are derived from the company domain (and optionally
the company name); each ATS is probed for each slug and the first non-empty board (in slug order, then
Greenhouse > Lever > Ashby) wins. A 404 simply means "no board here" and never raises. The ATS and slug that
produced the data are recorded in ``ProviderResult.endpoint`` / ``notes`` and in each item's
``independence_group`` so the evidence trail shows where the postings came from.

Caveat: slug matching is heuristic and ignores the domain's TLD, so a slug can belong to a different company
with a similar name (``ramp.xyz`` vs ``ramp.com``). Every board is therefore cross-checked: job URLs hosted on
the target's own domain (or a board name equal to the name the identity provider resolved) confirm it; job URLs
on a *different* company domain reject it; anything else is kept but marked ``board_match="name_only"`` so it is
never treated as strong evidence.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, date, datetime
from typing import Any, NamedTuple
from urllib.parse import urlparse

import httpx

from dealscope.domain.enums import EvidenceKind
from dealscope.domain.models import JobPostingPayload, normalize_domain
from dealscope.providers.base import (
    BadRequestError,
    NormalizedItem,
    ProviderError,
    ProviderResult,
    RetryExhaustedError,
    SchemaError,
    canonical_hash,
    payload_coverage,
)
from dealscope.providers.classify import JOB_ROLE_TERM_TITLES, classify_title
from dealscope.providers.http_retry import execute_with_retry

PROVIDER = "free"
ATS_ORDER = ("greenhouse", "lever", "ashby")
MAX_SLUGS = 5
MAX_JOB_LIMIT = 100
MAX_RESPONSE_BYTES = 5_000_000  # a board larger than this is skipped, not parsed
FIND_DEADLINE_S = 30.0  # overall budget for probing every candidate board of one company

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}
GREENHOUSE_META_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}"
# Hosts of the ATS vendors themselves: a job URL here says nothing about which company owns the board.
_GENERIC_HOSTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "smartrecruiters.com",
    "myworkdayjobs.com",
    "jobvite.com",
    "icims.com",
    "breezy.hr",
    "recruitee.com",
    "applytojob.com",
    "bamboohr.com",
)
_NAME_SUFFIXES = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "gmbh", "plc", "hq"}


def _registrable(host: str) -> str:
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _host_of(url: Any) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return None
    host = host.removeprefix("www.")
    return host if "." in host else None


def _name_key(name: str | None) -> str:
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split() if w not in _NAME_SUFFIXES]
    return "".join(words)


class Board(NamedTuple):
    ats: str
    slug: str
    jobs: list[dict]
    match: str  # "confirmed" | "name_only"
    detail: str  # human-readable basis for ``match``


class _Fetched(NamedTuple):
    jobs: list[dict]
    org_name: str | None


class _TooLarge(Exception):
    pass


def derive_slugs(domain: str, company_name: str | None = None) -> list[str]:
    """Candidate board slugs, most likely first: ``linear.app`` -> ``["linear", "linearapp"]``."""
    host = normalize_domain(domain)
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        core = labels[:-2]
    else:
        core = labels[:-1] or labels
    core = [lab for lab in core if lab != "www"] or core
    base = core[-1]
    cands: list[str] = [base]
    if "-" in base:
        cands.append(base.replace("-", ""))
    cands.append("".join(core))
    cands.append(re.sub(r"[^a-z0-9]", "", host))  # e.g. "linearapp"
    if company_name:
        low = company_name.strip().lower()
        cands.append(re.sub(r"[^a-z0-9]", "", low))
        cands.append(re.sub(r"[^a-z0-9]+", "-", low).strip("-"))
    out: list[str] = []
    for c in cands:
        c = c.strip().lower()
        if c and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", c) and c not in out:
            out.append(c)
    return out[:MAX_SLUGS]


# ---------------------------------------------------------------------------
# Normalization (one function per ATS; each returns (payload, job_id) or None)
# ---------------------------------------------------------------------------


def _str(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _date(v: Any) -> str | None:
    """ISO string -> YYYY-MM-DD; epoch milliseconds -> YYYY-MM-DD (UTC)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v > 0:
        try:
            return datetime.fromtimestamp(v / 1000.0, tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = _str(v)
    return text[:10] if text and re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def _payload(title: str, department: str | None, added: str | None, updated: str | None, url: str | None):
    group, capability = classify_title(title)
    if group == "non_technical" and department and department.lower() in {"engineering", "technology", "research"}:
        group, capability = "other_technical", "general_engineering"
    return JobPostingPayload(
        title=title,
        role_group=group,
        capability=capability,
        date_added=added,
        date_updated=updated,
        reposted=None,
        number_of_openings=None,
        url=url,
        category=department,
    )


def _greenhouse(job: dict) -> tuple[JobPostingPayload, str | None] | None:
    title = _str(job.get("title"))
    if title is None:
        return None
    depts = [d.get("name") for d in job.get("departments") or [] if isinstance(d, dict) and _str(d.get("name"))]
    p = _payload(
        title,
        depts[0] if depts else None,
        _date(job.get("first_published")),
        _date(job.get("updated_at")),
        _str(job.get("absolute_url")),
    )
    return p, str(job["id"]) if job.get("id") is not None else None


def _lever(job: dict) -> tuple[JobPostingPayload, str | None] | None:
    title = _str(job.get("text"))
    if title is None:
        return None
    cats = job.get("categories") if isinstance(job.get("categories"), dict) else {}
    dept = _str(cats.get("department")) or _str(cats.get("team"))
    p = _payload(title, dept, _date(job.get("createdAt")), None, _str(job.get("hostedUrl")))
    return p, _str(job.get("id"))


def _ashby(job: dict) -> tuple[JobPostingPayload, str | None] | None:
    title = _str(job.get("title"))
    if title is None or job.get("isListed") is False:
        return None
    dept = _str(job.get("department")) or _str(job.get("team"))
    p = _payload(title, dept, _date(job.get("publishedAt")), None, _str(job.get("jobUrl")))
    return p, _str(job.get("id"))


def _extract(ats: str, data: Any) -> list[dict]:
    if ats == "lever":
        return [j for j in data if isinstance(j, dict)] if isinstance(data, list) else []
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []


_NORMALIZERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def _org_name(ats: str, data: Any) -> str | None:
    """Company name if the board response exposes one (Ashby ``organization``); Greenhouse/Lever do not."""
    if ats == "ashby" and isinstance(data, dict):
        org = data.get("organization")
        if isinstance(org, dict):
            org = org.get("name")
        return _str(org) or _str(data.get("organizationName")) or _str(data.get("companyName"))
    return None


def _flat(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def _wanted_titles(role_terms: list[str]) -> list[str]:
    unknown = [t for t in role_terms if t not in JOB_ROLE_TERM_TITLES]
    if unknown or not role_terms:
        raise BadRequestError(f"unsupported role_terms: {unknown or role_terms!r}", code="INVALID_ROLE_TERMS")
    out: list[str] = []
    for term in role_terms:
        out.extend(_flat(t) for t in JOB_ROLE_TERM_TITLES[term] if _flat(t) not in out)
    return out


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


class AtsJobSource:
    provider_name = PROVIDER

    def __init__(
        self,
        *,
        timeout_s: float = 20.0,
        max_retries: int = 1,
        deadline_s: float = 45.0,
        find_deadline_s: float = FIND_DEADLINE_S,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        company_names: dict[str, str] | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._deadline_s = deadline_s
        self._find_deadline_s = find_deadline_s
        self._max_bytes = max_response_bytes
        self._sleep = sleep
        self._names = {normalize_domain(k): v for k, v in (company_names or {}).items()}
        self._http = httpx.Client(
            timeout=httpx.Timeout(connect=min(timeout_s, 8.0), read=timeout_s, write=timeout_s, pool=5.0),
            transport=transport,
            headers={"accept": "application/json", "user-agent": "DealScope/0.1 (public job-board reader)"},
            follow_redirects=True,
        )
        self._boards: dict[str, Board | None] = {}
        self._notes: dict[str, list[str]] = {}
        # Set by the orchestrator so a user "stop" also stops board probing at the next request boundary.
        self.cancel_event: threading.Event | None = None

    def close(self) -> None:
        self._http.close()

    def set_company_name(self, domain: str, name: str) -> None:
        """Extra slug hint (e.g. the name PDL resolved). Does not clear an already cached board."""
        self._names[normalize_domain(domain)] = name

    def set_cancel_event(self, event: threading.Event | None) -> None:
        self.cancel_event = event

    # -- fetching ---------------------------------------------------------

    def _get(self, url: str) -> httpx.Response:
        """GET with a hard cap on the body size; the body is read incrementally and abandoned beyond the cap."""
        with self._http.stream("GET", url) as r:
            body = bytearray()
            if r.status_code < 400:
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > self._max_bytes:
                        raise _TooLarge(url)
            else:
                body += r.read()[:2000]
            skip = ("content-encoding", "content-length", "transfer-encoding")
            headers = {k: v for k, v in r.headers.items() if k.lower() not in skip}
            return httpx.Response(r.status_code, headers=headers, content=bytes(body), request=r.request)

    def _fetch(self, ats: str, slug: str) -> _Fetched | None:
        """Jobs for one board; ``None`` for 404 or an oversized board (no usable board); other failures raise."""
        url = URLS[ats].format(slug=slug)
        try:
            response, _ = execute_with_retry(
                lambda: self._get(url),
                max_retries=self._max_retries,
                deadline_s=self._deadline_s,
                sleep=self._sleep,
            )
        except _TooLarge:
            return None
        except ProviderError as exc:
            if exc.status == 404:
                return None
            raise
        try:
            data = response.json()
        except ValueError as exc:
            raise SchemaError(f"{ats}:{slug}: response was not valid JSON", status=response.status_code) from exc
        return _Fetched(_extract(ats, data), _org_name(ats, data))

    def _greenhouse_name(self, slug: str) -> str | None:
        """Board display name from Greenhouse's board metadata; any failure just means "unknown"."""
        try:
            response, _ = execute_with_retry(
                lambda: self._get(GREENHOUSE_META_URL.format(slug=slug)),
                max_retries=0,
                deadline_s=self._deadline_s,
                sleep=self._sleep,
            )
            data = response.json()
        except (ProviderError, ValueError, _TooLarge):
            return None
        return _str(data.get("name")) if isinstance(data, dict) else None

    def _assess(self, domain: str, ats: str, slug: str, fetched: _Fetched) -> tuple[str, str]:
        """``(verdict, detail)``; verdict is ``confirmed``, ``name_only`` or ``rejected``."""
        target = _registrable(domain)
        hosts: Counter[str] = Counter()
        for job in fetched.jobs[:300]:
            for key in ("absolute_url", "hostedUrl", "jobUrl", "applyUrl"):
                host = _host_of(job.get(key))
                if host and not any(host == g or host.endswith("." + g) for g in _GENERIC_HOSTS):
                    hosts[_registrable(host)] += 1
        if hosts:
            if target in hosts:
                return "confirmed", f"job links point to {target}"
            owner = hosts.most_common(1)[0][0]
            return "rejected", f"{ats} board '{slug}' belongs to {owner}, not {domain}"
        board_name = fetched.org_name or (self._greenhouse_name(slug) if ats == "greenhouse" else None)
        hint = self._names.get(domain)
        if board_name and hint and _name_key(board_name) == _name_key(hint):
            return "confirmed", f"board name '{board_name}' equals the company name '{hint}'"
        named = f" (board is named '{board_name}')" if board_name else ""
        return "name_only", f"board matched by name only; ownership by {domain} could not be confirmed{named}"

    def find_board(self, domain: str) -> Board | None:
        """First usable non-empty board, or ``None``. Cached per domain.

        A board whose job links point to a different company is rejected. If any probe failed with a
        non-404 error and no board was found, a retryable error is raised and nothing is cached (a transient
        outage must not be remembered as "this company has no jobs")."""
        domain = normalize_domain(domain)
        if domain in self._boards:
            return self._boards[domain]
        combos = [(slug, ats) for slug in derive_slugs(domain, self._names.get(domain)) for ats in ATS_ORDER]
        deadline = time.monotonic() + self._find_deadline_s

        def stopped() -> bool:
            return time.monotonic() >= deadline or (self.cancel_event is not None and self.cancel_event.is_set())

        def probe(combo: tuple[str, str]) -> _Fetched | ProviderError | None:
            slug, ats = combo
            if stopped():
                return RetryExhaustedError("job-board lookup stopped before this board was checked", retryable=True)
            try:
                return self._fetch(ats, slug)
            except ProviderError as exc:
                return exc

        pool = ThreadPoolExecutor(max_workers=6)
        futures = [pool.submit(probe, c) for c in combos]
        wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        pool.shutdown(wait=False, cancel_futures=True)
        results: list[_Fetched | ProviderError | None] = []
        for fut in futures:
            if fut.done() and not fut.cancelled():
                results.append(fut.result())
            else:
                results.append(RetryExhaustedError("job-board lookup timed out", retryable=True))
        notes: list[str] = []
        for (slug, ats), res in zip(combos, results, strict=True):
            if not isinstance(res, _Fetched) or not res.jobs:
                continue
            verdict, detail = self._assess(domain, ats, slug, res)
            if verdict == "rejected":
                notes.append(detail)
                continue
            self._boards[domain] = Board(ats, slug, res.jobs, verdict, detail)
            self._notes[domain] = notes
            return self._boards[domain]
        errors = [r for r in results if isinstance(r, ProviderError)]
        if errors:
            first = errors[0]
            raise RetryExhaustedError(
                f"job-board lookup incomplete ({len(errors)} of {len(combos)} requests failed: {first}); "
                "not treating this as 'no jobs'",
                retryable=True,
                status=first.status,
            )
        self._boards[domain] = None
        self._notes[domain] = notes
        return None

    # -- DataSource.search_jobs ------------------------------------------

    def search_jobs(self, domain: str, role_terms: list[str], since_date: date, limit: int) -> ProviderResult:
        clean = normalize_domain(domain)
        needles = _wanted_titles(role_terms)
        limit = max(1, min(int(limit), MAX_JOB_LIMIT))
        body = {"domain": clean, "role_terms": list(role_terms), "since": since_date.isoformat(), "limit": limit}
        board = self.find_board(clean)
        if board is None:
            rejected = self._notes.get(clean) or []
            msg = "no match: no public ATS board found" + (f" ({'; '.join(rejected)})" if rejected else "")
            return ProviderResult(PROVIDER, "ats:none", body, [], 0, None, None, 1, [msg])
        ats, slug, raw_jobs, match, detail = board
        notes = [f"source: {ats} board '{slug}' (public API, {len(raw_jobs)} listings, no credits); {detail}"]
        items: list[NormalizedItem] = []
        seen: set[str] = set()
        undated = 0
        for raw in raw_jobs:
            norm = _NORMALIZERS[ats](raw)
            if norm is None:
                continue
            payload, job_id = norm
            payload = payload.model_copy(update={"board_match": match})
            flat_title = _flat(payload.title)
            if payload.role_group == "non_technical" or not any(n in flat_title for n in needles):
                continue
            if payload.date_added:
                try:
                    if date.fromisoformat(payload.date_added) < since_date:
                        continue
                except ValueError:
                    pass
            else:
                undated += 1
            dedup = f"job:{ats}:{job_id}" if job_id else f"job:{payload.url or payload.title}"
            if dedup in seen:
                continue
            seen.add(dedup)
            items.append(
                NormalizedItem(
                    kind=EvidenceKind.JOB_POSTING,
                    subject_domain=clean,
                    payload=payload,
                    source_url=payload.url,
                    source_record_id=job_id,
                    valid_from=payload.date_added,
                    valid_to=None,
                    field_coverage=payload_coverage(payload),
                    raw_hash=canonical_hash(raw),
                    dedup_key=dedup,
                    independence_group=f"ats:{ats}:{slug}:job",
                )
            )
            if len(items) >= limit:
                notes.append(f"truncated at limit={limit}")
                break
        if undated:
            notes.append(f"{undated} posting(s) have no posted date; kept without date filtering")
        if not items:
            notes.append("no match")
        return ProviderResult(PROVIDER, f"ats:{ats}:{slug}", body, items, len(items), None, None, 1, notes)


__all__ = ["AtsJobSource", "Board", "derive_slugs"]
