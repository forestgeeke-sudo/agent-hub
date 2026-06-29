from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from orchestrator.io.state_files import load_status
from orchestrator.nodes.workflow import route_node

from phase3_helpers import write_root


def _state(root, suggested="mock_worker", confidence=0.5):
    return {
        "root": str(root),
        "cycle_id": "C-9000",
        "task": {
            "id": "T-1000",
            "title": "Route me",
            "description": "docs",
            "type": "docs",
            "risk_tier": 1,
            "target_folder": "workspace/example",
            "suggested_worker": suggested,
        },
        "plan": {
            "task_type": "docs",
            "risk_tier": 1,
            "suggested_worker": suggested,
            "confidence": confidence,
        },
        "messages": [],
        "log_refs": [],
    }


def _limits(root):
    return json.loads((root / "project" / "LIMITS.json").read_text())


def test_primary_worker_available_is_chosen(tmp_path):
    write_root(tmp_path)
    state = route_node(_state(tmp_path, confidence=0.1))
    assert state["chosen_worker"] == "mock_worker"
    assert state["fallbacks"] == ["alt_worker", "codex"]


def test_primary_avoid_until_future_uses_fallback(tmp_path):
    write_root(tmp_path)
    data = _limits(tmp_path)
    data["workers"]["mock_worker"]["avoid_until"] = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "project" / "LIMITS.json").write_text(json.dumps(data))
    state = route_node(_state(tmp_path, confidence=0.1))
    assert state["chosen_worker"] == "alt_worker"


def test_primary_failed_uses_fallback(tmp_path):
    write_root(tmp_path)
    data = _limits(tmp_path)
    data["workers"]["mock_worker"]["status"] = "failed"
    (tmp_path / "project" / "LIMITS.json").write_text(json.dumps(data))
    state = route_node(_state(tmp_path, confidence=0.1))
    assert state["chosen_worker"] == "alt_worker"


def test_planner_suggestion_wins_when_confident_capable_available(tmp_path):
    write_root(tmp_path)
    state = route_node(_state(tmp_path, suggested="codex", confidence=0.8))
    assert state["chosen_worker"] == "codex"


def test_all_workers_unavailable_safe_stop_writes_blocker(tmp_path):
    write_root(tmp_path)
    data = _limits(tmp_path)
    for worker in data["workers"].values():
        worker["status"] = "failed"
    (tmp_path / "project" / "LIMITS.json").write_text(json.dumps(data))
    state = route_node(_state(tmp_path, confidence=0.1))
    assert state["outcome"] == "safe_stop"
    assert load_status(tmp_path).blockers
    assert "Routing blocker" in (tmp_path / "project" / "DAILY_REPORT.md").read_text()


def test_fallback_order_matches_config_after_primary_excluded(tmp_path):
    write_root(tmp_path)
    state = route_node(_state(tmp_path, confidence=0.1))
    assert state["fallbacks"] == ["alt_worker", "codex"]

