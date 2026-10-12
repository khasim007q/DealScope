"""Export real flows for the Evidence page (no prompt text, no personal data).

python scripts/export_evidence_flows.py traces CASE_ID --label "..." --description "..." --name NAME [--order N]
    -> evidence/neatlogs/traces/NAME.json   (recorded spans of every run of the case; one file per run)
python scripts/export_evidence_flows.py entire-session
    -> evidence/entire/session.json          (session id, agent, checkpoint count, first/last time; no prompts)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dealscope.config import Settings  # noqa: E402
from dealscope.persistence.repository import Repository  # noqa: E402


def export_traces(args: argparse.Namespace) -> None:
    repo = Repository(Settings().dealscope_db_path)
    traces = repo.list_traces(args.case_id)
    if not traces:
        sys.exit(f"no recorded traces for {args.case_id}")
    out_dir = ROOT / "evidence" / "neatlogs" / "traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = args.label.split("|")
    descs = args.description.split("|")
    for i, t in enumerate(traces):
        name = args.name if len(traces) == 1 else f"{args.name}-run{i + 1}"
        doc = {
            "label": labels[min(i, len(labels) - 1)],
            "description": descs[min(i, len(descs) - 1)],
            "order": args.order + i,
            "case_id": args.case_id,
            "trace": t,
        }
        (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"wrote {name}.json: {t['span_count']} spans, {t['error_count']} errors, trace {t['trace_id']}")


def export_entire_session(_: argparse.Namespace) -> None:
    raw = subprocess.run(
        ["entire", "checkpoint", "list", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    items = json.loads(raw)
    sessions = {i.get("session_id") for i in items if i.get("session_id")}
    commits = [i for i in items if i.get("agent")]
    dates = sorted(i["date"] for i in items if i.get("date"))
    doc = {
        "session_id": next(iter(sessions)) if len(sessions) == 1 else ", ".join(sorted(sessions)),
        "agent": commits[0]["agent"] if commits else "Claude Code",
        "checkpoints_total": len(items),
        "first": dates[0] if dates else "",
        "last": dates[-1] if dates else "",
    }
    out = ROOT / "evidence" / "entire" / "session.json"
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"wrote {out}: {doc}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("traces")
    t.add_argument("case_id")
    t.add_argument("--label", required=True, help="use | to give one label per run")
    t.add_argument("--description", required=True, help="use | to give one description per run")
    t.add_argument("--name", required=True)
    t.add_argument("--order", type=int, default=10)
    t.set_defaults(func=export_traces)
    e = sub.add_parser("entire-session")
    e.set_defaults(func=export_entire_session)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
