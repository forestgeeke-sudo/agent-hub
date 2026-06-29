from __future__ import annotations

import yaml

from orchestrator.graph import run_one_cycle
from orchestrator.io.state_files import load_backlog, load_approval_queue
from orchestrator.nodes.workflow import execute_node, record_node
from orchestrator.workers.base import WorkerResult

from phase3_helpers import write_root


def test_tier01_primary_fails_then_fallback_executes(tmp_path, monkeypatch):
    write_root(tmp_path)
    calls = []

    def fake_run(self, task, context, dry_run=False):
        calls.append(1)
        if len(calls) == 1:
            return WorkerResult(status="failed", stderr="boom")
        return WorkerResult(status="success", stdout="ok", diff="diff")

    monkeypatch.setattr("orchestrator.workers.mock_worker.MockWorker.run", fake_run)
    result = run_one_cycle(str(tmp_path))
    assert result["outcome"] == "success"
    assert len(calls) == 2
    assert load_backlog(tmp_path).tasks[0].status == "done"


def test_tier01_all_workers_fail_marks_blocked(tmp_path, monkeypatch):
    write_root(tmp_path)
    routing = yaml.safe_load((tmp_path / "config" / "ROUTING_RULES.yaml").read_text())
    routing["by_task_type"]["docs"]["fallbacks"] = ["alt_worker"]
    (tmp_path / "config" / "ROUTING_RULES.yaml").write_text(yaml.safe_dump(routing))

    def fake_run(self, task, context, dry_run=False):
        return WorkerResult(status="failed", stderr="boom")

    monkeypatch.setattr("orchestrator.workers.mock_worker.MockWorker.run", fake_run)
    result = run_one_cycle(str(tmp_path))
    assert result["outcome"] == "blocked"
    assert load_backlog(tmp_path).tasks[0].status == "blocked"


def _tier2_state(root, allowed_worker: str):
    (root / "approvals" / "APPROVAL_DECISIONS.yaml").write_text(
        f"""schema_version: 1
decisions:
- request_id: A-0001
  decision: approved
  decided_by: human
  decided_at: '2026-06-29T00:00:00Z'
  approved_scope:
    task_id: T-1000
    tier: 2
    target_folder: workspace/example
    allowed_files: ['workspace/example/utils.py']
    allowed_worker: {allowed_worker}
    expires_at: '2099-01-01T00:00:00Z'
"""
    )
    return {
        "root": str(root),
        "cycle_id": "C-9000",
        "task": {
            "id": "T-1000",
            "title": "tier2",
            "description": "tier2 docs",
            "type": "docs",
            "risk_tier": 2,
            "target_folder": "workspace/example",
        },
        "tier": 2,
        "chosen_worker": "mock_worker",
        "fallbacks": ["alt_worker"],
        "retries": 0,
        "max_retries": 1,
        "approval_request_id": "A-0001",
        "worker_result": {"status": "failed", "stderr": "boom"},
        "validation": {"passed": False},
        "messages": [],
    }


def test_tier2_fallback_different_worker_requires_new_approval(tmp_path):
    write_root(tmp_path, risk_tier=2)
    original = (tmp_path / "workspace" / "example" / "utils.py").read_text()
    result = record_node(_tier2_state(tmp_path, "mock_worker"))
    assert result["outcome"] == "approval_paused"
    assert load_backlog(tmp_path).tasks[0].status == "paused"
    assert load_approval_queue(tmp_path).pending[-1].task_id == "T-1000"
    assert (tmp_path / "workspace" / "example" / "utils.py").read_text() == original


def test_tier2_fallback_matching_allowed_worker_can_execute(tmp_path, monkeypatch):
    write_root(tmp_path, risk_tier=2)
    result = record_node(_tier2_state(tmp_path, "alt_worker"))
    assert result["retry_execute"] is True
    assert result["chosen_worker"] == "alt_worker"

    def fake_run(self, task, context, dry_run=False):
        return WorkerResult(status="success", stdout="ok", diff="diff")

    monkeypatch.setattr("orchestrator.workers.mock_worker.MockWorker.run", fake_run)
    executed = execute_node({**result, "approval_status": "approved", "skip_execute": False})
    assert executed["worker_result"]["status"] == "success"

