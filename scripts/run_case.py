"""CLI runner for traced DealScope runs (used for neatlogs evidence).

  python scripts/run_case.py case --scenario scenario_a            # synthetic run
  python scripts/run_case.py case --live --target t.com --peers a.com b.com c.com --thesis "..." --budget 60
  python scripts/run_case.py failure                                # 503x3 -> partial -> restart -> resume
  python scripts/run_case.py eval --scenario scenario_a             # baseline vs improved on the same fixture

Results (metrics + trace ids, no secrets) are written to evidence/neatlogs/*.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dealscope.agent.orchestrator import build_orchestrator  # noqa: E402
from dealscope.budget.governor import CreditGovernor  # noqa: E402
from dealscope.config import Settings  # noqa: E402
from dealscope.domain.enums import RunMode  # noqa: E402
from dealscope.domain.models import CaseInput  # noqa: E402
from dealscope.observability import tracing  # noqa: E402
from dealscope.persistence.repository import Repository  # noqa: E402

FIX = ROOT / "fixtures"
OUT = ROOT / "evidence" / "neatlogs"
NO_LLM = False  # set by --no-llm: deterministic planner + deterministic findings only
DETERMINISTIC_PLANNER = False  # set by --deterministic-planner: LLM used only for memo drafting


def init(settings: Settings) -> bool:
    key = settings.neatlogs_api_key.get_secret_value() if settings.neatlogs_api_key else None
    enabled = tracing.init_tracing(key, workflow_name="dealscope", record_to=settings.dealscope_db_path)
    print(f"neatlogs tracing: {'ENABLED' if enabled else 'DISABLED (no NEATLOGS_API_KEY)'}")
    return enabled


def fixture_input(scenario: str, **kw) -> CaseInput:
    c = json.loads((FIX / f"{scenario}.json").read_text(encoding="utf-8"))["case"]
    return CaseInput(
        target_domain=c["target_domain"],
        competitor_domains=c["competitor_domains"],
        deal_thesis=c["deal_thesis"],
        mode=RunMode.SYNTHETIC,
        **kw,
    )


def summarize(repo: Repository, settings: Settings, case_id: str, result, elapsed: float) -> dict:
    state = repo.load_case(case_id)
    report = repo.latest_report(case_id) or {}
    bundle = report.get("bundle", {})
    pool = "synthetic" if state.mode == RunMode.SYNTHETIC else "live"
    budget = CreditGovernor(repo, settings, pool=pool).case_summary(case_id, state.credit_budget)
    traces = [e["payload"].get("trace_id") for e in repo.list_events(case_id) if e["type"] == "trace"]
    plans = [
        f"{e['payload']['action']} ({e['payload']['decided_by']})"
        for e in repo.list_events(case_id)
        if e["type"] == "plan"
    ]
    sc = state.scorecard
    return {
        "case_id": case_id,
        "mode": state.mode.value,
        "run_label": state.run_label,
        "stage": state.stage.value,
        "finish_reason": state.finish_reason,
        "trace_ids": [t for t in traces if t],
        "tool_calls": state.tool_call_count,
        "planner_turns": state.iteration_count,
        "plan_sequence": plans,
        "elapsed_seconds": round(elapsed, 2),
        "credits": {k: str(v) for k, v in budget.items()},
        "scorecard": None
        if sc is None
        else {
            "risk_score": sc.risk_score,
            "coverage_pct": sc.coverage_pct,
            "evidence_confidence": sc.evidence_confidence,
            "signals": {s.signal_id.value: [s.state.value, s.score] for s in sc.signals},
        },
        "verification_published": bundle.get("verification", {}).get("metrics"),
        "verification_draft_llm": bundle.get("verification", {}).get("draft_metrics"),
        "llm_model": bundle.get("run", {}).get("llm_model"),
        "narrative_available": bundle.get("run", {}).get("narrative_available"),
    }


def run_one(
    settings, repo, mode, case_input, *, scenario=None, faults=None, variant="improved", resume=False, case_id=None
) -> dict:
    orch = build_orchestrator(
        settings,
        mode,
        repo=repo,
        fixture_path=(FIX / f"{scenario}.json") if scenario else None,
        faults=faults,
        synthesis_variant=variant,
        as_of=date.today(),
        llm=None if NO_LLM else "auto",
    )
    if DETERMINISTIC_PLANNER:
        from dealscope.agent.planner import Planner

        orch.planner = Planner(None)  # identical, rule-based investigation for both eval variants
    if case_id is None:
        case_id = orch.create_case(case_input, run_label=variant).case_id
    t0 = time.monotonic()
    result = orch.run(case_id, resume=resume)
    return summarize(repo, settings, case_id, result, time.monotonic() - t0)


def save(name: str, data: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="run without the runtime LLM (deterministic planner)")
    ap.add_argument("--deterministic-planner", action="store_true", help="use the LLM only for memo drafting")
    ap.add_argument("--model", help="override LLM_MODEL for this run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("case")
    c.add_argument("--scenario", default="scenario_a")
    c.add_argument("--variant", default="improved", choices=["baseline", "improved"])
    c.add_argument("--live", action="store_true")
    c.add_argument("--target")
    c.add_argument("--peers", nargs="*")
    c.add_argument("--thesis")
    c.add_argument("--budget", type=Decimal, default=Decimal("60"))
    f = sub.add_parser("failure")
    f.add_argument("--scenario", default="scenario_a")
    e = sub.add_parser("eval")
    e.add_argument("--scenario", default="scenario_a")
    args = ap.parse_args()
    global NO_LLM, DETERMINISTIC_PLANNER
    NO_LLM = args.no_llm
    DETERMINISTIC_PLANNER = args.deterministic_planner

    settings = Settings(**({"llm_model": args.model} if args.model else {}))
    init(settings)
    repo = Repository(settings.dealscope_db_path)
    try:
        if args.cmd == "case":
            if args.live:
                ci = CaseInput(
                    target_domain=args.target,
                    competitor_domains=args.peers or [],
                    deal_thesis=args.thesis,
                    max_case_credits=args.budget,
                    mode=RunMode.LIVE,
                )
                from dealscope.providers.crustdata import CrustdataClient

                idc = CrustdataClient(
                    settings.crustdata_api_key.get_secret_value(),
                    api_version=settings.crustdata_api_version,
                    base_url=settings.crustdata_base_url,
                    timeout_s=25,
                    max_retries=1,
                )
                checks = [idc.identify_company(d) for d in ci.all_domains()]  # free (FR-01)
                bad = [c for c in checks if not c.ok]
                for c in checks:
                    print(f"identity {c.domain}: {c.status} {c.resolved_name or ''} ({c.match_count} matches)")
                if bad:
                    print("Refusing live run: fix ambiguous/unknown domains first (no credits spent).")
                    return 2
                out = run_one(settings, repo, RunMode.LIVE, ci, variant=args.variant)
            else:
                out = run_one(
                    settings,
                    repo,
                    RunMode.SYNTHETIC,
                    fixture_input(args.scenario),
                    scenario=args.scenario,
                    variant=args.variant,
                )
            print(json.dumps(out, indent=2, default=str))
            print("saved:", save(f"{'live' if args.live else 'synthetic'}-run", out))
        elif args.cmd == "failure":
            first = run_one(
                settings,
                repo,
                RunMode.SYNTHETIC,
                fixture_input(args.scenario),
                scenario=args.scenario,
                faults={"enrich_company": [503, 503, 503]},
            )
            tracing.flush()
            # Simulated restart: fresh repository connection + orchestrator, then explicit resume.
            repo.close()
            repo = Repository(settings.dealscope_db_path)
            second = run_one(
                settings, repo, RunMode.SYNTHETIC, None, scenario=args.scenario, resume=True, case_id=first["case_id"]
            )
            out = {
                "injected": "enrich_company: 503, 503, 503 (2 retries then RETRY_EXHAUSTED)",
                "first_run": first,
                "after_restart_resume": second,
            }
            print(json.dumps(out, indent=2, default=str))
            print("saved:", save("failure-recovery", out))
        else:
            base = run_one(
                settings,
                repo,
                RunMode.SYNTHETIC,
                fixture_input(args.scenario),
                scenario=args.scenario,
                variant="baseline",
            )
            imp = run_one(
                settings,
                repo,
                RunMode.SYNTHETIC,
                fixture_input(args.scenario),
                scenario=args.scenario,
                variant="improved",
            )
            out = {"scenario": args.scenario, "baseline": base, "improved": imp}
            print(json.dumps(out, indent=2, default=str))
            print("saved:", save("baseline-vs-improved", out))
    finally:
        tracing.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
