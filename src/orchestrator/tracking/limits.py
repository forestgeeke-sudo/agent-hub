"""Worker usage-limit tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from orchestrator.io.state_files import LimitsFile, WorkerLimit, hub_root, save_limits

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_worker(limits: LimitsFile, worker: str) -> WorkerLimit:
    if worker not in limits.workers:
        limits.workers[worker] = WorkerLimit()
    return limits.workers[worker]


def record_success(limits: LimitsFile, worker: str) -> LimitsFile:
    wl = _ensure_worker(limits, worker)
    if wl.status == "failed" and wl.failure_type == "auth_expired":
        return limits
    wl.status = "available"
    wl.last_success = _now_iso()
    wl.daily_uses += 1
    wl.avoid_until = None
    wl.notes = None
    return limits


def record_failure(
    limits: LimitsFile,
    worker: str,
    failure_type: str = "error",
    retry_after: str | None = None,
    *,
    is_guess: bool = True,
    confidence: str = "low",
    cooldown_minutes: int = 60,
) -> LimitsFile:
    wl = _ensure_worker(limits, worker)
    if failure_type == "auth_expired":
        wl.status = "failed"
        wl.last_failure = _now_iso()
        wl.failure_type = "auth_expired"
        wl.retry_after = None
        wl.avoid_until = None
        wl.retry_after_is_guess = True
        wl.retry_confidence = "low"
        wl.notes = "re-authentication required"
        logger.warning(
            "Worker %s authentication expired; engine will not retry until a human clears the flag",
            worker,
        )
        return limits

    wl.status = "limited" if failure_type == "usage_limit" else "failed"
    wl.last_failure = _now_iso()
    wl.failure_type = failure_type
    if retry_after:
        wl.retry_after = retry_after
        wl.retry_after_is_guess = is_guess
        wl.retry_confidence = confidence
        wl.avoid_until = retry_after
        wl.notes = None
    else:
        avoid = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
        wl.avoid_until = avoid.strftime("%Y-%m-%dT%H:%M:%SZ")
        wl.retry_after = None if failure_type == "usage_limit" else wl.avoid_until
        wl.retry_after_is_guess = True
        wl.retry_confidence = "low"
        wl.notes = None
    return limits


def worker_is_available(limits: LimitsFile, worker: str) -> bool:
    wl = limits.workers.get(worker)
    if wl is None:
        return True
    if wl.status in ("limited", "failed"):
        if wl.avoid_until:
            try:
                avoid = datetime.fromisoformat(wl.avoid_until.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < avoid:
                    return False
            except ValueError:
                return False
        else:
            return False
    return True


def update_limits_after_run(
    worker: str,
    result_status: str,
    root=None,
    worker_result: dict[str, Any] | None = None,
) -> None:
    root = hub_root(root)
    from orchestrator.io.state_files import load_limits

    limits = load_limits(root)
    if result_status == "success":
        record_success(limits, worker)
    elif result_status in ("limited", "failed", "timeout"):
        usage_signal = (worker_result or {}).get("usage_signal") or {}
        failure_type = usage_signal.get("failure_type")
        if not failure_type:
            failure_type = "usage_limit" if result_status == "limited" else "error"
        record_failure(
            limits,
            worker,
            failure_type=failure_type,
            retry_after=usage_signal.get("retry_after"),
            is_guess=usage_signal.get("retry_after_is_guess", True),
            confidence=usage_signal.get("retry_confidence", "low"),
        )
    save_limits(limits, root)
