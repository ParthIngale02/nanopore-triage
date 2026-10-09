"""Command line entry point.

    python -m nanopore_triage.cli seed            # build the Chroma index from history + SOPs
    python -m nanopore_triage.cli triage PAW31001 # print a markdown report
    python -m nanopore_triage.cli list            # run IDs available to triage
"""

from __future__ import annotations

import argparse
import json
import sys

from . import config


def seed(store=None) -> dict[str, int]:
    from .store import TriageStore

    store = store or TriageStore()
    runs = store.ingest_history_file(config.HISTORY_FILE) if config.HISTORY_FILE.exists() else 0
    sops = store.ingest_sops(config.SOP_DIR) if config.SOP_DIR.exists() else 0
    return {"runs_ingested": runs, "sops_ingested": sops, **store.counts()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nanopore-triage")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    sub.add_parser("list")
    t = sub.add_parser("triage")
    t.add_argument("run_id")
    t.add_argument("--json", action="store_true", help="emit the structured analysis instead of markdown")
    args = p.parse_args(argv)

    if args.cmd == "seed":
        print(json.dumps(seed(), indent=2))
    elif args.cmd == "list":
        from .qc_loader import list_runs
        print("\n".join(list_runs()))
    elif args.cmd == "triage":
        from .graph import triage
        state = triage(args.run_id)
        if args.json:
            print(json.dumps({"engine": state["engine"], "flags": [f.model_dump() for f in state["flags"]],
                              "analysis": state["analysis"].model_dump(), "warnings": state.get("warnings", [])}, indent=2))
        else:
            print(state["report_md"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
