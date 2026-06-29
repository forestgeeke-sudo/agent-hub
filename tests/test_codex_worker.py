"""Codex worker adapter tests."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pytest

from orchestrator.workers.codex_worker import CodexWorker


FIXTURES = Path(__file__).parent / "fixtures" / "codex_stderr"


class _PopenMock:
    def __init__(self, stdout: str, stderr: str, exit_code: int) -> None:
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self._exit_code = exit_code

    def wait(self) -> int:
        return self._exit_code


def _hub(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "config").mkdir()
    (root / "workspace").mkdir()
    (root / "runs" / "AGENT_RUNS").mkdir(parents=True)
    (root / "project").mkdir()
    (root / "project" / "STATUS.json").write_text(
        '{"schema_version":1,"updated_at":"2026-06-29T00:00:00Z","mode":"supervised"}\n'
    )
    (root / "config" / "workers.yaml").write_text(
        """schema_version: 1
workers:
  codex:
    auth_method: oauth
    capabilities: [code_edit, docs, refactor]
    status: available
    command_template: "codex exec --sandbox workspace-write {task}"
"""
    )
    return root


def _patch_process(monkeypatch: pytest.MonkeyPatch, stderr: str, exit_code: int) -> None:
    def popen(*args, **kwargs):
        return _PopenMock("stdout progress\n", stderr, exit_code)

    def run(args, **kwargs):
        if args[:3] == ["git", "diff", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "diff --git a/example/utils.py b/example/utils.py\n", "")
        if args[:4] == ["git", "diff", "--name-only", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "example/utils.py\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("orchestrator.workers.codex_worker.subprocess.Popen", popen)
    monkeypatch.setattr("orchestrator.workers.codex_worker.subprocess.run", run)


@pytest.mark.parametrize(
    ("fixture", "exit_code", "status", "failure_type"),
    [
        ("normal_completion.txt", 0, "success", None),
        ("usage_limit.txt", 1, "limited", "usage_limit"),
        ("auth_expired.txt", 1, "failed", "auth_expired"),
        ("generic_error.txt", 2, "failed", "error"),
    ],
)
def test_codex_stderr_signal_classes(tmp_path, monkeypatch, fixture, exit_code, status, failure_type):
    root = _hub(tmp_path)
    stderr = (FIXTURES / fixture).read_text()
    _patch_process(monkeypatch, stderr, exit_code)

    result = CodexWorker(root).run(
        {"id": "T-0002", "title": "Docs", "description": "Add docstring"},
        {"root": str(root)},
        dry_run=False,
    )

    assert result.status == status
    assert result.usage_signal["failure_type"] == failure_type
    assert result.context_signal["bytes_sent"] == len("Add docstring")
    if failure_type == "usage_limit":
        assert result.usage_signal["avoid_until"]
        assert result.usage_signal["retry_after_is_guess"] is True
        assert result.usage_signal["retry_confidence"] == "low"
    if failure_type == "auth_expired":
        assert result.usage_signal["retry_after"] is None
        assert result.usage_signal["avoid_until"] is None
        assert "re-authentication" in result.notes


def test_dry_run_blocks_without_subprocess(tmp_path, monkeypatch):
    root = _hub(tmp_path)

    def fail_popen(*args, **kwargs):
        raise AssertionError("subprocess should not be invoked during dry_run")

    monkeypatch.setattr("orchestrator.workers.codex_worker.subprocess.Popen", fail_popen)

    result = CodexWorker(root).run(
        {"id": "T-0002", "description": "Add docstring"},
        {"root": str(root)},
        dry_run=True,
    )

    assert result.status == "blocked"
    assert result.notes == "dry_run active"


def test_success_populates_diff_and_files_changed(tmp_path, monkeypatch):
    root = _hub(tmp_path)
    _patch_process(monkeypatch, (FIXTURES / "normal_completion.txt").read_text(), 0)

    result = CodexWorker(root).run(
        {"id": "T-0002", "description": "Add docstring"},
        {"root": str(root)},
    )

    assert result.status == "success"
    assert "diff --git" in result.diff
    assert result.files_changed == ["example/utils.py"]
