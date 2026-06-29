"""State file round-trip and schema validation tests."""

from pathlib import Path

import pytest

from orchestrator.io.state_files import (
    BacklogFile,
    BacklogTask,
    StatusFile,
    WriteGuardError,
    assert_write_allowed,
    hub_root,
    load_backlog,
    load_status,
    save_backlog,
    save_status,
)


def test_hub_root_finds_project(tmp_path):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "STATUS.json").write_text('{"schema_version":1}')
    assert hub_root(tmp_path) == tmp_path.resolve()


def test_status_round_trip():
    root = hub_root()
    status = load_status(root)
    status.mode = "dry_run"
    save_status(status, root)
    reloaded = load_status(root)
    assert reloaded.mode == "dry_run"
    assert reloaded.schema_version == 1


def test_backlog_schema_validation():
    backlog = load_backlog()
    assert backlog.schema_version == 1
    assert len(backlog.tasks) >= 2
    t1 = next(t for t in backlog.tasks if t.id == "T-0001")
    assert t1.type == "planning"
    assert t1.risk_tier == 1


def test_write_guard_blocks_outside_approved(tmp_path):
    approved = ["workspace", "project", "runs", "approvals"]
    bad = tmp_path / "outside" / "secret.txt"
    with pytest.raises(WriteGuardError):
        assert_write_allowed(bad, approved, tmp_path)


def test_write_guard_allows_project(tmp_path):
    approved = ["workspace", "project", "runs", "approvals"]
    good = tmp_path / "project" / "STATUS.json"
    good.parent.mkdir(parents=True)
    assert_write_allowed(good, approved, tmp_path)
