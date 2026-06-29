"""Codex CLI worker adapter.

The exact command_template format may need adjustment once the installed Codex
CLI version is confirmed. Update workers.yaml rather than this file.
"""

from __future__ import annotations

import queue
import re
import shlex
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from orchestrator.io.state_files import hub_root, load_workers_registry
from orchestrator.workers.base import WorkerAdapter, WorkerResult


_USAGE_LIMIT_RE = re.compile(r"\b(rate limit|quota|too many requests|429)\b", re.I)
_AUTH_EXPIRED_RE = re.compile(
    r"\b(not authenticated|please log in|login required|session expired|unauthorized|401)\b",
    re.I,
)
_TOKEN_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.I),
    re.compile(r"\b(session|oauth|refresh|access)[_-]?token[=:]\s*[A-Za-z0-9._~+/=-]{8,}\b", re.I),
    re.compile(r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,}\b"),
]


class CodexWorker(WorkerAdapter):
    name = "codex"
    capabilities = {"code_edit", "docs", "refactor"}
    _turns = 0

    def __init__(self, root: Path | None = None) -> None:
        self.root = hub_root(root)

    def availability(self) -> Literal["available", "limited", "unknown", "failed"]:
        workers = load_workers_registry(self.root).workers
        status = workers.get(self.name, {}).get("status", "unknown")
        if status in ("available", "limited", "unknown", "failed"):
            return status
        return "unknown"

    def run(
        self,
        task: dict[str, Any],
        context: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> WorkerResult:
        task_text = str(task.get("description") or task.get("title") or task.get("id", ""))
        type(self)._turns += 1
        context_signal = {"turns": type(self)._turns, "bytes_sent": len(task_text.encode("utf-8"))}

        if dry_run:
            return WorkerResult(
                status="blocked",
                exit_code=None,
                usage_signal={"failure_type": None},
                context_signal=context_signal,
                notes="dry_run active",
            )

        root = Path(context.get("root", self.root))
        workspace = root / "workspace"
        task_id = task.get("id", "unknown")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        run_dir = root / "runs" / "AGENT_RUNS" / f"{ts}_codex_{task_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        context["run_dir"] = str(run_dir)

        command = self._command(task_text)
        stdout, stderr, exit_code = self._run_command(command, workspace, run_dir / "run.log")
        diff, files_changed = self._git_diff(workspace)
        usage_signal = self._usage_signal(stderr, exit_code)

        if exit_code == 0 and diff:
            status: Literal["success", "failed", "limited", "blocked", "timeout"] = "success"
            notes = "codex_success"
        elif exit_code == 0:
            status = "failed"
            usage_signal = {"failure_type": "error"}
            notes = "codex completed without workspace changes"
        elif usage_signal.get("failure_type") == "usage_limit":
            status = "limited"
            notes = "usage limit detected"
        elif usage_signal.get("failure_type") == "auth_expired":
            status = "failed"
            notes = "re-authentication required before retrying"
        else:
            status = "failed"
            notes = "codex subprocess failed"

        return WorkerResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            files_changed=files_changed,
            diff=diff,
            usage_signal=usage_signal,
            context_signal=context_signal,
            notes=notes,
        )

    def _command(self, task_text: str) -> list[str]:
        worker_config = load_workers_registry(self.root).workers.get(self.name, {})
        template = worker_config.get("command_template")
        if not template:
            raise ValueError("codex command_template is not configured")
        parts = shlex.split(str(template))
        return [task_text if part == "{task}" else part.replace("{task}", task_text) for part in parts]

    def _run_command(self, command: list[str], workspace: Path, log_path: Path) -> tuple[str, str, int]:
        proc = subprocess.Popen(
            command,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        lines: queue.Queue[tuple[str, str | None]] = queue.Queue()

        def reader(stream, label: str) -> None:
            try:
                for line in iter(stream.readline, ""):
                    lines.put((label, line))
            finally:
                lines.put((label, None))

        threads = [
            threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        closed = set()
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"$ {' '.join(shlex.quote(p) for p in command)}\n")
            while len(closed) < 2:
                label, line = lines.get()
                if line is None:
                    closed.add(label)
                    continue
                clean = redact_secrets(line)
                if label == "stdout":
                    stdout_parts.append(clean)
                else:
                    stderr_parts.append(clean)
                log.write(f"[{label}] {clean}")
                if not clean.endswith("\n"):
                    log.write("\n")

        exit_code = proc.wait()
        for thread in threads:
            thread.join(timeout=1)
        return "".join(stdout_parts), "".join(stderr_parts), int(exit_code)

    def _git_diff(self, workspace: Path) -> tuple[str, list[str]]:
        try:
            diff_result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
            )
            names_result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return "", []
        diff = diff_result.stdout if diff_result.returncode == 0 else ""
        files = [line.strip() for line in names_result.stdout.splitlines() if line.strip()]
        return diff, files

    def _usage_signal(self, stderr: str, exit_code: int) -> dict[str, Any]:
        if exit_code == 0:
            return {"failure_type": None}
        if _USAGE_LIMIT_RE.search(stderr):
            avoid = datetime.now(timezone.utc) + timedelta(minutes=60)
            return {
                "failure_type": "usage_limit",
                "avoid_until": avoid.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "retry_after": None,
                "retry_after_is_guess": True,
                "retry_confidence": "low",
            }
        if _AUTH_EXPIRED_RE.search(stderr):
            return {
                "failure_type": "auth_expired",
                "retry_after": None,
                "avoid_until": None,
                "notes": "re-authentication required before retrying",
            }
        return {"failure_type": "error"}


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
