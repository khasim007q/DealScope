"""Opt-in live Crustdata smoke test. Never prints the API key.

Usage (from repo root, with CRUSTDATA_API_KEY in .env):
  python scripts/live_smoke.py --pricing             # FREE: account balance + per-endpoint prices for our endpoints
  python scripts/live_smoke.py --enrich example.com  # ONE metered company enrichment (~2 credits)

Writes a sanitized summary (key paths, credits, field coverage — no raw values) to evidence/crustdata/ and the
normalized payload to reports/live/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dealscope.config import Settings  # noqa: E402
from dealscope.domain.models import normalize_domain  # noqa: E402
from dealscope.providers.crustdata import CrustdataClient  # noqa: E402

ENDPOINTS = ["/company/enrich", "/person/search", "/job/search"]


def key_paths(obj, prefix: str = "", depth: int = 0, max_depth: int = 4) -> list[str]:
    """Structure only (no values) so we can confirm undocumented key spellings."""
    out: list[str] = []
    if depth > max_depth:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.append(p)
            out.extend(key_paths(v, p, depth + 1, max_depth))
    elif isinstance(obj, list) and obj:
        out.extend(key_paths(obj[0], prefix + "[]", depth + 1, max_depth))
    return out


def client(settings: Settings) -> CrustdataClient:
    if settings.crustdata_api_key is None:
        sys.exit("CRUSTDATA_API_KEY is not set in .env — live smoke test refused (no fixture fallback).")
    return CrustdataClient(
        settings.crustdata_api_key.get_secret_value(),
        api_version=settings.crustdata_api_version,
        base_url=settings.crustdata_base_url,
        timeout_s=settings.dealscope_http_timeout_seconds,
        max_retries=settings.dealscope_max_retries,
    )


def credits_of(c: CrustdataClient):
    acct = c.account_credits().get("account", {})
    return acct.get("credits")


def pricing(c: CrustdataClient) -> dict:
    out = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "balance": credits_of(c), "endpoints": {}}
    for path in ENDPOINTS:
        data = c.endpoint_pricing(path)
        eps = data.get("endpoints") if isinstance(data, dict) else None
        eps = eps if isinstance(eps, list) else [data]
        for ep in eps:
            if not isinstance(ep, dict):
                continue
            out["endpoints"][ep.get("path", path)] = {
                k: ep.get(k)
                for k in (
                    "status",
                    "base_credits",
                    "effective_rate_limit_rpm",
                    "premium_fields",
                    "premium_filters",
                    "premium_modes",
                )
                if k in ep
            }
    return out


def enrich(c: CrustdataClient, domain: str) -> dict:
    captured: dict = {}

    def hook(response: httpx.Response) -> None:
        if response.request.url.path.endswith("/company/enrich"):
            response.read()
            try:
                captured["raw"] = response.json()
            except ValueError:
                captured["raw"] = None
            captured["credits_header"] = response.headers.get("x-credits-used")
            captured["request_id"] = response.headers.get("x-request-id")

    c._http.event_hooks["response"].append(hook)  # noqa: SLF001 - smoke-test instrumentation only
    before = credits_of(c)
    result = c.enrich_company(domain)
    after = credits_of(c)
    raw = captured.get("raw")
    company = None
    if isinstance(raw, list) and raw and raw[0].get("matches"):
        company = raw[0]["matches"][0].get("company_data")
    paths = [p for p in key_paths(company or {}) if p.split(".")[0] in {"basic_info", "headcount", "hiring", "funding"}]
    function_keys = (
        sorted(
            ((company or {}).get("headcount") or {})
            .get("by_function_timeseries", {})
            .get("CURRENT_FUNCTION", {})
            .keys()
        )
        if company
        else []
    )
    role_keys = (
        sorted((((company or {}).get("headcount") or {}).get("by_role_absolute") or {}).keys()) if company else []
    )
    item = result.items[0] if result.items else None
    return {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "domain": domain,
        "items": len(result.items),
        "notes": result.notes,
        "attempts": result.attempts,
        "x_credits_used": captured.get("credits_header"),
        "request_id": captured.get("request_id"),
        "balance_before": before,
        "balance_after": after,
        "field_coverage": item.field_coverage if item else [],
        "function_timeseries_keys": function_keys,
        "by_role_keys": role_keys,
        "key_paths": paths[:200],
        "normalized_payload": item.payload.model_dump() if item else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pricing", action="store_true")
    ap.add_argument("--enrich", metavar="DOMAIN")
    args = ap.parse_args()
    if not (args.pricing or args.enrich):
        ap.error("choose --pricing and/or --enrich DOMAIN")
    settings = Settings()
    c = client(settings)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (ROOT / "evidence" / "crustdata").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "live").mkdir(parents=True, exist_ok=True)
    if args.pricing:
        p = pricing(c)
        (ROOT / "evidence" / "crustdata" / f"pricing-{stamp}.json").write_text(json.dumps(p, indent=2, default=str))
        print(json.dumps(p, indent=2, default=str))
    if args.enrich:
        domain = normalize_domain(args.enrich)
        r = enrich(c, domain)
        payload = r.pop("normalized_payload")
        (ROOT / "reports" / "live" / f"enrich-{domain}-{stamp}.json").write_text(json.dumps(payload, indent=2))
        (ROOT / "evidence" / "crustdata" / f"smoke-enrich-{stamp}.json").write_text(
            json.dumps(r, indent=2, default=str)
        )
        print(json.dumps({**r, "key_paths": f"{len(r['key_paths'])} paths (see evidence file)"}, indent=2, default=str))
        print("normalized payload:", json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
