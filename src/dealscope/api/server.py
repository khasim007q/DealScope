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

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures"
EVIDENCE = ROOT / "evidence"
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
    tracing.init_tracing(
        s.neatlogs_api_key.get_secret_value() if s.neatlogs_api_key else None, workflow_name="dealscope"
    )
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
            orch.run(case_id, resume=resume)
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
    competitor_domains: list[str]
    deal_thesis: str
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
    providers = [
        {
            "key": "crustdata",
            "label": "Company data (Crustdata)",
            "connected": bool(st["crustdata_key_present"]),
            "detail": "Connected" if st["crustdata_key_present"] else "No API key - live runs disabled",
        },
        {
            "key": "llm",
            "label": "AI planner and writer (Gemini)",
            "connected": bool(st["llm_key_present"]),
            "detail": f"Model: {s.llm_model}" if st["llm_key_present"] else "No API key - rule-based planner only",
        },
        {
            "key": "neatlogs",
            "label": "Run tracing (neatlogs)",
            "connected": tracing.tracing_enabled(),
            "detail": "Traces are being recorded" if tracing.tracing_enabled() else "Not connected",
        },
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
        "live_available": bool(st["crustdata_key_present"]),
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


@app.post("/api/identity-check")
def identity_check(req: IdentityRequest) -> list[dict]:
    s = _settings()
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
    for raw in req.domains:
        try:
            out.append(views.identity_view(client.identify_company(normalize_domain(raw))))
        except ValueError as exc:
            out.append(
                {
                    "domain": raw,
                    "ok": False,
                    "status": "error",
                    "resolved_name": None,
                    "match_count": 0,
                    "message": f"Not a valid company domain: {exc}",
                    "candidates": [],
                }
            )
        except Exception as exc:  # provider/network error: surface it, nothing metered was attempted
            out.append(
                {
                    "domain": raw,
                    "ok": False,
                    "status": "error",
                    "resolved_name": None,
                    "match_count": 0,
                    "message": f"Could not check this domain right now ({type(exc).__name__}).",
                    "candidates": [],
                }
            )
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
        state = orch.create_case(case_input)
        if mode == RunMode.SYNTHETIC:
            repo.add_event(state.case_id, "scenario", {"scenario_id": req.scenario_id or "scenario_a"})
    except ConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        repo.close()
    _start_thread(state.case_id, mode, scenario, faults_cfg, resume=False)
    return {"case_id": state.case_id}


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
        )
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


_EVIDENCE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}


@app.get("/api/evidence/{path:path}")
def evidence_file(path: str) -> FileResponse:
    target = (EVIDENCE / path).resolve()
    if EVIDENCE.resolve() not in target.parents or target.suffix.lower() not in _EVIDENCE_TYPES or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target)


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
