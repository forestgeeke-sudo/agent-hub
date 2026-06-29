from __future__ import annotations

import json
import yaml

from orchestrator.graph import run_one_cycle
from orchestrator.io.state_files import load_context_state
from orchestrator.workers.base import WorkerResult

from phase3_helpers import write_root


def test_threshold_trip_writes_scrubbed_handoff_and_stops(tmp_path, monkeypatch):
    write_root(tmp_path)
    ctx = json.loads((tmp_path / "project" / "CONTEXT_STATE.json").read_text())
    ctx["thresholds"]["max_turns"] = 0
    (tmp_path / "project" / "CONTEXT_STATE.json").write_text(json.dumps(ctx))
    backlog = yaml.safe_load((tmp_path / "project" / "BACKLOG.yaml").read_text())
    backlog["tasks"][0]["description"] = "Update docs with password=supersecret and access_token=abc123456."
    (tmp_path / "project" / "BACKLOG.yaml").write_text(yaml.safe_dump(backlog))

    calls = []

    def fake_run(self, task, context, dry_run=False):
        calls.append(1)
        return WorkerResult(
            status="success",
            stdout="ok",
            diff="diff",
            files_changed=["workspace/example/utils.py"],
        )

    monkeypatch.setattr("orchestrator.workers.mock_worker.MockWorker.run", fake_run)
    result = run_one_cycle(str(tmp_path))
    handoff = (tmp_path / "project" / "HANDOFF.md").read_text()

    assert result["outcome"] == "handoff"
    assert len(calls) == 1
    assert "handoff_id:" in handoff
    assert "reason: turns" in handoff
    assert "task_id: T-1000" in handoff
    assert "git_sha:" in handoff
    for section in ["Goal", "Done so far", "Current state", "Next concrete step", "Relevant files"]:
        assert f"## {section}" in handoff
    assert "supersecret" not in handoff
    assert "access_token=abc123456" not in handoff
    session = load_context_state(tmp_path).sessions["mock_worker"]
    assert session.fresh_session_recommended is True
    assert session.reason == "turns"

