"""Partner-evidence summary for the judge-facing Evidence page (contract: EvidenceSummary in frontend/src/api/types.ts).

Everything is read from committed evidence files and git history; nothing here calls an external service.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence"
NEATLOGS = EVIDENCE / "neatlogs"

SCREENSHOT_CAPTIONS = {
    "213732": "Live Airtable investigation: real tool latencies, Gemini errors followed by successful retries",
    "213710": "Live Airtable memo regenerated via recover_run: Gemini 3.6-flash, 11,146 tokens, $0.02, "
    "no new data calls",
    "213609": "Resilience: several Gemini calls fail (free-tier quota / 503) and the run still finishes "
    "with a verified memo",
    "213651": "Resilience: failed and successful Gemini calls in one investigation",
    "213824": "Failure recovery, first run: target lookup fails after bounded retries, case ends partial",
    "213802": "Failure recovery, resume: recover_run retries only the failed lookup and completes",
    "213426": "Input/output summaries and the synthesis span: 2,175 tokens, $0.0015",
    "213450": "Complete synthetic run: enrichment, planning, scoring, searches, synthesis, verifier, memo",
    "213516": "Complete synthetic run with job search and AI drafting (5,510 tokens, $0.0026)",
    "213542": "Complete synthetic run (4,780 tokens, $0.0017)",
    "213854": "Earlier resume attempt that exposed the resume bug (superseded)",
    "213913": "Earlier first run paired with the superseded resume",
    "213929": "neatlogs delivery probe after the ingest outage",
}

# Targets and caveats for committed live-run files (see evidence/neatlogs/successful-run.md).
LIVE_RUN_NOTES = {
    "case-8ddc70b2b4de": (
        "retool.com vs appsmith.com, tooljet.com, budibase.com",
        " Trace likely incomplete: neatlogs ingest returned 503 during this run.",
    ),
    "case-289f654e60f5": (
        "airtable.com vs smartsheet.com, monday.com, clickup.com",
        " Memo regenerated with Gemini drafting in trace 81dd213dbdbc546acd906ecf44f66478.",
    ),
}

# Values verified from evidence/cfo-ai/DealScope-investor-summary.pdf (owner export, 2026-10-11).
CFO_SCENARIOS = [
    {
        "name": "Conservative",
        "revenue": "$30,000",
        "audits": "40",
        "gross_margin": "87.20%",
        "contribution_margin": "82.20%",
        "peak_funding_need": "$1,500",
    },
    {
        "name": "Base",
        "revenue": "$270,000",
        "audits": "180",
        "gross_margin": "93.69%",
        "contribution_margin": "90.02%",
        "peak_funding_need": "$0",
    },
    {
        "name": "Growth",
        "revenue": "$390,000",
        "audits": "390",
        "gross_margin": "90.54%",
        "contribution_margin": "86.79%",
        "peak_funding_need": "$0",
    },
]


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _neatlogs() -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for f in sorted(NEATLOGS.glob("live-run-*.json")):
        d = _load(f) or {}
        sc = d.get("scorecard") or {}
        risk = sc.get("risk_score")
        target, note = LIVE_RUN_NOTES.get(str(d.get("case_id")), (str(d.get("case_id")), ""))
        runs.append(
            {
                "label": f"Live investigation: {target}",
                "kind": "live",
                "case_id": d.get("case_id"),
                "trace_ids": d.get("trace_ids") or [],
                "summary": f"{d.get('stage')}; {d.get('tool_calls')} data requests; "
                f"{(d.get('credits') or {}).get('actual_used', '?')} credits confirmed; "
                f"risk {'not scored' if risk is None else round(risk)}; coverage {sc.get('coverage_pct', 0):.0f}%."
                f"{note}",
            }
        )
    for f in sorted(NEATLOGS.glob("failure-recovery-*.json")):
        d = _load(f) or {}
        first, second = d.get("first_run") or {}, d.get("after_restart_resume") or {}
        runs.append(
            {
                "label": "Failure recovery (synthetic)",
                "kind": "failure",
                "case_id": first.get("case_id"),
                "trace_ids": list(dict.fromkeys((first.get("trace_ids") or []) + (second.get("trace_ids") or []))),
                "summary": f"Injected {d.get('injected', 'failures')}. First run: {first.get('stage')} "
                f"({first.get('finish_reason')}). After restart and resume: {second.get('stage')}, "
                f"{second.get('tool_calls')} data requests, no completed request repeated.",
            }
        )
    eval_rows: list[dict[str, Any]] = []
    for f in sorted(NEATLOGS.glob("baseline-vs-improved-*.json")):
        d = _load(f) or {}
        scenario = str(d.get("scenario", "")).replace("scenario_", "").upper()
        for variant in ("baseline", "improved"):
            r = d.get(variant) or {}
            draft = r.get("verification_draft_llm") or {}
            pub = r.get("verification_published") or {}
            eval_rows.append(
                {
                    "scenario": scenario,
                    "variant": variant,
                    "trace_id": (r.get("trace_ids") or [None])[0],
                    "draft_claims": int(draft.get("total", 0)),
                    "draft_rejected": int(draft.get("rejected", 0)),
                    "draft_verified": int(draft.get("verified", 0)),
                    "draft_with_caveats": int(draft.get("qualified", 0)),
                    "published": int(pub.get("total", 0)),
                    "tool_calls": int(r.get("tool_calls", 0)),
                }
            )
        runs.append(
            {
                "label": f"Improvement experiment, scenario {scenario}",
                "kind": "eval",
                "case_id": None,
                "trace_ids": [t for v in ("baseline", "improved") for t in ((d.get(v) or {}).get("trace_ids") or [])],
                "summary": "Same investigation, two drafting prompts (loose baseline vs strict improved + verifier).",
            }
        )
    shots = sorted((NEATLOGS / "screenshots").glob("*.png"))
    order = list(SCREENSHOT_CAPTIONS)
    shots.sort(key=lambda p: next((i for i, k in enumerate(order) if k in p.name), len(order)))
    return {
        "runs": runs,
        "eval_rows": eval_rows,
        "eval_reading": (
            "Neither prompt produced unsupported claims on these fixtures (0 rejected in all four drafts), because the "
            "model only sees the evidence index with IDs in both variants. The strict prompt produced more claims that "
            "pass verification outright (A: 5 vs 2, B: 6 vs 1), fewer caveated claims, and explicit diligence "
            "questions. Small sample: one run per variant per scenario."
        ),
        "screenshots": [
            {"label": next((c for k, c in SCREENSHOT_CAPTIONS.items() if k in p.name), p.stem), "path": _rel(p)}
            for p in shots
        ],
    }


def _entire() -> dict[str, Any]:
    checkpoints: list[dict[str, str]] = []
    try:
        out = subprocess.run(
            ["git", "log", "--format=%h%x1f%s%x1f%(trailers:key=Entire-Checkpoint,valueonly,separator=%x2c)"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3 and parts[2].strip():
                checkpoints.append({"commit": parts[0], "subject": parts[1], "checkpoint": parts[2].strip()})
    except (OSError, subprocess.SubprocessError):
        pass
    transcript = next(iter(sorted((EVIDENCE / "entire").glob("transcript-*.md"))), None)
    shots = sorted((EVIDENCE / "entire" / "screenshots").glob("*.png"))
    return {
        "checkpoints": checkpoints,
        "screenshots": [
            {
                "label": "Entire session timeline: 10 checkpoints, 145 file changes, each commit linked to "
                "the Claude Code turns that produced it",
                "path": _rel(p),
            }
            for p in shots
        ],
        "transcript_path": _rel(transcript) if transcript else None,
        "notes": [
            "Each commit made after Entire was enabled carries an Entire-Checkpoint trailer that links it to the "
            "Claude Code session context that produced it.",
            "The build was multi-agent (Opus lead, Sonnet sub-agents); the session transcript makes those decisions "
            "auditable.",
            "Gotcha found: the commit hook asks an interactive question, which blocked non-interactive agent commits "
            "until the owner chose 'always'.",
        ],
    }


def _cfo() -> dict[str, Any]:
    folder = EVIDENCE / "cfo-ai"
    files = [{"label": p.name, "path": _rel(p)} for p in sorted(folder.glob("*")) if p.suffix in {".pdf", ".xlsx"}]
    return {
        "scenarios": CFO_SCENARIOS,
        "unit_cost": "$94.65 per audit: human QA $90 (1.5 h at $60), tooling $2, Crustdata $2.60 (26 credits at "
        "$0.10), LLM $0.05",
        "pricing": [
            "Per audit: $750 / $1,500 / $3,000",
            "Annual deal-team plan: $24,000 incl. 24 audits, $1,000 per extra audit",
            "Hybrid: $6,000/year workspace + $1,000 per audit",
        ],
        "notes": [
            "Pre-revenue: 0 customers, $0 revenue. All scenarios are hypotheses, not traction.",
            "Available cash is unknown, so runway is left blank instead of invented.",
            "Real runs fed back: live cases used 4.8-12.2 credits (model assumes 26) and measured Gemini drafting cost "
            "$0.0015-$0.02 per call (model assumes $0.05), so modeled data and AI costs are conservative.",
        ],
        "files": files,
    }


def _crustdata(global_summary: dict[str, Any], settings: Any) -> dict[str, Any]:
    pricing = sorted((EVIDENCE / "crustdata").glob("pricing-*.json"))
    prices: list[dict[str, str]] = []
    if pricing:
        d = _load(pricing[-1]) or {}
        for ep, info in (d.get("endpoints") or {}).items():
            extra = ", ".join(f"{x['field']} +{x['credits']}" for x in (info.get("premium_fields") or [])[:2])
            prices.append(
                {"endpoint": ep, "credits": f"{info.get('base_credits')} base" + (f" ({extra})" if extra else "")}
            )
    return {
        "total": float(settings.crustdata_total_credits),
        "reserve": float(settings.crustdata_global_reserve_credits),
        "spendable": float(global_summary["spendable"]),
        "actual_used": float(global_summary["actual_used"]),
        "estimated_used": float(global_summary["estimated_used"]),
        "remaining": float(global_summary["remaining"]),
        "prices": prices,
        "notes": [
            "Every paid call reserves credits first and is refused if it would exceed the case cap or touch the "
            "reserve; unknown prices are blocked.",
            "Actual cost comes from Crustdata's X-Credits-Used response header.",
            "A free identity check runs before any paid call, after an ambiguous domain (notion.so) cost 6 credits.",
            "Figures exclude the 2-credit smoke test made outside the app.",
        ],
    }


def evidence_summary(global_summary: dict[str, Any], settings: Any) -> dict[str, Any]:
    return {
        "neatlogs": _neatlogs(),
        "entire": _entire(),
        "cfo": _cfo(),
        "crustdata": _crustdata(global_summary, settings),
    }
