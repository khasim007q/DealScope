"""FastAPI server for the DealScope web UI (contract: frontend/src/api/types.ts).

Run:  .venv/Scripts/uvicorn dealscope.api.server:app --port 8000   (serves frontend/dist at / when built)
Investigations run in background threads; the UI polls GET /api/cases/{id}. State lives in SQLite, so a server
restart loses nothing and a partial case can be resumed.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from dealscope.agent.orchestrator import ConfigError, build_orchestrator
from dealscope.api import evidence as evidence_mod
from dealscope.api import views
from dealscope.budget.governor import CreditGovernor
from dealscope.config import Settings, get_settings
from dealscope.domain.enums import RunMode
from dealscope.domain.models import CaseInput, normalize_domain
from dealscope.observability import tracing
from dealscope.persistence import featured
from dealscope.persistence.repository import Repository
from dealscope.providers.base import ProviderError

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
DIST = ROOT / "frontend" / "dist"

SCENARIOS = {
    "scenario_a": (
        "Scenario A - engineering lags the company",
        "Engineering headcount shrinks while the company grows, several critical roles are open and senior "
        "leaders have left. Shows the agent prioritising hiring and continuity checks.",
    ),
    "scenario_b": (
        "Scenario B - steady growth, thin history",
        "Engineering keeps pace with the company but most profile histories lack dates. Shows the agent "
        "choosing a different path: broadening people coverage instead of hiring checks.",
    ),
    "synthetic_case": (
        "Original spec fixture",
        "The minimal example from the specification: one departure, one reposted role.",
    ),
}
FAULTS = {
    "none": ("No failure", "Normal run.", None),
    "retry_success": (
        "Temporary outage, then recovery",
        "The first company lookup fails twice (HTTP 503) and succeeds on the third attempt.",
        {"enrich_company": [503, 503]},
    ),
    "retry_exhausted": (
        "Outage that outlasts retries",
        "The first company lookup fails three times. The case ends as partial; press Resume to "
        "recover without repeating completed requests.",
        {"enrich_company": [503, 503, 503]},
    ),
    "auth_failure": (
        "Rejected credentials",
        "The provider rejects the key (HTTP 401). The agent stops cleanly and never substitutes demo data.",
        {"enrich_company": [401]},
    ),
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = _settings()
    tracing.init_tracing(workflow_name="dealscope", record_to=s.dealscope_db_path)
    repo = _repo()
    try:
        imported = featured.import_all(repo)
        if imported:
            log.info("imported featured cases: %s", imported)
    except Exception:  # a bad fixture must not stop the server
        log.exception("featured case import failed")
    finally:
        repo.close()
    yield
    tracing.shutdown()


app = FastAPI(title="DealScope API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_runs: dict[str, threading.Thread] = {}
_cancels: dict[str, threading.Event] = {}
_runs_lock = threading.Lock()


def _settings() -> Settings:
    return get_settings()


def _repo() -> Repository:
    return Repository(_settings().dealscope_db_path)


def _running(case_id: str) -> bool:
    with _runs_lock:
        t = _runs.get(case_id)
        return bool(t and t.is_alive())


def _start_thread(case_id: str, mode: RunMode, scenario: Path | None, faults: dict | None, resume: bool) -> None:
    cancel = threading.Event()

    def work() -> None:
        repo = _repo()
        try:
            orch = build_orchestrator(_settings(), mode, repo=repo, fixture_path=scenario, faults=faults)
            orch.cancel_event = cancel
            try:
                orch.run(case_id, resume=resume)
            finally:
                orch.close()
        except Exception:  # state is persisted as failed by the orchestrator; log for the operator
            log.exception("run failed for %s", case_id)
        finally:
            repo.close()

    t = threading.Thread(target=work, name=f"run-{case_id}", daemon=True)
    with _runs_lock:
        _runs[case_id] = t
        _cancels[case_id] = cancel
    t.start()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateCase(BaseModel):
    target_domain: str
    competitor_domains: list[str] = Field(default_factory=list, max_length=5)
    deal_thesis: str | None = None
    lookback_months: int = 12
    max_case_credits: float = 40
    mode: Literal["live", "synthetic"] = "synthetic"
    scenario_id: str | None = None
    fault_id: str | None = None


class IdentityRequest(BaseModel):
    domains: list[str] = Field(min_length=1, max_length=6)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/status")
def status() -> dict:
    s = _settings()
    repo = _repo()
    try:
        g = CreditGovernor(repo, s, pool="live").global_summary()
    finally:
        repo.close()
    st = s.public_status()
    free = s.data_provider == "free"
    llm_row = {
        "key": "llm",
        "label": "AI planner and writer (Gemini)",
        "connected": bool(st["llm_key_present"]),
        "detail": f"Model: {s.llm_model}" if st["llm_key_present"] else "No API key - rule-based planner only",
    }
    crust_row = {
        "key": "crustdata",
        "label": "Company data (Crustdata)" if not free else "Crustdata (optional, paid)",
        "connected": bool(st["crustdata_key_present"]),
        "detail": "Connected" if st["crustdata_key_present"] else "No API key - live runs disabled",
    }
    if free:
        crust_row["optional"] = True
        crust_row["detail"] = "Key set" if st["crustdata_key_present"] else "Not set (not needed)"
    if free:
        providers = [
            {
                "key": "job_boards",
                "label": "Public job boards (free)",
                "connected": True,
                "detail": "Greenhouse, Lever and Ashby boards - no key needed",
            },
            {
                "key": "pdl",
                "label": "People Data Labs (free tier)",
                "connected": bool(st["pdl_key_present"]),
                "optional": True,
                "detail": "Key set"
                if st["pdl_key_present"]
                else "Key not set - company and people signals are not scored",
            },
            crust_row,
            llm_row,
        ]
    else:
        providers = [
            crust_row,
            llm_row,
            {
                "key": "jobs_pricing",
                "label": "Job postings pricing",
                "connected": bool(st["jobs_price_configured"]),
                "detail": "Price confirmed from account"
                if st["jobs_price_configured"]
                else "Price not confirmed - job searches blocked in live mode",
            },
        ]
    budget = {k: float(g[k]) for k in ("spendable", "estimated_used", "actual_used", "reserved", "remaining")}
    budget.update(
        unknown_calls=int(g["unknown_count"]),
        reserve=float(s.crustdata_global_reserve_credits),
        total=float(s.crustdata_total_credits),
    )
    return {
        "providers": providers,
        "live_budget": budget,
        "max_case_credits": float(s.crustdata_max_case_credits),
        "live_available": True if free else bool(st["crustdata_key_present"]),
        "data_provider": s.data_provider,
        "pdl_key_present": bool(st["pdl_key_present"]),
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    out = []
    for sid, (label, desc) in SCENARIOS.items():
        path = FIXTURES / f"{sid}.json"
        if not path.exists():
            continue
        c = json.loads(path.read_text(encoding="utf-8")).get("case", {})
        out.append(
            {
                "id": sid,
                "label": label,
                "description": desc,
                "target_domain": c.get("target_domain", ""),
                "competitor_domains": c.get("competitor_domains", []),
                "deal_thesis": c.get("deal_thesis", ""),
            }
        )
    return out


@app.get("/api/evidence-summary")
def evidence_summary() -> dict:
    s = _settings()
    repo = _repo()
    try:
        g = CreditGovernor(repo, s, pool="live").global_summary()
    finally:
        repo.close()
    return evidence_mod.evidence_summary(g, s)


@app.get("/api/featured")
def featured_cases() -> list[dict]:
    return [
        {
            "case_id": d["state"]["case_id"],
            "label": d["label"],
            "description": d["description"],
            "recorded_at": d["recorded_at"],
        }
        for d in featured.featured_docs()
    ]


@app.get("/api/faults")
def faults() -> list[dict]:
    return [{"id": k, "label": v[0], "description": v[1]} for k, v in FAULTS.items()]


_PROVIDER_ERROR_TEXT = {
    "NOT_CONFIGURED": "Company lookup is not configured on this server.",
    "AUTH": "The company-data provider rejected the server's key.",
    "PERMISSION": "The company-data provider rejected the server's key.",
    "INSUFFICIENT_CREDITS": "The company-data provider account is out of credits.",
    "PDL_MONTHLY_LIMIT": "This month's free company-data quota is used up.",
    "RETRY_EXHAUSTED": "The company-data provider is not responding right now. Try again shortly.",
    "UNKNOWN_OUTCOME": "The connection dropped while checking this domain. Try again shortly.",
    "BAD_REQUEST": "The company-data provider could not check this domain.",
    "SCHEMA": "The company-data provider returned something unexpected.",
}


def _identity_error(raw: str, message: str) -> dict:
    return {
        "domain": raw,
        "ok": False,
        "status": "error",
        "resolved_name": None,
        "match_count": 0,
        "message": message,
        "candidates": [],
    }


@app.post("/api/identity-check")
def identity_check(req: IdentityRequest) -> list[dict]:
    s = _settings()
    close = None
    if s.data_provider == "free":
        if s.pdl_api_key is None:
            # Public job boards need no key but cannot verify identity: let the search proceed, unverified.
            out = []
            for raw in req.domains:
                try:
                    dom = normalize_domain(raw)
                except ValueError as exc:
                    out.append(_identity_error(raw, f"Not a valid company domain: {exc}"))
                    continue
                out.append(
                    {
                        "domain": dom,
                        "ok": True,
                        "status": "unverified",
                        "resolved_name": None,
                        "match_count": 0,
                        "message": "Not verified: no company-data key set. Public job boards only.",
                        "candidates": [],
                    }
                )
            return out
        from dealscope.providers.free_source import FreeDataSource

        client = FreeDataSource.from_settings(s)
        close = client.close
    else:
        if s.crustdata_api_key is None:
            raise HTTPException(400, "Live data is not configured (no Crustdata API key).")
        from dealscope.providers.crustdata import CrustdataClient

        client = CrustdataClient(
            s.crustdata_api_key.get_secret_value(),
            api_version=s.crustdata_api_version,
            base_url=s.crustdata_base_url,
            timeout_s=s.dealscope_http_timeout_seconds,
            max_retries=s.dealscope_max_retries,
        )
    out = []
    try:
        for raw in req.domains:
            try:
                out.append(views.identity_view(client.identify_company(normalize_domain(raw))))
            except ValueError as exc:
                out.append(_identity_error(raw, f"Not a valid company domain: {exc}"))
            except ProviderError as exc:
                out.append(
                    _identity_error(raw, _PROVIDER_ERROR_TEXT.get(exc.code, "Could not check this domain right now."))
                )
            except Exception as exc:  # network error: surface it, nothing metered was attempted
                out.append(_identity_error(raw, f"Could not check this domain right now ({type(exc).__name__})."))
    finally:
        if close is not None:
            close()
    return out


@app.post("/api/cases")
def create_case(req: CreateCase) -> dict:
    s = _settings()
    mode = RunMode(req.mode)
    try:
        case_input = CaseInput(
            target_domain=req.target_domain,
            competitor_domains=req.competitor_domains,
            deal_thesis=req.deal_thesis,
            lookback_months=req.lookback_months,
            max_case_credits=Decimal(str(req.max_case_credits)),
            mode=mode,
        )
    except ValidationError as exc:
        msg = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
        raise HTTPException(422, msg) from exc
    scenario = faults_cfg = None
    if mode == RunMode.SYNTHETIC:
        sid = req.scenario_id or "scenario_a"
        if sid not in SCENARIOS:
            raise HTTPException(422, f"Unknown scenario {sid}")
        scenario = FIXTURES / f"{sid}.json"
        faults_cfg = FAULTS.get(req.fault_id or "none", FAULTS["none"])[2]
    repo = _repo()
    try:
        orch = build_orchestrator(s, mode, repo=repo, fixture_path=scenario, faults=faults_cfg, llm=None)
        try:
            state = orch.create_case(case_input)
        finally:
            orch.close()
        if mode == RunMode.SYNTHETIC:
            repo.add_event(state.case_id, "scenario", {"scenario_id": req.scenario_id or "scenario_a"})
    except ConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        repo.close()
    _start_thread(state.case_id, mode, scenario, faults_cfg, resume=False)
    return {"case_id": state.case_id}


_PROVIDER_LABEL = {"free": "free (public job boards)", "crustdata": "Crustdata (paid)"}


def _case_provider(case_id: str, events: list[dict]) -> str | None:
    """Data provider a live case ran with: recorded at creation, else inferred from its stored evidence."""
    for e in events:
        if e["type"] == "case_created" and e["payload"].get("provider") in ("free", "crustdata"):
            return e["payload"]["provider"]
    repo = _repo()
    try:
        providers = {ev.source_provider for ev in repo.get_evidence(case_id)} & {"free", "crustdata"}
    finally:
        repo.close()
    return providers.pop() if len(providers) == 1 else None


@app.post("/api/cases/{case_id}/resume")
def resume_case(case_id: str) -> dict:
    repo = _repo()
    try:
        state = repo.load_case(case_id)
        events = repo.list_events(case_id) if state else []
    finally:
        repo.close()
    if state is None:
        raise HTTPException(404, "Case not found")
    if _running(case_id):
        raise HTTPException(409, "This case is already running")
    if state.mode == RunMode.LIVE:
        used = _case_provider(case_id, events)
        current = _settings().data_provider
        if used is not None and used != current:
            raise HTTPException(
                409,
                f"This investigation was run with the {_PROVIDER_LABEL.get(used, used)} data source, but the "
                f"server is now set to {_PROVIDER_LABEL.get(current, current)}. Resuming would mix evidence from "
                "two sources, so start a new investigation instead.",
            )
    scenario = None
    if state.mode == RunMode.SYNTHETIC:
        sid = next((e["payload"].get("scenario_id") for e in events if e["type"] == "scenario"), "scenario_a")
        scenario = FIXTURES / f"{sid if sid in SCENARIOS else 'scenario_a'}.json"
    _start_thread(case_id, state.mode, scenario, None, resume=True)
    return {"case_id": case_id}


@app.post("/api/cases/{case_id}/cancel")
def cancel_case(case_id: str) -> dict:
    with _runs_lock:
        t, ev = _runs.get(case_id), _cancels.get(case_id)
    if not (t and t.is_alive() and ev):
        raise HTTPException(409, "This case is not running")
    ev.set()
    return {"case_id": case_id}


@app.get("/api/cases")
def list_cases() -> list[dict]:
    repo = _repo()
    try:
        out = []
        for row in repo.list_cases()[:100]:
            st = repo.load_case(row["case_id"])
            if st is not None:
                out.append(views.case_list_item(st, _running(st.case_id)))
        return out
    finally:
        repo.close()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    s = _settings()
    repo = _repo()
    try:
        state = repo.load_case(case_id)
        if state is None:
            raise HTTPException(404, "Case not found")
        pool = "synthetic" if state.mode == RunMode.SYNTHETIC else "live"
        summary = CreditGovernor(repo, s, pool=pool).case_summary(case_id, state.credit_budget)
        return views.case_view(
            state,
            repo.get_evidence(case_id),
            repo.list_events(case_id),
            repo.latest_report(case_id),
            summary,
            _running(case_id),
            s,
        )
    finally:
        repo.close()


@app.get("/api/cases/{case_id}/traces")
def case_traces(case_id: str) -> list[dict]:
    repo = _repo()
    try:
        if repo.load_case(case_id) is None:
            raise HTTPException(404, "Case not found")
        return repo.list_traces(case_id)
    finally:
        repo.close()


@app.get("/api/cases/{case_id}/report.md", response_class=PlainTextResponse)
def report_md(case_id: str) -> PlainTextResponse:
    repo = _repo()
    try:
        rep = repo.latest_report(case_id)
    finally:
        repo.close()
    if rep is None:
        raise HTTPException(404, "No report yet")
    return PlainTextResponse(
        rep["markdown"],
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="dealscope-{case_id}.md"'},
    )


@app.get("/api/cases/{case_id}/bundle.json")
def report_bundle(case_id: str) -> JSONResponse:
    repo = _repo()
    try:
        rep = repo.latest_report(case_id)
    finally:
        repo.close()
    if rep is None:
        raise HTTPException(404, "No report yet")
    return JSONResponse(
        json.loads(json.dumps(rep["bundle"], default=str)),
        headers={"Content-Disposition": f'attachment; filename="dealscope-{case_id}.json"'},
    )


# Serve the built single-page app (frontend/dist) with client-side routing fallback.
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (DIST / full_path).resolve()
        if full_path and DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
