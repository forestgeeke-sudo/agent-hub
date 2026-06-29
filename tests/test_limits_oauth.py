"""OAuth worker limit tracking tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orchestrator.io.state_files import load_limits
from orchestrator.tracking.limits import update_limits_after_run


def _root(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "project").mkdir()
    (root / "config").mkdir()
    (root / "project" / "STATUS.json").write_text(
        '{"schema_version":1,"updated_at":"2026-06-29T00:00:00Z","mode":"supervised"}\n'
    )
    (root / "config" / "SAFETY_RULES.yaml").write_text(
        "schema_version: 1\nmode: supervised\napproved_folders: [workspace, project, runs, approvals]\n"
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
    },
    "mock_worker": {
      "status": "available",
      "daily_uses": 0
    }
  }
}
"""
    )
    return root


def test_auth_expired_has_no_timed_retry(tmp_path):
    root = _root(tmp_path)
    update_limits_after_run(
        "codex",
        "failed",
        root,
        worker_result={"usage_signal": {"failure_type": "auth_expired"}},
    )
    worker = load_limits(root).workers["codex"]
    assert worker.status == "failed"
    assert worker.failure_type == "auth_expired"
    assert worker.retry_after is None
    assert worker.avoid_until is None
    assert "re-auth" in worker.notes


def test_usage_limit_gets_conservative_avoid_until(tmp_path):
    root = _root(tmp_path)
    before = datetime.now(timezone.utc)
    update_limits_after_run(
        "codex",
        "limited",
        root,
        worker_result={"usage_signal": {"failure_type": "usage_limit"}},
    )
    worker = load_limits(root).workers["codex"]
    avoid = datetime.fromisoformat(worker.avoid_until.replace("Z", "+00:00"))
    delta = (avoid - before).total_seconds()
    assert 55 * 60 <= delta <= 65 * 60
    assert worker.retry_after_is_guess is True
    assert worker.retry_confidence == "low"


def test_auth_expired_worker_not_auto_cleared_by_other_success(tmp_path):
    root = _root(tmp_path)
    update_limits_after_run(
        "codex",
        "failed",
        root,
        worker_result={"usage_signal": {"failure_type": "auth_expired"}},
    )
    update_limits_after_run("mock_worker", "success", root, worker_result={})
    worker = load_limits(root).workers["codex"]
    assert worker.status == "failed"
    assert worker.failure_type == "auth_expired"
