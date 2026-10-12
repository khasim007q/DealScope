"""Basic structural validator for a DealScope report JSON export.

Expected format is intentionally simple. Extend with application-level entity/date checks.
Exits non-zero when a material claim lacks citations or references a missing evidence ID.
"""

import json
import sys
from pathlib import Path


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    evidence = data.get("evidence", [])
    valid_ids = {item.get("evidence_id") for item in evidence if item.get("evidence_id")}
    report = data.get("report", {})
    claims = report.get("claims", [])
    if not isinstance(claims, list):
        return ["report.claims must be a list"]
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claim[{index}] must be an object")
            continue
        text = str(claim.get("text", "")).strip()
        kind = claim.get("claim_type", "observation")
        cited = claim.get("evidence_ids", [])
        if not text:
            errors.append(f"claim[{index}] has empty text")
        if kind in {"observation", "interpretation"} and not cited:
            errors.append(f"claim[{index}] material claim has no evidence_ids")
        for evidence_id in cited:
            if evidence_id not in valid_ids:
                errors.append(f"claim[{index}] references unknown evidence_id={evidence_id}")
        if claim.get("verification_status") == "verified" and not cited:
            errors.append(f"claim[{index}] cannot be verified without evidence")
    mode = data.get("mode", "unknown")
    if mode not in {"live", "synthetic"}:
        errors.append("mode must be live or synthetic")
    if mode == "synthetic" and not report.get("synthetic_banner", False):
        errors.append("synthetic mode requires report.synthetic_banner=true")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/validate_report.py path/to/report.json", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not load JSON: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: report structure and citation IDs are valid (semantic support still requires app verifier).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
