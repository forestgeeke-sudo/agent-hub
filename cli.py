#!/usr/bin/env python3
"""CLI entrypoint for agent-hub."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from orchestrator.graph import run_one_cycle
from orchestrator.io.state_files import hub_root, load_backlog, load_status


def cmd_run(args: argparse.Namespace) -> int:
    root = hub_root(Path(args.root) if args.root else None)
    print(f"Running one cycle from {root}")
    result = run_one_cycle(str(root))
    print(f"Outcome: {result.get('outcome', 'unknown')}")
    for msg in result.get("messages", []):
        print(f"  {msg}")
    if result.get("log_refs"):
        print("Log refs:")
        for ref in result["log_refs"]:
            print(f"  {ref}")
    return 0 if result.get("outcome") in ("success", "approval_queued", "no_task", None) else 1


def cmd_status(args: argparse.Namespace) -> int:
    root = hub_root(Path(args.root) if args.root else None)
    status = load_status(root)
    print(f"Hub status ({root})")
    print(f"  Mode:          {status.mode}")
    print(f"  Updated:       {status.updated_at}")
    print(f"  Active task:   {status.active_task_id or 'none'}")
    if status.last_cycle:
        lc = status.last_cycle
        print(f"  Last cycle:    {lc.id} — {lc.outcome} at {lc.ended_at}")
    else:
        print("  Last cycle:    none")
    print(f"  Stop requested:{status.stop_requested}")
    print("  Workers:")
    for name, avail in status.workers.items():
        print(f"    {name}: {avail}")
    if status.blockers:
        print("  Blockers:")
        for b in status.blockers:
            print(f"    - {b}")
    return 0


def cmd_backlog(args: argparse.Namespace) -> int:
    root = hub_root(Path(args.root) if args.root else None)
    backlog = load_backlog(root)
    print(f"Backlog ({len(backlog.tasks)} tasks)")
    for t in backlog.tasks:
        print(
            f"  [{t.status:12}] {t.id} P{t.priority} "
            f"tier={t.risk_tier} {t.type:10} — {t.title}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="agent-hub orchestrator CLI")
    parser.add_argument("--root", help="Hub root directory", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run one orchestration cycle")
    run_p.set_defaults(func=cmd_run)

    status_p = sub.add_parser("status", help="Show hub status")
    status_p.set_defaults(func=cmd_status)

    backlog_p = sub.add_parser("backlog", help="List backlog tasks")
    backlog_p.set_defaults(func=cmd_backlog)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
