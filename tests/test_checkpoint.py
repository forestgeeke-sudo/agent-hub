"""Checkpoint rollback tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.nodes.workflow import checkpoint_node


def test_checkpoint_sha_restores_pre_execution_content(tmp_path):
    root = tmp_path
    workspace = root / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@agent-hub.local"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "agent-hub dev"], cwd=workspace, check=True)

    target = workspace / "dummy.txt"
    target.write_text("pre-execution\n")

    state = {
        "root": str(root),
        "task": {"id": "T-ROLLBACK"},
        "tier": 2,
        "approval_status": "approved",
        "messages": [],
    }
    result = checkpoint_node(state)
    sha = result["checkpoint"]["git_sha"]
    assert sha

    target.write_text("post-execution\n")
    subprocess.run(["git", "reset", "--hard", sha], cwd=workspace, check=True, capture_output=True)

    assert target.read_text() == "pre-execution\n"
