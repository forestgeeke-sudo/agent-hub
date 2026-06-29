from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from orchestrator.graph import run_one_cycle
from orchestrator.io.state_files import load_status
from orchestrator.workers.base import WorkerResult

from phase3_helpers import write_root


def test_phase3_cycle_primary_avoid_until_fallback_success(tmp_path, monkeypatch):
    write_root(tmp_path)
    limits = json.loads((tmp_path / "project" / "LIMITS.json").read_text())
    limits["workers"]["mock_worker"]["avoid_until"] = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "project" / "LIMITS.json").write_text(json.dumps(limits))

    def fake_run(self, task, context, dry_run=False):
        return WorkerResult(status="success", stdout="ok", diff="diff")

    monkeypatch.setattr("orchestrator.workers.mock_worker.MockWorker.run", fake_run)
    result = run_one_cycle(str(tmp_path))

    assert result["chosen_worker"] == "alt_worker"
    assert result["outcome"] == "success"
    assert (tmp_path / "project" / "HANDOFF.md").read_text() == ""
    assert "T-1000" in (tmp_path / "project" / "DAILY_REPORT.md").read_text()
    assert load_status(tmp_path).last_cycle.outcome == "success"


def test_phase3_cycle_threshold_handoff_stops_without_reexecute(tmp_path, monkeypatch):
    write_root(tmp_path)
    ctx = json.loads((tmp_path / "project" / "CONTEXT_STATE.json").read_text())
    ctx["thresholds"]["max_turns"] = 0
    (tmp_path / "project" / "CONTEXT_STATE.json").write_text(json.dumps(ctx))
    calls = []

    def fake_run(self, task, context, dry_run=False):
        calls.append(1)
        return WorkerResult(status="success", stdout="ok", diff="diff")

    monkeypatch.setattr("orchestrator.workers.mock_worker.MockWorker.run", fake_run)
    result = run_one_cycle(str(tmp_path))

    assert result["outcome"] == "handoff"
    assert len(calls) == 1
    assert "reason: turns" in (tmp_path / "project" / "HANDOFF.md").read_text()

