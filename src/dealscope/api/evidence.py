"""Evidence summary for the Evidence page: Crustdata credit budget and the committed pricing probe.

Everything is read from committed evidence files and the local credit ledger; nothing here calls an external service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
    return {"crustdata": _crustdata(global_summary, settings)}
