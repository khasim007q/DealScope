"""DealScope Streamlit workspace: create a case, run/resume the bounded investigation, review the verified memo."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from dealscope.agent.orchestrator import ConfigError, build_orchestrator
from dealscope.budget.governor import CreditGovernor
from dealscope.config import get_settings
from dealscope.domain.enums import RunMode
from dealscope.domain.models import CaseInput
from dealscope.observability import tracing
from dealscope.persistence.repository import Repository

ROOT = Path(__file__).resolve().parent
SCENARIOS = {
    "Scenario A — engineering lags headcount, critical roles open": ROOT / "fixtures" / "scenario_a.json",
    "Scenario B — no trajectory concern, undated histories": ROOT / "fixtures" / "scenario_b.json",
    "Original spec fixture (synthetic_case.json)": ROOT / "fixtures" / "synthetic_case.json",
}
SYNTHETIC_BANNER = "SYNTHETIC DEMO DATA — NOT A REAL COMPANY ASSESSMENT"

st.set_page_config(page_title="DealScope", page_icon="🔎", layout="wide")
settings = get_settings()


@st.cache_resource
def _init_tracing() -> bool:
    key = settings.neatlogs_api_key.get_secret_value() if settings.neatlogs_api_key else None
    return tracing.init_tracing(key, workflow_name="dealscope")


@st.cache_resource
def _repo() -> Repository:
    return Repository(settings.dealscope_db_path)


traced = _init_tracing()
repo = _repo()


def _orchestrator(mode: RunMode, scenario: Path | None = None, faults: dict | None = None):
    return build_orchestrator(settings, mode, repo=repo, fixture_path=scenario, faults=faults)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🔎 DealScope")
    st.caption("Evidence-led outside-in organizational diligence")
    status = settings.public_status()
    st.subheader("Providers")
    st.write(f"Crustdata key: {'✅' if status['crustdata_key_present'] else '❌ (live mode disabled)'}")
    st.write(
        f"LLM ({status['llm_provider']} · {status['llm_model']}): "
        f"{'✅' if status['llm_key_present'] else '❌ deterministic planner only'}"
    )
    st.write(f"neatlogs tracing: {'✅ connected' if traced else '❌ not connected'}")
    st.write(
        "Jobs API price configured: "
        + ("✅" if status["jobs_price_configured"] else "❌ live jobs disabled (fail closed)")
    )
    live_gov = CreditGovernor(repo, settings, pool="live").global_summary()
    st.subheader("Live Crustdata budget")
    st.caption("Estimated figures unless marked actual. 1,000-credit global reserve is never spent.")
    st.metric("Spendable remaining (est.)", f"{live_gov['remaining']:.2f}", help=f"of {live_gov['spendable']}")
    st.write(
        f"Estimated used: {live_gov['estimated_used']:.2f} · Confirmed actual: {live_gov['actual_used']:.2f} · "
        f"Unknown-outcome calls: {live_gov['unknown_count']}"
    )

    st.subheader("Case history")
    cases = repo.list_cases()
    labels = {c["case_id"]: f"{c['target']} · {c['mode']} · {c['stage']} · {c['case_id'][-6:]}" for c in cases}
    selected = st.selectbox(
        "Open case", options=[None, *labels.keys()], format_func=lambda k: "—" if k is None else labels[k]
    )
    if selected:
        st.session_state["case_id"] = selected

# ---------------------------------------------------------------- new case
tab_new, tab_case = st.tabs(["New case", "Case workspace"])

with tab_new:
    mode_label = st.radio(
        "Mode", ["SYNTHETIC FIXTURE", "LIVE CRUSTDATA"], horizontal=True, help="Live mode never falls back to fixtures."
    )
    mode = RunMode.LIVE if mode_label.startswith("LIVE") else RunMode.SYNTHETIC
    scenario = None
    faults = None
    if mode == RunMode.SYNTHETIC:
        st.warning(SYNTHETIC_BANNER)
        scenario_name = st.selectbox("Fixture scenario", list(SCENARIOS))
        scenario = SCENARIOS[scenario_name]
        inject = st.selectbox(
            "Failure injection (recovery demo)",
            [
                "none",
                "503 twice on first company enrichment (retry → success)",
                "503 three times on first enrichment (retry exhausted → resume)",
                "401 on first enrichment (no retry)",
            ],
        )
        faults = {
            "none": None,
            "503 twice on first company enrichment (retry → success)": {"enrich_company": [503, 503]},
            "503 three times on first enrichment (retry exhausted → resume)": {"enrich_company": [503, 503, 503]},
            "401 on first enrichment (no retry)": {"enrich_company": [401]},
        }[inject]
        defaults = json.loads(scenario.read_text(encoding="utf-8")).get("case", {})
    else:
        st.info("LIVE CRUSTDATA — calls are metered against your Crustdata credits.")
        defaults = {}
    with st.form("case_form"):
        target = st.text_input("Target domain", defaults.get("target_domain", ""))
        peers = st.text_area(
            "Competitor domains (2–5, one per line)", "\n".join(defaults.get("competitor_domains", []))
        )
        thesis = st.text_area("Deal thesis", defaults.get("deal_thesis", ""))
        c1, c2 = st.columns(2)
        lookback = c1.number_input("Lookback (months)", 3, 36, int(defaults.get("lookback_months", 12)))
        budget = c2.number_input(
            "Case credit cap",
            1.0,
            float(settings.crustdata_max_case_credits),
            float(min(100, settings.crustdata_max_case_credits)),
        )
        confirm = True
        if mode == RunMode.LIVE:
            confirm = st.checkbox("I confirm these company identities and accept the credit cap above.")
        submitted = st.form_submit_button("Create and run case", type="primary")
    if submitted:
        try:
            case_input = CaseInput(
                target_domain=target,
                competitor_domains=[p for p in peers.splitlines() if p.strip()],
                deal_thesis=thesis,
                lookback_months=int(lookback),
                max_case_credits=Decimal(str(budget)),
                mode=mode,
            )
        except Exception as exc:
            st.error(f"Invalid input: {exc}")
        else:
            if not confirm:
                st.error("Confirm identities and budget before a live run.")
            else:
                try:
                    orch = _orchestrator(mode, scenario, faults)
                except ConfigError as exc:
                    st.error(str(exc))
                else:
                    state = orch.create_case(case_input)
                    st.session_state["case_id"] = state.case_id
                    st.session_state["case_scenario"] = {state.case_id: str(scenario) if scenario else None}
                    with st.status("Investigating…", expanded=True) as s:
                        try:
                            result = orch.run(state.case_id)
                            s.update(label=f"Finished: {result.stage.value} ({result.finish_reason})", state="complete")
                        except Exception as exc:  # surfaced, and state is persisted as failed
                            s.update(label=f"Run failed: {type(exc).__name__}", state="error")
                            st.exception(exc)
                    st.success("Open the Case workspace tab to review.")

# ---------------------------------------------------------------- case view
with tab_case:
    case_id = st.session_state.get("case_id")
    state = repo.load_case(case_id) if case_id else None
    if state is None:
        st.info("Create or select a case.")
        st.stop()
    synthetic = state.mode == RunMode.SYNTHETIC
    if synthetic:
        st.error(f"⚠️ {SYNTHETIC_BANNER}")
    else:
        st.success("LIVE CRUSTDATA")
    events = repo.list_events(state.case_id)
    trace_ids = [e["payload"].get("trace_id") for e in events if e["type"] == "trace"]
    c = st.columns(5)
    c[0].metric("Stage", state.stage.value)
    c[1].metric("Planner turns", state.iteration_count)
    c[2].metric("Tool calls", state.tool_call_count)
    c[3].metric("Finish", state.finish_reason or "—")
    c[4].metric("Evidence", len(state.evidence_ids))
    if trace_ids:
        st.caption(f"neatlogs trace id(s): {', '.join(t for t in trace_ids if t)}")
    if state.current_question:
        st.write(f"**Current question:** {state.current_question}")

    pool = "synthetic" if synthetic else "live"
    gov = CreditGovernor(repo, settings, pool=pool).case_summary(state.case_id, state.credit_budget)
    st.subheader("Credits" + (" (simulated for fixture run)" if synthetic else ""))
    b = st.columns(5)
    b[0].metric("Case cap", f"{gov['budget']}")
    b[1].metric("Estimated used", f"{gov['estimated_used']:.2f}")
    b[2].metric("Confirmed actual", f"{gov['actual_used']:.2f}")
    b[3].metric("Reserved", f"{gov['reserved']:.2f}")
    b[4].metric("Unknown-outcome", f"{gov['unknown_count']}")
    st.progress(min(1.0, float((gov["budget"] - gov["remaining"]) / gov["budget"])) if gov["budget"] else 0.0)

    if state.stage.value in {"partial", "failed", "investigating", "baseline", "created"}:
        if st.button("Resume case", type="primary"):
            scen = (st.session_state.get("case_scenario") or {}).get(state.case_id)
            orch = _orchestrator(state.mode, Path(scen) if scen else None, None)
            with st.status("Resuming from latest checkpoint…") as s:
                result = orch.run(state.case_id, resume=True)
                s.update(label=f"Finished: {result.stage.value} ({result.finish_reason})", state="complete")
            st.rerun()

    sc = state.scorecard
    if sc:
        st.subheader("Signal scorecard")
        m = st.columns(3)
        m[0].metric(
            "Risk signal strength",
            "INSUFFICIENT EVIDENCE" if sc.risk_score is None else f"{sc.risk_score:.0f} ({sc.risk_band})",
            help="Heuristic, unvalidated bands",
        )
        m[1].metric("Evidence coverage", f"{sc.coverage_pct:.0f}% · {sc.coverage_label}")
        m[2].metric("Evidence confidence", f"{sc.evidence_confidence:.0f}/100", help="Separate from risk")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Signal": f"{s.signal_id.value} {s.name}",
                        "Weight": s.weight,
                        "State": s.state.value,
                        "Score": "not scored" if s.score is None else round(s.score),
                        "Confidence": round(s.confidence),
                        "Reasons": ", ".join(s.reason_codes),
                    }
                    for s in sc.signals
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Investigation timeline")
    rows = []
    for e in events:
        p = e["payload"]
        if e["type"] == "plan":
            rows.append(
                {
                    "type": "🧭 plan",
                    "detail": f"#{p['iteration']} {p['action']} {p.get('arguments', {})}",
                    "why": p.get("why", ""),
                    "by": p.get("decided_by"),
                }
            )
        elif e["type"] == "tool_result":
            rows.append(
                {
                    "type": "🔧 tool",
                    "detail": f"{p['tool']} → {p['outcome']} (+{p['new_evidence']} evidence)",
                    "why": f"est {p.get('estimate')} / actual {p.get('actual')}",
                    "by": p.get("decided_by"),
                }
            )
        elif e["type"] == "retry":
            rows.append(
                {
                    "type": "🔁 retry",
                    "detail": f"{p.get('tool')} attempt {p['attempt']}: {p['reason']}",
                    "why": f"backoff {p['delay_s']}s",
                    "by": "policy",
                }
            )
        elif e["type"] == "score_change":
            rows.append(
                {
                    "type": "📈 scores",
                    "detail": "; ".join(f"{c['signal']} {c['from']}→{c['to']}" for c in p["changes"]),
                    "why": f"coverage {p['coverage_pct']:.0f}%",
                    "by": "deterministic",
                }
            )
        elif e["type"] in {"stage", "resume", "budget_filter", "llm_unavailable"}:
            rows.append({"type": f"• {e['type']}", "detail": json.dumps(p)[:200], "why": "", "by": "system"})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    evidence = repo.get_evidence(state.case_id)
    with st.expander(f"Evidence ({len(evidence)})"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": ev.evidence_id,
                        "kind": ev.kind.value,
                        "subject": ev.subject_domain,
                        "endpoint": ev.source_endpoint,
                        "retrieved": ev.retrieved_at.isoformat(timespec="minutes"),
                        "synthetic": ev.synthetic,
                        "data": json.dumps(ev.payload.model_dump(exclude_none=True))[:220],
                    }
                    for ev in evidence
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    report = repo.latest_report(state.case_id)
    if report:
        st.subheader("Verified memo")
        st.markdown(report["markdown"])
        d1, d2 = st.columns(2)
        d1.download_button("Download memo (.md)", report["markdown"], file_name=f"dealscope-{state.case_id}.md")
        d2.download_button(
            "Download evidence bundle (.json)",
            json.dumps(report["bundle"], indent=2, default=str),
            file_name=f"dealscope-{state.case_id}.json",
        )
