"""Approval gate scope validation tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from orchestrator.io.state_files import load_backlog
from orchestrator.nodes.workflow import approval_gate_node


def _root(tmp_path: Path, decision_scope: dict | None) -> Path:
    root = tmp_path
    (root / "project").mkdir()
    (root / "config").mkdir()
    (root / "approvals").mkdir()
    (root / "runs" / "VALIDATION_RESULTS").mkdir(parents=True)
    (root / "project" / "STATUS.json").write_text(
        '{"schema_version":1,"updated_at":"2026-06-29T00:00:00Z","mode":"supervised"}\n'
    )
    (root / "config" / "SAFETY_RULES.yaml").write_text(
        "schema_version: 1\nmode: supervised\napproved_folders: [workspace, project, runs, approvals]\n"
    )
    (root / "project" / "BACKLOG.yaml").write_text(
        """schema_version: 1
tasks:
- id: T-0002
  title: Add a docstring
  description: Add a one-line docstring.
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
    (root / "approvals" / "APPROVAL_QUEUE.yaml").write_text("schema_version: 1\npending: []\n")
    decisions = {"schema_version": 1, "decisions": []}
    if decision_scope:
        decisions["decisions"].append(
            {
                "request_id": "A-0001",
                "decision": "approved",
                "decided_by": "human",
                "decided_at": "2026-06-29T00:00:00Z",
                "approved_scope": decision_scope,
                "note": "test",
            }
        )
    (root / "approvals" / "APPROVAL_DECISIONS.yaml").write_text(
        yaml.safe_dump(decisions, sort_keys=False)
    )
    return root


def _state(root: Path) -> dict:
    return {
        "root": str(root),
        "task": {
            "id": "T-0002",
            "type": "docs",
            "risk_tier": 2,
            "target_folder": "workspace/example",
            "title": "Add a docstring",
        },
        "tier": 2,
        "chosen_worker": "codex",
        "approval_status": "pending",
        "messages": [],
    }


def _scope(**overrides) -> dict:
    base = {
        "task_id": "T-0002",
        "tier": 2,
        "target_folder": "workspace/example",
        "allowed_files": ["workspace/example/utils.py"],
        "allowed_worker": "codex",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_valid_approval_proceeds_to_checkpoint(tmp_path):
    root = _root(tmp_path, _scope())
    result = approval_gate_node(_state(root))
    assert result["approval_status"] == "approved"
    assert result["skip_execute"] is False


def test_expired_approval_pauses(tmp_path):
    root = _root(tmp_path, _scope(expires_at="2020-01-01T00:00:00Z"))
    result = approval_gate_node(_state(root))
    assert result["outcome"] == "approval_paused"
    assert load_backlog(root).tasks[0].status == "paused"


def test_wrong_allowed_worker_pauses(tmp_path):
    root = _root(tmp_path, _scope(allowed_worker="mock_worker"))
    result = approval_gate_node(_state(root))
    assert result["outcome"] == "approval_paused"
    assert load_backlog(root).tasks[0].status == "paused"


def test_file_not_in_allowed_files_pauses(tmp_path):
    root = _root(tmp_path, _scope(allowed_files=["workspace/example/other.py"]))
    result = approval_gate_node(_state(root))
    assert result["outcome"] == "approval_paused"
    assert load_backlog(root).tasks[0].status == "paused"


def test_no_decision_record_pauses(tmp_path):
    root = _root(tmp_path, None)
    result = approval_gate_node(_state(root))
    assert result["outcome"] == "approval_paused"
    assert load_backlog(root).tasks[0].status == "paused"
