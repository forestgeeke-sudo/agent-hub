"""Session/context heuristics tracking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from orchestrator.io.state_files import (
    ContextStateFile,
    SessionState,
    hub_root,
    load_context_state,
    save_context_state,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_session(ctx: ContextStateFile, worker: str) -> SessionState:
    if worker not in ctx.sessions:
        ctx.sessions[worker] = SessionState()
    return ctx.sessions[worker]


def _result_status(worker_result: Any) -> str | None:
    if isinstance(worker_result, dict):
        return worker_result.get("status")
    return getattr(worker_result, "status", None)


def record_worker_activity(
    ctx: ContextStateFile,
    worker: str,
    input_bytes: int = 0,
) -> ContextStateFile:
    sess = _ensure_session(ctx, worker)
    now = _now_iso()
    if sess.started_at is None:
        sess.started_at = now
    sess.last_activity = now
    sess.turns += 1
    sess.approx_input_bytes += input_bytes
    _evaluate_thresholds(ctx, worker)
    return ctx


def update(worker: str, worker_result: Any, task_description: str = "", root=None) -> ContextStateFile:
    """Update a worker session after execution and persist CONTEXT_STATE.json."""
    root = hub_root(Path(root) if root else None)
    ctx = load_context_state(root)
    sess = _ensure_session(ctx, worker)
    now = _now_iso()
    if sess.started_at is None:
        sess.started_at = now
    sess.last_activity = now
    sess.turns += 1
    sess.approx_input_bytes += len(task_description.encode("utf-8"))

    if _result_status(worker_result) in {"failed", "limited", "timeout"}:
        sess.consecutive_failures += 1
    else:
        sess.consecutive_failures = 0

    save_context_state(ctx, root)
    return ctx


def check_thresholds(worker: str, root=None) -> tuple[bool, str | None]:
    """Return whether a fresh worker session should be requested.

    This function is intentionally defensive: context tracking must not break
    the workflow, so any read/parse error returns no threshold trip.
    """
    try:
        root = hub_root(Path(root) if root else None)
        ctx = load_context_state(root)
        sess = ctx.sessions.get(worker)
        if sess is None:
            return False, None
        thresholds = ctx.thresholds
        reason = None
        if sess.turns > thresholds.max_turns:
            reason = "turns"
        elif sess.approx_input_bytes > thresholds.max_input_bytes:
            reason = "bytes"
        elif sess.last_activity:
            try:
                last = datetime.fromisoformat(sess.last_activity.replace("Z", "+00:00"))
                stale_at = datetime.now(timezone.utc) - timedelta(
                    minutes=thresholds.stale_minutes
                )
                if last < stale_at:
                    reason = "stale"
            except ValueError:
                return False, None
        if reason is None and sess.consecutive_failures >= 2:
            reason = "consecutive_failures"
        sess.fresh_session_recommended = reason is not None
        sess.reason = reason
        save_context_state(ctx, root)
        if reason:
            return True, reason
        return False, None
    except Exception:
        return False, None


def _evaluate_thresholds(ctx: ContextStateFile, worker: str) -> None:
    sess = ctx.sessions[worker]
    thresholds = ctx.thresholds
    reasons: list[str] = []
    if sess.turns > thresholds.max_turns:
        reasons.append(f"turns ({sess.turns}) > max_turns ({thresholds.max_turns})")
    if sess.approx_input_bytes > thresholds.max_input_bytes:
        reasons.append(
            f"approx_input_bytes ({sess.approx_input_bytes}) > max ({thresholds.max_input_bytes})"
        )
    if sess.last_activity:
        try:
            last = datetime.fromisoformat(sess.last_activity.replace("Z", "+00:00"))
            stale = datetime.now(timezone.utc) - timedelta(minutes=thresholds.stale_minutes)
            if last < stale:
                reasons.append(f"idle > {thresholds.stale_minutes} minutes")
        except ValueError:
            pass
    if reasons:
        sess.fresh_session_recommended = True
        sess.reason = "; ".join(reasons)
    else:
        sess.fresh_session_recommended = False
        sess.reason = None


def update_context_after_run(
    worker: str,
    stdout: str = "",
    stderr: str = "",
    root=None,
) -> None:
    root = hub_root(root)
    ctx = load_context_state(root)
    input_bytes = len(stdout.encode()) + len(stderr.encode())
    record_worker_activity(ctx, worker, input_bytes=input_bytes)
    save_context_state(ctx, root)
