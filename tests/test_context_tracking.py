from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from orchestrator.io.state_files import load_context_state
from orchestrator.tracking import context

from phase3_helpers import write_root


def test_turns_and_input_bytes_increment_and_persist(tmp_path):
    write_root(tmp_path)
    context.update("mock_worker", {"status": "success"}, "abc", tmp_path)
    context.update("mock_worker", {"status": "success"}, "defg", tmp_path)
    session = load_context_state(tmp_path).sessions["mock_worker"]
    assert session.turns == 2
    assert session.approx_input_bytes == 7
    assert (tmp_path / "project" / "CONTEXT_STATE.json").read_text()


def test_check_thresholds_turns(tmp_path):
    write_root(tmp_path)
    data = json.loads((tmp_path / "project" / "CONTEXT_STATE.json").read_text())
    data["sessions"]["mock_worker"] = {"turns": 26, "approx_input_bytes": 0}
    (tmp_path / "project" / "CONTEXT_STATE.json").write_text(json.dumps(data))
    assert context.check_thresholds("mock_worker", tmp_path) == (True, "turns")


def test_check_thresholds_stale(tmp_path):
    write_root(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    data = json.loads((tmp_path / "project" / "CONTEXT_STATE.json").read_text())
    data["sessions"]["mock_worker"] = {
        "turns": 1,
        "approx_input_bytes": 0,
        "last_activity": old.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (tmp_path / "project" / "CONTEXT_STATE.json").write_text(json.dumps(data))
    assert context.check_thresholds("mock_worker", tmp_path) == (True, "stale")


def test_check_thresholds_consecutive_failures(tmp_path):
    write_root(tmp_path)
    context.update("mock_worker", {"status": "failed"}, "a", tmp_path)
    context.update("mock_worker", {"status": "timeout"}, "b", tmp_path)
    assert context.check_thresholds("mock_worker", tmp_path) == (
        True,
        "consecutive_failures",
    )


def test_check_thresholds_false_when_clear_and_on_read_error(tmp_path):
    write_root(tmp_path)
    context.update("mock_worker", {"status": "success"}, "a", tmp_path)
    assert context.check_thresholds("mock_worker", tmp_path) == (False, None)
    (tmp_path / "project" / "CONTEXT_STATE.json").write_text("{")
    assert context.check_thresholds("mock_worker", tmp_path) == (False, None)

