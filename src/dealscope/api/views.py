"""Translate internal case state into plain-language view models for the web UI.

Contract: frontend/src/api/types.ts. Internal codes (reason codes, stage enums, outcome codes) are converted to
sentences a deal-team reader can act on; raw codes are only passed through in `technical` fields.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from dealscope.analysis.signals import _in_window, _parse_date, _subtract_months, resolve_as_of
from dealscope.domain.enums import CaseStage, ClaimType, EvidenceKind, RunMode, SignalState, VerificationStatus
from dealscope.domain.models import (
    CaseState,
    CompanyProfilePayload,
    EvidenceRecord,
    JobPostingPayload,
    PersonHistoryPayload,
    Scorecard,
    SignalResult,
)
from dealscope.verification.claims import REJECTION_DESCRIPTIONS

# ---------------------------------------------------------------------------
# Plain-language dictionaries
# ---------------------------------------------------------------------------

SIGNAL_TEXT: dict[str, dict[str, str]] = {
    "S1": {
        "name": "Engineering team vs. company growth",
        "question": "Is the engineering team growing more slowly than the company, or shrinking?",
        "why": "If the thesis depends on product or platform delivery, a technical team that lags the rest of the "
        "company can signal execution risk.",
    },
    "S2": {
        "name": "Senior technical departures",
        "question": "Have senior technical leaders or senior engineers left the company recently?",
        "why": "Losing several key technical people in a short period can put roadmap continuity at risk.",
    },
    "S3": {
        "name": "Coverage of critical capabilities",
        "question": "Are the capabilities the thesis needs (platform, security, data/AI, reliability) visibly staffed?",
        "why": "A thesis-critical capability that depends on very few people, or has only open roles, is a gap to "
        "validate with management.",
    },
    "S4": {
        "name": "Pressure to hire critical roles",
        "question": "Is the company trying to fill many critical technical roles, or reposting the same ones?",
        "why": "Clusters of open or reposted critical roles can indicate difficulty rebuilding key capabilities.",
    },
    "S5": {
        "name": "Talent moving to competitors",
        "question": "Have former technical leaders joined the competitors you listed?",
        "why": "Mostly corroborating evidence: movement to direct competitors matters more when it coincides with "
        "other signals. It is not evidence of wrongdoing.",
    },
}

# (code prefix, sentence). "{x}" is replaced by the humanized code suffix (a count, period or capability).
CODE_TEXT: list[tuple[str, str]] = [
    ("NO_COMPANY_DATA", "No company profile was available for the target, so this could not be assessed."),
    ("NO_DEPARTMENT_DATA", "The data source did not return engineering headcount history for the target."),
    ("NO_SHARED_PERIOD", "Engineering and total headcount growth were not reported for the same period."),
    ("SINGLE_PERIOD", "Only one comparable time period was available, so no trend is inferred."),
    ("TECH_STABLE_OR_STRONG_", "Engineering growth kept pace with the company ({x})."),
    ("NO_DIVERGENCE_OBSERVED_", "No gap between engineering and total growth was observed ({x})."),
    ("MODEST_DIVERGENCE_", "Engineering grew somewhat more slowly than the company ({x})."),
    ("TECH_TOTAL_GAP_MATERIAL_", "Engineering growth trailed total company growth by a material margin ({x})."),
    ("TECH_FLAT_OR_DECLINING_TOTAL_GROWING_", "Engineering was flat or shrinking while the company grew ({x})."),
    ("TECH_CONTRACTION_TOTAL_STABLE_", "Engineering shrank while total headcount was stable ({x})."),
    ("CONTRACTION_CONSISTENT_WITH_TOTAL_", "Engineering shrank, but in line with the whole company ({x})."),
    ("MULTI_PERIOD_TECH_CONTRACTION", "Engineering contracted in more than one reported period."),
    ("DIVERGENCE_IN_MULTIPLE_PERIODS", "The engineering gap appears in more than one reported period."),
    ("BELOW_PEER_MEDIAN_MATERIAL_", "Engineering growth was well below the peer median ({x})."),
    ("PEER_BENCHMARK_WEAK", "Fewer than three comparable peers, so the peer comparison is weak."),
    ("NO_PEER_BENCHMARK", "No comparable peer data was available."),
    ("CORROBORATED_BY_", "Supported by an independent signal ({x})."),
    ("NO_PERSON_DATA", "No people-history records were collected for the target."),
    ("NO_EMPLOYMENT_DATA", "Returned profiles did not include usable employment history."),
    ("NO_DATED_EMPLOYMENT", "Returned profiles did not include employment dates."),
    ("NO_CRITICAL_ROLE_PROFILES", "No profiles in critical technical roles were found."),
    ("DEPARTURES_IN_WINDOW_", "Senior technical people seen leaving within the lookback window: {x}."),
    ("CRITICAL_DEPARTURES_IN_WINDOW", "Departures include critical leadership roles."),
    ("CONCENTRATED_DEPARTURES", "Departures are concentrated in a short period."),
    (
        "HIGH_SHARE_OF_OBSERVED_PROFILES",
        "Departures are a high share of the profiles observed (a sample, not a census).",
    ),
    ("NO_DEPARTURES_OBSERVED", "No departures were observed in the lookback window among returned profiles."),
    ("MISSING_END_DATE_NOT_COUNTED", "Profiles without an end date were not counted as departures."),
    ("UNPARSEABLE_END_DATE_NOT_COUNTED", "Profiles with unreadable end dates were not counted."),
    ("DUPLICATE_PROFILES_MERGED", "Duplicate profiles were merged before counting."),
    ("CONFLICTING_RECORDS_EXCLUDED", "Contradictory records were excluded."),
    ("LOW_PROFILE_COVERAGE", "Few profiles were available, so this is a low-coverage reading."),
    ("ALL_CAPABILITIES_NO_DATA", "No staffing evidence was found for any thesis-critical capability."),
    ("SOME_CAPABILITIES_NO_DATA", "Some thesis-critical capabilities had no evidence either way."),
    ("LOW_CAPABILITY_COVERAGE", "Visible coverage of critical capabilities is thin."),
    ("SINGLE_OBSERVED_LEADER_", "Only one current leader was observed for {x}."),
    ("GAP_WITH_OPEN_ROLES_AND_DEPARTURES_", "Open roles plus departures with no observed current leader for {x}."),
    ("CONFLICTING_CAPABILITY_RECORDS", "Some capability records conflict with each other."),
    ("NO_CRITICAL_CAPABILITIES_SPECIFIED", "No critical capabilities were specified for this thesis."),
    (
        "NO_JOB_DATA",
        "No job postings were collected, so hiring pressure was not assessed (this is not proof of no hiring).",
    ),
    ("NO_CRITICAL_OPENINGS_OBSERVED", "No open critical technical roles were observed."),
    ("FEW_CRITICAL_OPENINGS", "Only a few critical technical roles are open."),
    ("MULTIPLE_CRITICAL_OPENINGS", "Several critical technical roles are open."),
    ("REPOSTED_OR_PERSISTENT_CRITICAL_ROLE", "At least one critical role has been reposted or open for a long time."),
    ("UNUSUAL_CONCENTRATION_OR_PERSISTENCE", "Open critical roles are unusually concentrated or persistent."),
    ("BROAD_CAPABILITY_REBUILD_PRESSURE", "Openings suggest broad rebuilding of critical capabilities."),
    ("NO_HEADCOUNT_DENOMINATOR", "Openings could not be compared with company size."),
    ("DUPLICATE_POSTINGS_REMOVED", "Duplicate postings were removed before counting."),
    ("CRITICAL_VACANCIES", "Critical vacancies support this reading."),
    ("ENGINEERING_CONTRACTION_SIGNAL", "Engineering contraction supports this reading."),
    ("CONTINUITY_RISK_SIGNAL", "Senior departures support this reading."),
    ("COMPETITOR_MOVES_IN_WINDOW_", "Former technical leaders who joined a listed competitor within the window: {x}."),
    ("NO_COMPETITOR_MOVES_OBSERVED", "No moves to the listed competitors were observed."),
    ("EARLIER_MOVES_OUTSIDE_WINDOW_NOT_COUNTED", "Moves before the lookback window were not counted."),
    ("UNCONFIRMED_MOVE_TIMING_NOT_COUNTED", "Moves without confirmed timing were not counted."),
]

ROLE_GROUP_TEXT = {
    "technical_leadership": "Technical leadership",
    "senior_technical_ic": "Senior engineer",
    "security": "Security",
    "data_ml": "Data / AI",
    "other_technical": "Other technical",
    "non_technical": "Non-technical",
}
CAPABILITY_TEXT = {
    "platform_engineering": "Platform engineering",
    "security": "Security",
    "data_ml": "Data / AI",
    "reliability": "Reliability",
    "general_engineering": "General engineering",
    "other": "Other",
}
OUTCOME_TEXT = {
    "RETRY_EXHAUSTED": "the data provider kept failing after 2 retries",
    "AUTH": "the provider rejected the credentials",
    "PERMISSION": "the account is not allowed to use this data",
    "INSUFFICIENT_CREDITS": "the provider account is out of credits",
    "BAD_REQUEST": "the provider rejected the request",
    "SCHEMA": "the provider returned data in an unexpected format",
    "UNKNOWN_OUTCOME": "the connection dropped and the charge is unknown",
    "PER_CASE_BUDGET_EXCEEDED": "it would exceed this case's credit cap",
    "GLOBAL_SPENDABLE_BUDGET_EXCEEDED": "it would dip into the protected credit reserve",
    "UNKNOWN_PRICE_FAIL_CLOSED": "its price is not confirmed, so it was blocked",
    "UNKNOWN_OUTCOME_NOT_REPLAYED": "an identical earlier call has an unknown charge, so it was not repeated",
}
EXPLAINER = (
    "Risk, coverage and confidence are separate. Risk (0-100) is how strongly the observed signals point to "
    "organizational execution risk - a prompt for diligence questions, not a probability of failure. Coverage is how "
    "much of the signal set had enough data to be assessed; below 60% no overall score is given. Confidence rates "
    "the quality of the evidence behind the scores. Missing data lowers coverage and confidence, never risk."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _f(v: Any) -> float:
    return float(v) if isinstance(v, int | float | Decimal) else float(str(v)) if v not in (None, "") else 0.0


def _humanize(suffix: str) -> str:
    s = suffix.strip("_")
    m = re.fullmatch(r"(\d+)M", s)
    if m:
        return f"{m.group(1)}-month period"
    if s.isdigit():
        return s
    return CAPABILITY_TEXT.get(s.lower(), s.replace("_", " ").lower())


def code_sentence(code: str) -> str | None:
    for prefix, template in CODE_TEXT:
        if code == prefix or (prefix.endswith("_") and code.startswith(prefix)):
            return template.replace("{x}", _humanize(code[len(prefix) :])) if "{x}" in template else template
    return None


def band_for(score: float | None) -> tuple[str | None, str]:
    if score is None:
        return None, "neutral"
    if score < 25:
        return "Low signal", "good"
    if score < 50:
        return "Watch", "caution"
    if score < 70:
        return "Elevated", "bad"
    return "High signal", "bad"


def _signal_band(score: float | None) -> tuple[str | None, str]:
    if score is None:
        return None, "neutral"
    for limit, label, tone in (
        (20, "Low", "good"),
        (40, "Modest", "caution"),
        (60, "Elevated", "bad"),
        (80, "High", "bad"),
    ):
        if score <= limit:
            return label, tone
    return "Severe", "bad"


def _confidence_label(c: float) -> str:
    return "High" if c >= 75 else "Medium" if c >= 50 else "Low"


def _evidence_label(ev: EvidenceRecord) -> str:
    p = ev.payload
    if isinstance(p, CompanyProfilePayload):
        return f"Company profile - {p.name or ev.subject_domain} ({ev.subject_domain})"
    if isinstance(p, JobPostingPayload):
        return f"Job posting - {p.title}"
    if isinstance(p, PersonHistoryPayload):
        role = ROLE_GROUP_TEXT.get(p.role_group, p.role_group)
        title = f", {p.title_at_target}" if p.title_at_target else ""
        return f"Profile {p.person_ref[-6:]} - {role}{title}"
    return ev.kind.value


def _evidence_date(ev: EvidenceRecord) -> str | None:
    p = ev.payload
    if isinstance(p, JobPostingPayload):
        return (p.date_added or "")[:10] or None
    if isinstance(p, PersonHistoryPayload):
        return p.target_end or p.target_start
    return ev.retrieved_at.date().isoformat()


def _source(ev: EvidenceRecord) -> str:
    return "Synthetic fixture" if ev.synthetic else f"Crustdata {ev.source_endpoint}"


def evidence_ref(ev: EvidenceRecord) -> dict:
    return {"id": ev.evidence_id, "label": _evidence_label(ev), "date": _evidence_date(ev), "source": _source(ev)}


def _plain_flag(flag: str) -> str:
    m = re.match(r"(total|engineering)_growth_pct\.(\w+)=([-\d.]+)% dropped", flag)
    if not m:
        return flag
    what = "Total headcount" if m.group(1) == "total" else "Engineering headcount"
    return (
        f"{what} growth over {m.group(2)} was reported as {m.group(3)}% and ignored as implausible "
        "(likely a gap in the provider's data)."
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def status_of(state: CaseState, running: bool) -> tuple[str, str, str, bool]:
    reason = state.finish_reason or ""
    if running:
        return "Running", "info", "The agent is investigating. Results update as each step completes.", False
    failed_actions = re.search(r"_with_(\d+)_failed_actions", reason)
    if state.stage == CaseStage.COMPLETE:
        detail = {
            "no_candidates": "Finished: no remaining data source was likely to change the conclusion.",
            "planner_stop": "Finished: the AI planner judged further searches would not change the conclusion.",
            "complete": "Finished.",
        }.get(reason, "Finished.")
        return "Complete", "good", detail, False
    if state.stage == CaseStage.PARTIAL:
        if failed_actions:
            n = failed_actions.group(1)
            return (
                "Partial - can resume",
                "caution",
                f"{n} data request(s) failed after retries, so some evidence is missing. Resume to retry them "
                "without repeating completed calls.",
                True,
            )
        if reason.startswith("fatal:"):
            code = reason.split(":", 1)[1]
            return (
                "Stopped",
                "bad",
                f"Stopped because {OUTCOME_TEXT.get(code, code.lower())}. No fallback to demo data was used.",
                True,
            )
        limits = {
            "max_tool_calls": "the 12 data-request limit",
            "max_iterations": "the 8 planning-step limit",
            "max_runtime": "the time limit",
        }
        return (
            "Partial",
            "caution",
            f"Stopped at {limits.get(reason, reason)}; the memo covers what was collected.",
            True,
        )
    if state.stage == CaseStage.FAILED:
        return "Failed", "bad", f"The run failed ({reason}). Saved progress is kept; you can resume.", True
    return "Not started", "neutral", "Waiting to start.", True


# ---------------------------------------------------------------------------
# Steps (timeline)
# ---------------------------------------------------------------------------


def _action_title(action: str, args: dict, target: str, planned: bool = False) -> str:
    if action == "enrich_company":
        return f"{'Pull' if planned else 'Pulled'} the company profile for {args.get('domain')}"
    if action == "search_people":
        who = ROLE_GROUP_TEXT.get(str(args.get("role_group")), "technical people").lower()
        rel = "former" if args.get("relationship") == "past_target_employment" else "current"
        extra = f" now at {args['competitor_domain']}" if args.get("competitor_domain") else ""
        return f"{'Search' if planned else 'Searched'} for {rel} {who} at {target}{extra}"
    if action == "search_jobs":
        return f"{'Check' if planned else 'Checked'} open technical roles at {args.get('domain')}"
    if action == "stop":
        return "Decided to stop investigating"
    return action.replace("_", " ")


def _actor(decided_by: str | None) -> str:
    return {"llm": "AI planner", "deterministic_fallback": "Rule-based planner", "baseline": "Baseline"}.get(
        decided_by or "", "System"
    )


def _credits_text(p: dict, synthetic: bool) -> str | None:
    outcome = str(p.get("outcome", ""))
    sim = " (simulated)" if synthetic else ""
    if outcome == "cached":
        return "Reused cached result, 0 credits"
    if p.get("actual") not in (None, "None"):
        return f"{_f(p['actual']):g} credits (confirmed){sim}"
    if p.get("estimate") not in (None, "None"):
        return f"about {_f(p['estimate']):g} credits (estimated){sim}"
    return None


def build_steps(state: CaseState, events: list[dict]) -> list[dict]:
    steps: list[dict] = []
    target = state.input.target_domain
    synthetic = state.mode == RunMode.SYNTHETIC

    def add(at: str, kind: str, title: str, detail: str, actor: str, tone: str, credits: str | None = None) -> None:
        steps.append(
            {
                "n": len(steps) + 1,
                "at": at,
                "kind": kind,
                "title": title,
                "detail": detail,
                "actor": actor,
                "tone": tone,
                "credits": credits,
            }
        )

    for e in events:
        p, at, t = e["payload"], e["created_at"], e["type"]
        if t == "case_created":
            add(
                at,
                "stage",
                "Investigation created",
                f"Target {target} against {len(state.input.competitor_domains)} competitors; "
                f"credit cap {p.get('budget')}.",
                "System",
                "info",
            )
        elif t == "plan":
            action = p.get("action", "")
            rejected = p.get("rejected") or []
            detail = p.get("why") or ""
            if p.get("question"):
                detail = f"{p['question']} {detail}".strip()
            tone = "info"
            if rejected:
                detail += (
                    f" (The AI planner was unavailable or returned an invalid choice {len(rejected)} time(s), "
                    "so the rule-based planner decided.)"
                )
                tone = "caution"
            title = (
                "Decided to stop investigating"
                if action == "stop"
                else f"Next step: {_action_title(action, p.get('arguments') or {}, target, planned=True).lower()}"
            )
            add(at, "plan", title, detail, _actor(p.get("decided_by")), tone)
        elif t == "tool_result":
            args = p.get("arguments") or {}
            outcome = str(p.get("outcome", ""))
            n = int(p.get("new_evidence") or 0)
            title = _action_title(str(p.get("tool")), args, target)
            if outcome in ("succeeded", "cached"):
                if p.get("tool") == "enrich_company":
                    detail = (
                        "Headcount, growth and hiring data recorded."
                        if n or outcome == "cached"
                        else "No matching company record was returned."
                    )
                elif p.get("tool") == "search_jobs":
                    detail = f"Found {n} relevant posting(s)."
                else:
                    detail = f"Found {n} relevant profile(s)."
                if outcome == "cached":
                    detail += " Reused a result already fetched today."
                tone = "good" if n or outcome == "cached" else "neutral"
                kind = "tool"
            else:
                status, _, code = outcome.partition(":")
                reason = OUTCOME_TEXT.get(code.split(":")[0].strip(), code.lower())
                if status == "blocked":
                    detail, tone, kind = f"Not sent because {reason}.", "caution", "blocked"
                else:
                    detail, tone, kind = f"Failed because {reason}.", "bad", "tool"
            add(at, kind, title, detail, _actor(p.get("decided_by")), tone, _credits_text(p, synthetic))
        elif t == "retry":
            add(
                at,
                "retry",
                f"Retrying a failed data request ({p.get('tool')})",
                f"Attempt {p.get('attempt')} failed ({p.get('reason')}); waiting {p.get('delay_s')} s before retrying.",
                "Retry policy",
                "caution",
            )
        elif t == "score_change":
            changes = p.get("changes") or []
            scored = [c["signal"] for c in changes if str(c.get("to", "")).startswith(("scorable", "low_coverage"))]
            detail = (
                f"Updated signals: {', '.join(SIGNAL_TEXT[s]['name'] for s in scored if s in SIGNAL_TEXT)}. "
                if scored
                else "Signals re-evaluated. "
            )
            add(
                at,
                "score",
                "Re-scored the risk signals",
                detail + f"Evidence coverage is now {_f(p.get('coverage_pct')):.0f}%.",
                "System",
                "info",
            )
        elif t == "resume":
            add(
                at,
                "resume",
                "Resumed from the last saved checkpoint",
                f"Restored {p.get('evidence_restored')} evidence records; retrying {p.get('retrying')} failed step(s). "
                "Completed requests are not repeated.",
                "System",
                "info",
            )
        elif t == "llm_unavailable":
            add(
                at,
                "note",
                "AI write-up unavailable",
                "The AI model could not draft findings (quota or service error); only rule-based, verified findings "
                "are shown.",
                "System",
                "caution",
            )
        elif t == "budget_filter":
            add(
                at,
                "note",
                "Skipped options that would exceed the credit cap",
                f"Remaining case budget: {p.get('remaining')} credits.",
                "Credit governor",
                "caution",
            )
        elif t == "stage" and p.get("to") in ("complete", "partial", "failed"):
            label = {
                "complete": "Investigation complete",
                "partial": "Investigation ended early",
                "failed": "Investigation failed",
            }[p["to"]]
            add(
                at,
                "stage",
                label,
                "Memo generated from verified findings." if p["to"] != "failed" else "",
                "System",
                {"complete": "good", "partial": "caution", "failed": "bad"}[p["to"]],
            )
    return steps


# ---------------------------------------------------------------------------
# Signals / assessment
# ---------------------------------------------------------------------------


def signal_view(s: SignalResult) -> dict:
    text = SIGNAL_TEXT.get(s.signal_id.value, {"name": s.name, "question": "", "why": ""})
    scored = s.score is not None and s.state != SignalState.NOT_SCORED
    band, tone = _signal_band(s.score if scored else None)
    sentences = [x for x in (code_sentence(c) for c in s.reason_codes) if x]
    status = {
        SignalState.SCORABLE: "Scored",
        SignalState.LOW_COVERAGE: "Partly scored (thin data)",
        SignalState.CONFLICTING: "Conflicting data",
        SignalState.NOT_SCORED: "Not scored",
    }[s.state]
    return {
        "id": s.signal_id.value,
        "name": text["name"],
        "question": text["question"],
        "weight_pct": round(s.weight * 100),
        "scored": scored,
        "score": round(s.score) if scored else None,
        "band": band,
        "tone": tone,
        "status_label": status,
        "confidence": round(s.confidence),
        "finding": " ".join(dict.fromkeys(sentences)) or "No result recorded.",
        "why_it_matters": text["why"],
        "limitations": s.limitations,
        "evidence_ids": s.evidence_ids,
        "technical": {"reason_codes": s.reason_codes, "state": s.state.value},
    }


def assessment_view(sc: Scorecard) -> dict:
    band, tone = band_for(sc.risk_score)
    scored = [s for s in sc.signals if s.score is not None and s.state != SignalState.NOT_SCORED]
    if sc.risk_score is None:
        headline = (
            f"Not enough evidence for an overall score yet: {sc.coverage_pct:.0f}% of the signal weight could "
            "be assessed (60% needed). Individual signals below still show what was found."
        )
    else:
        top = max(scored, key=lambda s: s.score or 0)
        provisional = " (provisional)" if sc.coverage_label == "provisional" else ""
        headline = (
            f"{band}{provisional}: overall risk signal {sc.risk_score:.0f}/100 from {len(scored)} of 5 signals. "
            f"Strongest: {SIGNAL_TEXT[top.signal_id.value]['name'].lower()} ({top.score:.0f}/100)."
        )
    coverage_label = {
        "insufficient_evidence": "Not enough evidence",
        "provisional": "Provisional",
        "coverage_threshold_met": "Enough evidence to score",
    }[sc.coverage_label]
    return {
        "risk_score": round(sc.risk_score) if sc.risk_score is not None else None,
        "risk_band": band,
        "risk_tone": tone,
        "headline": headline,
        "coverage_pct": round(sc.coverage_pct, 1),
        "coverage_label": coverage_label,
        "confidence": round(sc.evidence_confidence),
        "confidence_label": _confidence_label(sc.evidence_confidence),
        "explainer": EXPLAINER,
    }


# ---------------------------------------------------------------------------
# Findings / evidence tables
# ---------------------------------------------------------------------------

_KIND = {
    ClaimType.OBSERVATION: "Fact",
    ClaimType.INTERPRETATION: "Interpretation",
    ClaimType.HYPOTHESIS: "Hypothesis",
    ClaimType.QUESTION: "Question",
}


def findings_and_questions(state: CaseState, by_id: dict[str, EvidenceRecord]) -> tuple[list[dict], list[str]]:
    findings, questions = [], []
    accepted = [
        c for c in state.claims if c.verification_status in (VerificationStatus.VERIFIED, VerificationStatus.QUALIFIED)
    ]
    order = {"high": 0, "medium": 1, "low": 2}
    for c in sorted(accepted, key=lambda c: order.get(c.severity.value, 3)):
        if c.claim_type == ClaimType.QUESTION:
            questions.append(c.text)
            continue
        findings.append(
            {
                "id": c.claim_id,
                "kind": _KIND[c.claim_type],
                "severity": c.severity.value,
                "text": c.text,
                "verification": "Verified"
                if c.verification_status == VerificationStatus.VERIFIED
                else "Verified with caveats",
                "caveats": [n for n in c.verification_notes if n],
                "evidence": [evidence_ref(by_id[i]) for i in c.evidence_ids if i in by_id],
                "counter_evidence": [evidence_ref(by_id[i]) for i in c.counter_evidence_ids if i in by_id],
                "alternatives": c.alternative_explanations,
                "limitations": c.limitations,
            }
        )
    for q in state.open_questions:
        if q not in questions:
            questions.append(q)
    return findings, questions


def tables(state: CaseState, evidence: list[EvidenceRecord]) -> tuple[list[dict], list[dict], list[dict]]:
    companies, people, jobs = [], [], []
    target = state.input.target_domain
    peers = set(state.input.competitor_domains)
    as_of = resolve_as_of(evidence) if evidence else datetime.now(UTC).date()
    start = _subtract_months(as_of, state.input.lookback_months)
    for ev in evidence:
        p = ev.payload
        if isinstance(p, CompanyProfilePayload):
            companies.append(
                {
                    "domain": ev.subject_domain,
                    "role": "Target" if ev.subject_domain == target else "Peer",
                    "name": p.name,
                    "headcount": p.total_headcount,
                    "total_growth": {k: round(v, 1) for k, v in p.total_growth_pct.items()},
                    "engineering_headcount": p.engineering_headcount,
                    "engineering_growth": {k: round(v, 1) for k, v in p.engineering_growth_pct.items()},
                    "open_jobs": p.job_openings_count,
                    "data_quality_flags": [_plain_flag(f) for f in p.data_quality_flags],
                    "evidence_id": ev.evidence_id,
                }
            )
        elif isinstance(p, PersonHistoryPayload):
            if p.currently_at_target:
                status = "Still at target"
            elif p.target_end and _in_window(_parse_date(p.target_end), start, as_of):
                status = "Left in lookback window"
            elif p.target_end:
                status = "Left earlier"
            else:
                status = "End date unknown"
            people.append(
                {
                    "ref": p.person_ref[-6:],
                    "role_group": ROLE_GROUP_TEXT.get(p.role_group, p.role_group),
                    "title_at_target": p.title_at_target,
                    "left_target": None if p.currently_at_target else p.target_end,
                    "status": status,
                    "now_at": p.current_employer_name or p.current_employer_domain,
                    "now_at_competitor": bool(p.current_employer_domain and p.current_employer_domain in peers),
                    "evidence_id": ev.evidence_id,
                }
            )
        elif isinstance(p, JobPostingPayload):
            jobs.append(
                {
                    "title": p.title,
                    "capability": CAPABILITY_TEXT.get(p.capability, p.capability),
                    "posted": (p.date_added or "")[:10] or None,
                    "reposted": p.reposted,
                    "openings": p.number_of_openings,
                    "url": p.url,
                    "evidence_id": ev.evidence_id,
                }
            )
    companies.sort(key=lambda r: (r["role"] != "Target", r["domain"]))
    rank = {"Left in lookback window": 0, "Left earlier": 1, "End date unknown": 2, "Still at target": 3}
    people.sort(key=lambda r: (rank[r["status"]], r["left_target"] or ""), reverse=False)
    jobs.sort(key=lambda r: r["posted"] or "", reverse=True)
    return companies, people, jobs


# ---------------------------------------------------------------------------
# Top-level builders
# ---------------------------------------------------------------------------


def credits_view(summary: dict, synthetic: bool) -> dict:
    return {
        "cap": _f(summary["budget"]),
        "estimated_used": _f(summary["estimated_used"]),
        "actual_used": _f(summary["actual_used"]),
        "reserved": _f(summary["reserved"]),
        "remaining": _f(summary["remaining"]),
        "unknown_calls": int(summary["unknown_count"]),
        "simulated": synthetic,
    }


def verification_view(report: dict | None) -> dict | None:
    if not report:
        return None
    bundle = report.get("bundle") or {}
    m = (bundle.get("verification") or {}).get("metrics") or {}
    reasons = [
        {"reason": REJECTION_DESCRIPTIONS.get(code, code.replace("_", " ").lower()), "count": n}
        for code, n in (m.get("rejection_reasons") or {}).items()
    ]
    return {
        "published": int(m.get("verified", 0)) + int(m.get("qualified", 0)),
        "verified": int(m.get("verified", 0)),
        "with_caveats": int(m.get("qualified", 0)),
        "rejected": int(m.get("rejected", 0)),
        "grounded_rate": m.get("grounded_claim_rate"),
        "rejected_reasons": reasons,
        "ai_draft_used": bool((bundle.get("run") or {}).get("narrative_available")),
    }


def case_view(
    state: CaseState,
    evidence: list[EvidenceRecord],
    events: list[dict],
    report: dict | None,
    credit_summary: dict,
    running: bool,
) -> dict:
    by_id = {e.evidence_id: e for e in evidence}
    label, tone, detail, can_resume = status_of(state, running)
    findings, questions = findings_and_questions(state, by_id)
    companies, people, jobs = tables(state, evidence)
    bundle = (report or {}).get("bundle") or {}
    return {
        "case_id": state.case_id,
        "mode": state.mode.value,
        "synthetic": state.mode == RunMode.SYNTHETIC,
        "target": state.input.target_domain,
        "peers": state.input.competitor_domains,
        "thesis": state.input.deal_thesis,
        "lookback_months": state.input.lookback_months,
        "running": running,
        "status_label": label,
        "status_tone": tone,
        "status_detail": detail,
        "can_resume": can_resume and not running,
        "current_question": state.current_question if running else None,
        "planner_turns": state.iteration_count,
        "tool_calls": state.tool_call_count,
        "assessment": assessment_view(state.scorecard) if state.scorecard else None,
        "signals": [signal_view(s) for s in state.scorecard.signals] if state.scorecard else [],
        "findings": findings,
        "questions": questions,
        "steps": build_steps(state, events),
        "companies": companies,
        "people": people,
        "jobs": jobs,
        "credits": credits_view(credit_summary, state.mode == RunMode.SYNTHETIC),
        "verification": verification_view(report),
        "trace_ids": [
            e["payload"]["trace_id"] for e in events if e["type"] == "trace" and e["payload"].get("trace_id")
        ],
        "llm_model": (bundle.get("run") or {}).get("llm_model"),
        "updated_at": state.updated_at.isoformat(),
        "report_available": report is not None,
    }


def case_list_item(state: CaseState, running: bool) -> dict:
    label, tone, _, _ = status_of(state, running)
    sc = state.scorecard
    if sc is None:
        risk = "Not scored yet"
    elif sc.risk_score is None:
        risk = "Not enough evidence"
    else:
        risk = f"{band_for(sc.risk_score)[0]} ({sc.risk_score:.0f}/100)"
    return {
        "case_id": state.case_id,
        "target": state.input.target_domain,
        "mode": state.mode.value,
        "status_label": label,
        "tone": tone,
        "risk_label": risk,
        "updated_at": state.updated_at.isoformat(),
    }


IDENTITY_TEXT = {
    "ok": "Matches exactly one company.",
    "ambiguous": "This domain matches several companies. Use the company's main domain to avoid paying for "
    "the wrong one.",
    "mismatch": "No company uses this as its main domain; several unrelated records reference it. Try the "
    "company's primary domain.",
    "no_match": "No company found for this domain.",
}


def identity_view(check: Any) -> dict:
    msg = IDENTITY_TEXT.get(check.status, check.status)
    if check.status == "mismatch" and check.match_count:
        msg = (
            f"{check.match_count} different records reference this domain, but none use it as their main domain. "
            "Pick the right company's primary domain below."
        )
    return {
        "domain": check.domain,
        "ok": check.ok,
        "status": check.status,
        "resolved_name": check.resolved_name,
        "match_count": check.match_count,
        "message": msg,
        "candidates": [
            {k: c.get(k) for k in ("name", "primary_domain", "employee_count_range")} for c in check.candidates
        ],
    }


__all__ = ["case_view", "case_list_item", "identity_view", "EvidenceKind"]
