"""Featured (recorded) cases: finished live investigations bundled with the repo.

A featured case is exported from the local SQLite store to `fixtures/featured/<case_id>.json` and imported on server
start when missing. Live cases contain real professional records, so `fixtures/featured/` is gitignored: featured cases
are for local demos only and are never published (spec: no real profiles in Git). They let the demo open a real
live result instantly, without spending Crustdata credits or depending on LLM quotas.

Imported credit-ledger rows use pool "featured", so they appear in the case's own credit summary but never count
against this installation's live budget.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from dealscope.domain.models import CaseState, EvidenceRecord, FindingClaim
from dealscope.persistence.repository import Repository

FEATURED_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "featured"
FORMAT_VERSION = 1


def export_case(repo: Repository, case_id: str, label: str, description: str) -> dict[str, Any]:
    state = repo.load_case(case_id)
    if state is None:
        raise KeyError(case_id)
    report = repo.latest_report(case_id)
    if report is None:
        raise ValueError(f"{case_id} has no report; only finished cases can be featured")
    return {
        "format_version": FORMAT_VERSION,
        "label": label,
        "description": description,
        "recorded_at": state.updated_at.isoformat(),
        "state": json.loads(state.model_dump_json()),
        "evidence": [json.loads(e.model_dump_json()) for e in repo.get_evidence(case_id)],
        "events": [
            {"type": e["type"], "payload": e["payload"], "created_at": e["created_at"]}
            for e in repo.list_events(case_id)
        ],
        "ledger": [
            {
                "operation": r["operation"],
                "quantity": r["quantity"],
                "estimate": str(r["estimate"]),
                "actual": None if r["actual"] is None else str(r["actual"]),
                "status": r["status"],
            }
            for r in repo.ledger_rows(case_id)
        ],
        "report": {
            "markdown": report["markdown"],
            "bundle": report["bundle"],
            "claims": [
                json.loads(c.model_dump_json()) if hasattr(c, "model_dump_json") else c
                for c in report.get("claims", [])
            ],
        },
    }


def import_case(repo: Repository, doc: dict[str, Any]) -> str | None:
    """Insert a featured case if it is not already present. Returns the case id when imported."""
    if doc.get("format_version") != FORMAT_VERSION:
        raise ValueError("unsupported featured-case format")
    state = CaseState.model_validate(doc["state"])
    if repo.load_case(state.case_id) is not None:
        return None
    repo.create_case(state)
    repo.save_case(state)
    repo.add_evidence([EvidenceRecord.model_validate(e) for e in doc["evidence"]])
    for e in doc["events"]:
        repo.add_event(state.case_id, e["type"], e["payload"], created_at=e["created_at"])
    for r in doc["ledger"]:
        lid = repo.ledger_insert(
            state.case_id,
            r["operation"],
            int(r["quantity"]),
            Decimal(r["estimate"]),
            status=r["status"],
            pool="featured",
        )
        if r["actual"] is not None:
            repo.ledger_update(lid, r["status"], actual=Decimal(r["actual"]))
    rep = doc["report"]
    repo.save_report(
        state.case_id, rep["markdown"], rep["bundle"], [FindingClaim.model_validate(c) for c in rep["claims"]]
    )
    return state.case_id


def featured_docs(directory: Path = FEATURED_DIR) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def import_all(repo: Repository, directory: Path = FEATURED_DIR) -> list[str]:
    return [cid for doc in featured_docs(directory) if (cid := import_case(repo, doc))]
