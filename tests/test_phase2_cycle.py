"""Phase 2 Tier-2 cycle test with Codex subprocess mocked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from orchestrator.graph import run_one_cycle
from orchestrator.io.state_files import load_backlog, load_limits, load_status


FIXTURES = Path(__file__).parent / "fixtures" / "codex_stderr"


def _write_phase2_root(root: Path) -> None:
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
                "mode": "supervised",
                "active_task_id": None,
                "last_cycle": None,
                "blockers": [],
                "workers": {"codex": "available"},
                "stop_requested": False,
            },
            indent=2,
        )
        + "\n"
    )
    (root / "project" / "BACKLOG.yaml").write_text(
        """schema_version: 1
tasks:
- id: T-0002
  title: Add a docstring to utils.format_date
  description: Add a one-line docstring to utils.format_date; do not change behavior.
  type: docs
  risk_tier: 2
  priority: 1
  target_folder: workspace/example
  suggested_worker: codex
  depends_on: []
  status: ready
  created_at: '2026-06-29T00:00:00Z'
"""
    )
    (root / "project" / "LIMITS.json").write_text(
        """{
  "schema_version": 1,
  "workers": {
    "codex": {
      "auth_method": "oauth",
      "status": "available",
      "last_success": null,
      "last_failure": null,
      "failure_type": null,
      "retry_after": null,
      "retry_after_is_guess": true,
      "retry_confidence": "low",
      "daily_uses": 0,
      "avoid_until": null,
      "notes": null
    }
  }
}
"""
    )
    (root / "project" / "CONTEXT_STATE.json").write_text(
        '{"schema_version":1,"sessions":{},"thresholds":{"max_turns":25,"max_input_bytes":400000,"stale_minutes":120}}\n'
    )
    (root / "project" / "DECISION_LOG.md").write_text("# Decision Log\n")
    (root / "project" / "DAILY_REPORT.md").write_text("# Daily Report\n")
    (root / "config" / "SAFETY_RULES.yaml").write_text(
        """schema_version: 1
mode: supervised
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
  max_retries: 1
by_task_type:
  docs: { primary: codex, fallbacks: [claude] }
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
  codex:
    auth_method: oauth
    capabilities: [code_edit, docs, refactor]
    status: available
    command_template: "codex exec --sandbox workspace-write {task}"
  claude:
    auth_method: oauth
    capabilities: [code_edit, docs, refactor, planning]
    status: future
    command_template: "claude {task}"
"""
    )
    (root / "approvals" / "APPROVAL_QUEUE.yaml").write_text("schema_version: 1\npending: []\n")
    (root / "approvals" / "APPROVAL_DECISIONS.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "decisions": [
                    {
                        "request_id": "A-0001",
                        "decision": "approved",
                        "decided_by": "human",
                        "decided_at": "2026-06-29T00:00:00Z",
                        "approved_scope": {
                            "task_id": "T-0002",
                            "tier": 2,
                            "target_folder": "workspace/example",
                            "allowed_files": ["workspace/example/utils.py"],
                            "allowed_worker": "codex",
                            "expires_at": "2099-01-01T00:00:00Z",
                        },
                        "note": "test",
                    }
                ],
            },
            sort_keys=False,
        )
    )
    utils = root / "workspace" / "example" / "utils.py"
    utils.write_text("def format_date(d):\n    return str(d)\n")
    subprocess.run(["git", "init"], cwd=root / "workspace", check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@agent-hub.local"], cwd=root / "workspace", check=True)
    subprocess.run(["git", "config", "user.name", "agent-hub dev"], cwd=root / "workspace", check=True)
    subprocess.run(["git", "add", "-A"], cwd=root / "workspace", check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=root / "workspace", check=True, capture_output=True)


def test_full_tier2_cycle_with_mocked_codex_success(tmp_path, monkeypatch):
    root = tmp_path
    _write_phase2_root(root)

    def fake_run_command(self, command, workspace, log_path):
        log_path.write_text("[stderr] " + (FIXTURES / "normal_completion.txt").read_text())
        target = workspace / "example" / "utils.py"
        target.write_text('def format_date(d):\n    """Format a date value as a string."""\n    return str(d)\n')
        return "completed\n", (FIXTURES / "normal_completion.txt").read_text(), 0

    monkeypatch.setattr("orchestrator.workers.codex_worker.CodexWorker._run_command", fake_run_command)

    result = run_one_cycle(str(root))

    assert result["outcome"] == "success"
    assert list((root / "runs" / "AGENT_RUNS").glob("*_codex_T-0002"))
    assert "T-0002" in (root / "project" / "DAILY_REPORT.md").read_text()
    assert load_status(root).last_cycle.outcome == "success"
    assert load_backlog(root).tasks[0].status == "done"
    limits = load_limits(root)
    assert limits.workers["codex"].daily_uses == 1
