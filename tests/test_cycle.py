"""End-to-end mock cycle tests."""

import json
import shutil
from pathlib import Path

import yaml

from orchestrator.graph import run_one_cycle
from orchestrator.io.state_files import hub_root, load_backlog, load_status


def _reset_tier1_task(root: Path) -> None:
    backlog_path = root / "project" / "BACKLOG.yaml"
    data = yaml.safe_load(backlog_path.read_text())
    for t in data["tasks"]:
        if t["id"] == "T-0001":
            t["status"] = "ready"
        if t["id"] == "T-0002":
            t["status"] = "ready"
    backlog_path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_tier1_full_mock_cycle():
    root = hub_root()
    _reset_tier1_task(root)

    result = run_one_cycle(str(root))
    assert result.get("outcome") == "success"

    status = load_status(root)
    assert status.last_cycle is not None
    assert status.last_cycle.outcome == "success"

    backlog = load_backlog(root)
    t1 = next(t for t in backlog.tasks if t.id == "T-0001")
    assert t1.status == "done"

    runs = list((root / "runs" / "AGENT_RUNS").glob("*_mock_worker_T-0001"))
    assert runs, "Expected AGENT_RUNS folder for T-0001"

    validations = list((root / "runs" / "VALIDATION_RESULTS").glob("*T-0001*"))
    assert validations, "Expected validation record for T-0001"

    daily = (root / "project" / "DAILY_REPORT.md").read_text()
    assert "T-0001" in daily


def test_tier2_docs_queues_approval_without_workspace_mutation():
    root = hub_root()
    _reset_tier1_task(root)

    backlog_path = root / "project" / "BACKLOG.yaml"
    data = yaml.safe_load(backlog_path.read_text())
    for t in data["tasks"]:
        if t["id"] == "T-0001":
            t["status"] = "done"
        if t["id"] == "T-0002":
            t["status"] = "ready"
    backlog_path.write_text(yaml.safe_dump(data, sort_keys=False))

    queue_path = root / "approvals" / "APPROVAL_QUEUE.yaml"
    queue_path.write_text("schema_version: 1\npending: []\n")

    decisions_path = root / "approvals" / "APPROVAL_DECISIONS.yaml"
    original_decisions = decisions_path.read_text()
    decisions_path.write_text("schema_version: 1\ndecisions: []\n")

    workspace_utils = root / "workspace" / "example" / "utils.py"
    original_content = workspace_utils.read_text() if workspace_utils.exists() else None
    if workspace_utils.exists():
        workspace_utils.unlink()

    try:
        result = run_one_cycle(str(root))
        assert result.get("outcome") == "approval_paused"

        queue = yaml.safe_load(queue_path.read_text())
        assert any(p["task_id"] == "T-0002" for p in queue.get("pending", []))

        paused = list((root / "runs" / "VALIDATION_RESULTS").glob("*T-0002*paused*"))
        assert paused

        assert not workspace_utils.exists(), "workspace must not be mutated in dry_run"

        backlog = load_backlog(root)
        t2 = next(t for t in backlog.tasks if t.id == "T-0002")
        assert t2.status == "paused"

        decision_log = (root / "project" / "DECISION_LOG.md").read_text()
        assert "A-0001" in decision_log or "T-0002" in decision_log
        assert "approval required" in decision_log.lower()
    finally:
        if original_content is not None:
            workspace_utils.parent.mkdir(parents=True, exist_ok=True)
            workspace_utils.write_text(original_content)
        decisions_path.write_text(original_decisions)


def test_no_ready_tasks_reports_no_task():
    root = hub_root()
    backlog_path = root / "project" / "BACKLOG.yaml"
    data = yaml.safe_load(backlog_path.read_text())
    for t in data["tasks"]:
        if t["status"] == "ready":
            t["status"] = "done"
    backlog_path.write_text(yaml.safe_dump(data, sort_keys=False))

    result = run_one_cycle(str(root))
    assert result.get("outcome") == "no_task"
    assert result.get("task") is None

    daily = (root / "project" / "DAILY_REPORT.md").read_text()
    assert "no_task" in daily


def test_dry_run_prevents_workspace_mutation_with_approval():
    """Even with a valid approval, dry_run must not write workspace files."""
    root = hub_root()
    backlog_path = root / "project" / "BACKLOG.yaml"
    data = yaml.safe_load(backlog_path.read_text())
    for t in data["tasks"]:
        if t["id"] == "T-0001":
            t["status"] = "done"
        if t["id"] == "T-0002":
            t["status"] = "ready"
    backlog_path.write_text(yaml.safe_dump(data, sort_keys=False))

    decisions_path = root / "approvals" / "APPROVAL_DECISIONS.yaml"
    original_decisions = decisions_path.read_text()
    decisions_path.write_text(
        """schema_version: 1
decisions:
- request_id: A-0001
  decision: approved
  decided_by: human
  decided_at: '2026-06-26T16:00:00Z'
  approved_scope:
    task_id: T-0002
    tier: 2
    target_folder: workspace/example
    allowed_files: ['workspace/example/utils.py']
    allowed_worker: mock_worker
    expires_at: '2099-01-01T00:00:00Z'
  note: test approval
"""
    )
    queue_path = root / "approvals" / "APPROVAL_QUEUE.yaml"
    queue_path.write_text("schema_version: 1\npending: []\n")

    workspace_utils = root / "workspace" / "example" / "utils.py"
    original_content = workspace_utils.read_text() if workspace_utils.exists() else None
    if workspace_utils.exists():
        workspace_utils.unlink()

    try:
        result = run_one_cycle(str(root))
        assert result.get("outcome") in ("success", "approval_queued", "approval_paused")
        assert not workspace_utils.exists(), "dry_run must not mutate workspace/"
    finally:
        if original_content is not None:
            workspace_utils.parent.mkdir(parents=True, exist_ok=True)
            workspace_utils.write_text(original_content)

    decisions_path.write_text(original_decisions)
