"""Mock worker for Phase 1."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from orchestrator.io.state_files import hub_root, safe_write_text
from orchestrator.workers.base import WorkerAdapter, WorkerResult


class MockWorker(WorkerAdapter):
    name = "mock_worker"
    capabilities = {"planning", "docs", "code_edit", "test"}

    def availability(self) -> Literal["available", "limited", "unknown", "failed"]:
        return "available"

    def run(
        self,
        task: dict[str, Any],
        context: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> WorkerResult:
        root = Path(context.get("root", hub_root()))
        tier = int(task.get("risk_tier", 1))
        task_type = task.get("type", "planning")
        task_id = task.get("id", "unknown")
        approved = context.get("approved_folders", ["workspace", "project", "runs", "approvals"])
        execution_allowed = context.get("execution_allowed", False)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
        run_dir = root / "runs" / "AGENT_RUNS" / f"{ts}_mock_worker_{task_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        log_path = run_dir / "run.log"
        safe_write_text(
            log_path,
            f"mock_worker run for {task_id} (tier={tier}, type={task_type}, dry_run={dry_run})\n",
            approved,
            root,
        )

        context["run_dir"] = str(run_dir)

        if tier >= 2 and not execution_allowed:
            blocked_path = run_dir / "blocked.json"
            safe_write_text(
                blocked_path,
                json.dumps({"status": "needs_approval", "task_id": task_id}, indent=2) + "\n",
                approved,
                root,
            )
            return WorkerResult(
                status="blocked",
                exit_code=0,
                stdout=f"Tier {tier} task {task_id} blocked: approval required\n",
                stderr="",
                files_changed=[str(blocked_path.relative_to(root))],
                diff=None,
                notes="needs_approval",
            )

        if dry_run and task_type in ("docs", "code_edit", "refactor"):
            return WorkerResult(
                status="success",
                exit_code=0,
                stdout=f"[dry_run] Would edit files in {task.get('target_folder')}\n",
                stderr="",
                files_changed=[],
                diff=f"--- /dev/null\n+++ {task.get('target_folder')}/utils.py\n@@ mock diff @@\n",
                notes="dry_run_no_workspace_mutation",
            )

        files_changed: list[str] = [str(log_path.relative_to(root))]

        if task_type == "planning":
            decision_path = root / "project" / "DECISION_LOG.md"
            entry = (
                f"\n## {task_id} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"- Sprint planning notes recorded by mock_worker.\n"
            )
            safe_write_text(
                decision_path,
                decision_path.read_text(encoding="utf-8") + entry
                if decision_path.exists()
                else "# Decision Log\n" + entry,
                approved,
                root,
            )
            files_changed.append(str(decision_path.relative_to(root)))

        elif task_type == "docs" and execution_allowed and not dry_run:
            target = root / task.get("target_folder", "workspace/example") / "utils.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            content = '"""Format a date string."""\n\ndef format_date(d):\n    return str(d)\n'
            safe_write_text(target, content, approved, root)
            files_changed.append(str(target.relative_to(root)))
            diff = f"--- /dev/null\n+++ {target}\n@@ mock diff @@\n+{content}"
        else:
            diff = None
            if task_type == "docs":
                diff = f"--- /dev/null\n+++ {task.get('target_folder')}/utils.py\n@@ mock diff @@\n"

        return WorkerResult(
            status="success",
            exit_code=0,
            stdout=f"mock_worker completed {task_id}\n",
            stderr="",
            files_changed=files_changed,
            diff=diff if task_type == "docs" else None,
            notes="mock_success",
        )
