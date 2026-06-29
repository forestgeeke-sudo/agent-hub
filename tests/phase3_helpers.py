from __future__ import annotations

import json
import subprocess
from pathlib import Path


def write_root(root: Path, *, mode: str = "supervised", risk_tier: int = 1) -> None:
    for path in [
        root / "project",
        root / "config",
        root / "approvals",
        root / "runs" / "AGENT_RUNS",
        root / "runs" / "VALIDATION_RESULTS",
        root / "workspace" / "example",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    (root / "project" / "STATUS.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-06-29T00:00:00Z",
                "mode": mode,
                "active_task_id": None,
                "last_cycle": None,
                "blockers": [],
                "workers": {},
                "stop_requested": False,
            },
            indent=2,
        )
        + "\n"
    )
    (root / "project" / "BACKLOG.yaml").write_text(
        f"""schema_version: 1
tasks:
- id: T-1000
  title: Phase 3 task
  description: Do the Phase 3 task without credentials or tokens.
  type: docs
  risk_tier: {risk_tier}
  priority: 1
  target_folder: workspace/example
  suggested_worker: mock_worker
  depends_on: []
  status: ready
  created_at: '2026-06-29T00:00:00Z'
"""
    )
    (root / "project" / "LIMITS.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workers": {
                    "mock_worker": {"status": "available", "avoid_until": None},
                    "alt_worker": {"status": "available", "avoid_until": None},
                    "codex": {"status": "available", "avoid_until": None},
                    "claude": {"status": "available", "avoid_until": None},
                },
            },
            indent=2,
        )
        + "\n"
    )
    (root / "project" / "CONTEXT_STATE.json").write_text(
        '{"schema_version":1,"sessions":{},"thresholds":{"max_turns":25,"max_input_bytes":400000,"stale_minutes":120}}\n'
    )
    (root / "project" / "DECISION_LOG.md").write_text("# Decision Log\n")
    (root / "project" / "DAILY_REPORT.md").write_text("# Daily Report\n")
    (root / "project" / "HANDOFF.md").write_text("")
    (root / "config" / "SAFETY_RULES.yaml").write_text(
        f"""schema_version: 1
mode: {mode}
approved_folders: [workspace, project, runs, approvals]
auto_execute_max_tier: 1
approval_required_tiers: [2, 3, 4]
stop_file: STOP
"""
    )
    (root / "config" / "ROUTING_RULES.yaml").write_text(
        """schema_version: 1
defaults:
  planner: mock_planner
  max_retries: 2
by_task_type:
  docs: { primary: mock_worker, fallbacks: [alt_worker, codex] }
  planning: { primary: mock_worker, fallbacks: [] }
worker_selection:
  prefer_available: true
  avoid_limited: true
  on_all_unavailable: safe_stop
"""
    )
    (root / "config" / "workers.yaml").write_text(
        """schema_version: 1
workers:
  mock_worker:
    auth_method: none
    capabilities: [code_edit, docs, planning, routing]
    status: available
    command_template: null
  alt_worker:
    auth_method: none
    capabilities: [code_edit, docs, planning, routing]
    status: available
    command_template: null
  codex:
    auth_method: oauth
    capabilities: [code_edit, docs, refactor]
    status: available
    command_template: "codex {task}"
  claude:
    auth_method: oauth
    capabilities: [code_edit, docs, refactor]
    status: available
    command_template: "claude {task}"
"""
    )
    (root / "approvals" / "APPROVAL_QUEUE.yaml").write_text("schema_version: 1\npending: []\n")
    (root / "approvals" / "APPROVAL_DECISIONS.yaml").write_text("schema_version: 1\ndecisions: []\n")
    (root / "workspace" / "example" / "utils.py").write_text("def format_date(d):\n    return str(d)\n")
    subprocess.run(["git", "init"], cwd=root / "workspace", check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@agent-hub.local"], cwd=root / "workspace", check=True)
    subprocess.run(["git", "config", "user.name", "agent-hub dev"], cwd=root / "workspace", check=True)
    subprocess.run(["git", "add", "-A"], cwd=root / "workspace", check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=root / "workspace", check=True, capture_output=True)

