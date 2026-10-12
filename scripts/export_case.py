"""Export a finished case to fixtures/featured/<case_id>.json so it ships with the repo (see persistence/featured.py).

python scripts/export_case.py case-0e61a0b82462 --label "..." --description "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dealscope.config import Settings  # noqa: E402
from dealscope.persistence.featured import FEATURED_DIR, export_case  # noqa: E402
from dealscope.persistence.repository import Repository  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("--label", required=True)
    ap.add_argument("--description", required=True)
    args = ap.parse_args()
    repo = Repository(Settings().dealscope_db_path)
    doc = export_case(repo, args.case_id, args.label, args.description)
    FEATURED_DIR.mkdir(parents=True, exist_ok=True)
    out = FEATURED_DIR / f"{args.case_id}.json"
    out.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(doc['evidence'])} evidence records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
