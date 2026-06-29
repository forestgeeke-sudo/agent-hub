"""Graph node implementations."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.io.state_files import (
    ApprovalDecision,
    ApprovalRequest,
    BacklogFile,
    LastCycle,
    append_markdown,
    hub_root,
    load_approval_decisions,
    load_approval_queue,
    load_backlog,
    load_context_state,
    load_limits,
    load_routing_rules,
    load_safety_rules,
    load_status,
    load_workers_registry,
    save_backlog,
    save_context_state,
    save_status,
    safe_write_text,
    stop_requested,
    write_approval_queue_entry,
)
from orchestrator.planners.mock_planner import MockPlanner
from orchestrator.safety.permissions import check_target_folder
from orchestrator.safety.tiers import (
    resolve_tier,
    tier_auto_allowed,
    tier_requires_approval,
)
from orchestrator.state import HubState
from orchestrator.tracking import context as context_tracking
from orchestrator.tracking.limits import update_limits_after_run, worker_is_available
from orchestrator.workers.codex_worker import CodexWorker
from orchestrator.workers.mock_worker import MockWorker


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_cycle_id(root: Path) -> str:
    status = load_status(root)
    if status.last_cycle and status.last_cycle.id.startswith("C-"):
        try:
            num = int(status.last_cycle.id.split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"C-{num:04d}"


def _append_route_log(root: Path, state: HubState, line: str) -> list[str]:
    task = state.get("task") or {}
    cycle_id = state.get("cycle_id", "C-0000")
    task_id = task.get("id", "none")
    run_dir = root / "runs" / "AGENT_RUNS" / f"{cycle_id}_routing_{task_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")
    refs = list(state.get("log_refs", []))
    if str(run_dir) not in refs:
        refs.append(str(run_dir))
    return refs


def _add_blocker(root: Path, blocker: str) -> None:
    status = load_status(root)
    if blocker not in status.blockers:
        status.blockers.append(blocker)
    status.active_task_id = None
    save_status(status, root)


def _mark_task(root: Path, task_id: str, status_value: str) -> None:
    backlog = load_backlog(root)
    for t in backlog.tasks:
        if t.id == task_id:
            t.status = status_value
            break
    save_backlog(backlog, root)


def _select_next_task(backlog: BacklogFile) -> dict[str, Any] | None:
    done_ids = {t.id for t in backlog.tasks if t.status == "done"}
    ready = [
        t
        for t in backlog.tasks
        if t.status == "ready" and all(dep in done_ids for dep in t.depends_on)
    ]
    if not ready:
        return None
    ready.sort(key=lambda t: t.priority)
    task = ready[0]
    return task.model_dump()


def intake_node(state: HubState) -> HubState:
    root = Path(state.get("root", hub_root()))
    messages = list(state.get("messages", []))

    if stop_requested(root):
        messages.append("STOP file detected — halting")
        return {
            **state,
            "task": None,
            "outcome": "stopped",
            "stop_requested": True,
            "messages": messages,
        }

    backlog = load_backlog(root)
    task = _select_next_task(backlog)
    cycle_id = state.get("cycle_id") or _next_cycle_id(root)
    safety = load_safety_rules(root)
    status = load_status(root)

    if task:
        status.mode = safety.mode
        status.active_task_id = task["id"]
        save_status(status, root)
        messages.append(f"Selected task {task['id']}: {task['title']}")
    else:
        messages.append("No ready tasks in backlog")

    return {
        **state,
        "cycle_id": cycle_id,
        "mode": safety.mode,
        "dry_run": safety.mode == "dry_run",
        "task": task,
        "root": str(root),
        "max_retries": load_routing_rules(root).defaults.max_retries,
        "retries": state.get("retries", 0),
        "messages": messages,
    }


def plan_node(state: HubState) -> HubState:
    if not state.get("task"):
        return state
    planner = MockPlanner()
    plan = planner.plan(state)
    messages = list(state.get("messages", []))
    messages.append(f"Plan created: {plan.task_type} tier {plan.risk_tier}")
    return {
        **state,
        "plan": {
            "steps": plan.steps,
            "task_type": plan.task_type,
            "risk_tier": plan.risk_tier,
            "suggested_worker": plan.suggested_worker,
            "fallbacks": plan.fallbacks,
            "confidence": plan.confidence,
            "rationale": plan.rationale,
        },
        "messages": messages,
    }


def route_node(state: HubState) -> HubState:
    if not state.get("task") or not state.get("plan"):
        return state

    root = Path(state.get("root", hub_root()))
    routing = load_routing_rules(root)
    limits = load_limits(root)
    registry = load_workers_registry(root)
    plan = state["plan"]
    task = state["task"]
    task_type = plan["task_type"]

    route = routing.by_task_type.get(task_type)
    primary = route.primary if route else "mock_worker"
    configured_fallbacks = list(route.fallbacks) if route else []

    suggested = plan.get("suggested_worker")
    confidence = plan.get("confidence", 0.0)

    avoid_values: dict[str, str | None] = {}

    def capable(worker: str) -> bool:
        config = registry.workers.get(worker, {})
        capabilities = set(config.get("capabilities", []))
        return task_type in capabilities or worker == primary == "planner"

    def routable(worker: str) -> bool:
        config = registry.workers.get(worker, {})
        if config.get("status") == "future":
            return False
        if not capable(worker):
            return False
        wl = limits.workers.get(worker)
        avoid_values[worker] = wl.avoid_until if wl else None
        if wl and wl.status in {"limited", "failed"}:
            return False
        if wl and wl.avoid_until:
            try:
                avoid = datetime.fromisoformat(wl.avoid_until.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < avoid:
                    return False
            except ValueError:
                return False
        return worker_is_available(limits, worker)

    reason = "config_primary"
    if suggested and confidence >= 0.6 and routable(suggested):
        chosen = suggested
        reason = "planner_suggestion"
    elif routable(primary):
        chosen = primary
        reason = "config_primary"
    else:
        chosen = None
        for fb in configured_fallbacks:
            if routable(fb):
                chosen = fb
                reason = "primary_unavailable_fallback"
                break
        if chosen is None:
            action = routing.worker_selection.on_all_unavailable
            blocker = (
                f"All workers unavailable for task {task['id']} "
                f"(type={task_type}, action={action})"
            )
            _add_blocker(root, blocker)
            append_markdown(
                root / "project" / "DAILY_REPORT.md",
                f"\n## Routing blocker — {_now_iso()}\n- Task: {task['id']}\n- {blocker}\n",
                root,
            )
            log_refs = _append_route_log(
                root,
                state,
                (
                    f"chosen=None reason=all_unavailable action={action} "
                    f"fallbacks=[] avoid_until={avoid_values}"
                ),
            )
            messages = list(state.get("messages", []))
            messages.append(blocker)
            return {
                **state,
                "chosen_worker": None,
                "fallbacks": [],
                "skip_execute": True,
                "outcome": action,
                "messages": messages,
                "log_refs": log_refs,
            }

    tier = resolve_tier(task, plan)
    surviving_fallbacks = [
        fb for fb in configured_fallbacks if fb != chosen and routable(fb)
    ]
    log_refs = _append_route_log(
        root,
        state,
        (
            f"chosen={chosen} reason={reason} "
            f"fallbacks={surviving_fallbacks} avoid_until={avoid_values}"
        ),
    )
    messages = list(state.get("messages", []))
    messages.append(f"Routed to worker {chosen}, tier {tier} ({reason})")

    return {
        **state,
        "chosen_worker": chosen,
        "fallbacks": surviving_fallbacks,
        "tier": tier,
        "log_refs": log_refs,
        "messages": messages,
    }


def safety_check_node(state: HubState) -> HubState:
    if state.get("skip_execute") and state.get("outcome") in {"safe_stop", "queue"}:
        return state
    if not state.get("task"):
        return state

    root = Path(state.get("root", hub_root()))
    safety = load_safety_rules(root)
    task = state["task"]
    tier = state.get("tier", resolve_tier(task, state.get("plan")))

    ok, reason = check_target_folder(task.get("target_folder", ""), safety)
    messages = list(state.get("messages", []))

    if not ok:
        messages.append(f"Safety check failed: {reason}")
        return {
            **state,
            "outcome": "blocked",
            "approval_status": "denied",
            "skip_execute": True,
            "messages": messages,
        }

    if tier_requires_approval(tier, safety.approval_required_tiers):
        messages.append(f"Tier {tier} requires approval")
        return {
            **state,
            "approval_status": "pending",
            "skip_execute": True,
            "messages": messages,
        }

    if tier_auto_allowed(tier, safety.auto_execute_max_tier):
        messages.append(f"Tier {tier} auto-approved for execution")
        return {
            **state,
            "approval_status": "not_required",
            "skip_execute": False,
            "messages": messages,
        }

    messages.append(f"Tier {tier} not auto-allowed")
    return {
        **state,
        "approval_status": "pending",
        "skip_execute": True,
        "messages": messages,
    }


def _find_valid_approval(
    task: dict[str, Any],
    tier: int,
    worker: str,
    root: Path,
) -> ApprovalDecision | None:
    decisions = load_approval_decisions(root)
    now = datetime.now(timezone.utc)
    for d in decisions.decisions:
        if d.decision != "approved" or not d.approved_scope:
            continue
        scope = d.approved_scope
        if scope.task_id != task["id"]:
            continue
        if scope.tier != tier:
            continue
        if scope.target_folder != task.get("target_folder"):
            continue
        if scope.allowed_worker != worker:
            continue
        if _task_target_file(task) not in scope.allowed_files:
            continue
        try:
            expires = datetime.fromisoformat(scope.expires_at.replace("Z", "+00:00"))
            if now > expires:
                continue
        except ValueError:
            continue
        return d
    return None


def _task_target_file(task: dict[str, Any]) -> str:
    if task.get("target_file"):
        return str(task["target_file"])
    if task.get("type") == "docs":
        return str(Path(task.get("target_folder", "workspace")) / "utils.py")
    return str(task.get("target_folder", ""))


def _pause_task_for_approval_mismatch(
    state: HubState,
    reason: str,
    request_id: str | None = None,
) -> HubState:
    root = Path(state.get("root", hub_root()))
    task = state["task"]
    messages = list(state.get("messages", []))
    messages.append(f"Approval paused: {reason}")

    backlog = load_backlog(root)
    for t in backlog.tasks:
        if t.id == task["id"]:
            t.status = "paused"
            break
    save_backlog(backlog, root)

    val_dir = root / "runs" / "VALIDATION_RESULTS"
    val_dir.mkdir(parents=True, exist_ok=True)
    paused_record = {
        "task_id": task["id"],
        "type": "approval_paused",
        "status": "paused",
        "reason": reason,
        "request_id": request_id,
        "tier": state.get("tier"),
        "recorded_at": _now_iso(),
    }
    val_path = val_dir / f"{_now_iso().replace(':', '')}_{task['id']}_paused.json"
    val_path.write_text(json.dumps(paused_record, indent=2) + "\n", encoding="utf-8")

    return {
        **state,
        "approval_status": "denied",
        "approval_request_id": request_id,
        "skip_execute": True,
        "outcome": "approval_paused",
        "messages": messages,
    }


def approval_gate_node(state: HubState) -> HubState:
    if state.get("approval_status") != "pending" or not state.get("task"):
        return state

    root = Path(state.get("root", hub_root()))
    task = state["task"]
    tier = state.get("tier", 1)
    worker = state.get("chosen_worker", "mock_worker")
    messages = list(state.get("messages", []))

    existing = _find_valid_approval(task, tier, worker, root)
    if existing:
        messages.append(f"Found valid approval {existing.request_id}")
        return {
            **state,
            "approval_status": "approved",
            "approval_request_id": existing.request_id,
            "skip_execute": False,
            "messages": messages,
        }

    decisions = load_approval_decisions(root)
    matching_task = [
        d
        for d in decisions.decisions
        if d.approved_scope and d.approved_scope.task_id == task["id"]
    ]
    if matching_task:
        decision = matching_task[0]
        scope = decision.approved_scope
        assert scope is not None
        reason = "approval scope mismatch"
        try:
            expires = datetime.fromisoformat(scope.expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires:
                reason = "approval expired"
        except ValueError:
            reason = "approval expiration invalid"
        if scope.allowed_worker != worker:
            reason = "allowed_worker mismatch"
        elif _task_target_file(task) not in scope.allowed_files:
            reason = "target file not in allowed_files"
        elif scope.tier != tier:
            reason = "tier mismatch"
        elif scope.target_folder != task.get("target_folder"):
            reason = "target_folder mismatch"
        elif decision.decision != "approved":
            reason = "approval denied"
        return _pause_task_for_approval_mismatch(state, reason, decision.request_id)

    queue = load_approval_queue(root)
    request_id = f"A-{len(queue.pending) + len(load_approval_decisions(root).decisions) + 1:04d}"
    request = ApprovalRequest(
        request_id=request_id,
        task_id=task["id"],
        tier=tier,
        action_summary=f"{task.get('type')} task: {task.get('title')}",
        target_folder=task.get("target_folder", ""),
        risk_notes=f"Tier {tier} workspace mutation requires explicit approval",
        requested_at=_now_iso(),
    )
    write_approval_queue_entry(request, root)

    risk_note = (
        f"\n## {request_id} — {task['id']}\n"
        f"- Tier {tier} {task.get('type')} task queued for approval.\n"
        f"- Target: {task.get('target_folder')}\n"
        f"- Worker: {worker}\n"
    )
    append_markdown(root / "approvals" / "RISK_REVIEW.md", risk_note, root)

    val_dir = root / "runs" / "VALIDATION_RESULTS"
    val_dir.mkdir(parents=True, exist_ok=True)
    blocked_record = {
        "task_id": task["id"],
        "type": "approval_blocked",
        "status": "queued",
        "request_id": request_id,
        "tier": tier,
        "recorded_at": _now_iso(),
    }
    val_path = val_dir / f"{_now_iso().replace(':', '')}_{task['id']}_blocked.json"
    val_path.write_text(json.dumps(blocked_record, indent=2) + "\n", encoding="utf-8")

    messages.append(f"Queued approval request {request_id}")

    queued_state = {**state, "approval_request_id": request_id, "messages": messages}
    return _pause_task_for_approval_mismatch(
        queued_state,
        "no matching approval decision record",
        request_id,
    )


def checkpoint_node(state: HubState) -> HubState:
    if state.get("skip_execute") or not state.get("task"):
        return state

    root = Path(state.get("root", hub_root()))
    tier = state.get("tier", 1)
    if tier < 2:
        return {**state, "checkpoint": {"git_sha": None, "skipped": True}}

    workspace = root / "workspace"
    git_sha = None
    if (workspace / ".git").exists():
        import subprocess

        try:
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "agent-hub",
                "GIT_AUTHOR_EMAIL": "agent-hub@local",
                "GIT_COMMITTER_NAME": "agent-hub",
                "GIT_COMMITTER_EMAIL": "agent-hub@local",
            }
            subprocess.run(
                ["git", "add", "-A"],
                cwd=workspace,
                check=True,
                capture_output=True,
                env=env,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-m",
                    f"checkpoint: {state['task']['id']} pre-execution",
                ],
                cwd=workspace,
                check=True,
                capture_output=True,
                env=env,
            )
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            git_sha = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            git_sha = "no-git"

    messages = list(state.get("messages", []))
    messages.append(f"Checkpoint git_sha={git_sha}")
    return {
        **state,
        "checkpoint": {"git_sha": git_sha, "skipped": False},
        "messages": messages,
    }


def execute_node(state: HubState) -> HubState:
    if state.get("skip_execute") or not state.get("task"):
        return state

    root = Path(state.get("root", hub_root()))
    safety = load_safety_rules(root)
    task = state["task"]
    worker_name = state.get("chosen_worker", "mock_worker")
    dry_run = state.get("dry_run", safety.mode == "dry_run")
    execution_allowed = state.get("approval_status") == "approved"

    if worker_name == "codex":
        worker = CodexWorker(root)
    else:
        worker = MockWorker()
    context = {
        "root": str(root),
        "approved_folders": safety.approved_folders,
        "execution_allowed": execution_allowed,
        "dry_run": dry_run,
    }
    result = worker.run(task, context, dry_run=dry_run)

    log_refs = list(state.get("log_refs", []))
    if context.get("run_dir"):
        log_refs.append(context["run_dir"])

    messages = list(state.get("messages", []))
    messages.append(f"Execute: worker status={result.status}")

    return {
        **state,
        "worker_result": {
            "status": result.status,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "files_changed": result.files_changed,
            "diff": result.diff,
            "usage_signal": result.usage_signal,
            "context_signal": result.context_signal,
            "notes": result.notes,
        },
        "log_refs": log_refs,
        "messages": messages,
    }


def validate_node(state: HubState) -> HubState:
    if not state.get("task"):
        return state

    root = Path(state.get("root", hub_root()))
    task = state["task"]
    plan = state.get("plan") or {}
    task_type = plan.get("task_type", task.get("type", "planning"))
    worker_result = state.get("worker_result") or {}

    if state.get("outcome") == "approval_queued":
        return state
    if state.get("outcome") == "approval_paused":
        return state

    passed = True
    checks: list[str] = []
    warnings: list[str] = []

    if worker_result.get("status") == "blocked":
        passed = False
        checks.append("worker blocked — needs approval")
    elif worker_result.get("status") not in ("success",):
        passed = False
        checks.append(f"worker status={worker_result.get('status')}")

    if task_type == "planning":
        decision_log = (root / "project" / "DECISION_LOG.md").read_text(encoding="utf-8")
        if task["id"] not in decision_log and "Sprint planning" not in decision_log:
            passed = False
            checks.append("DECISION_LOG not updated")
        else:
            checks.append("DECISION_LOG updated")

    elif task_type == "docs":
        if worker_result.get("diff"):
            checks.append("diff present")
        else:
            warnings.append("no diff captured")
        checks.append("docs validation warn-only")

    elif task_type == "routing":
        checks.append("routing record-only")

    validation = {
        "task_id": task["id"],
        "task_type": task_type,
        "passed": passed,
        "checks": checks,
        "warnings": warnings,
        "validated_at": _now_iso(),
    }

    val_dir = root / "runs" / "VALIDATION_RESULTS"
    val_dir.mkdir(parents=True, exist_ok=True)
    ts = _now_iso().replace(":", "")
    val_path = val_dir / f"{ts}_{task['id']}_validation.json"
    val_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

    messages = list(state.get("messages", []))
    messages.append(f"Validation {'passed' if passed else 'failed'}")

    return {**state, "validation": validation, "messages": messages}


_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"(?:oauth|access|refresh|session)[_-]?token[=:]\s*[A-Za-z0-9._~+/=-]{6,}|"
    r"(?:password|credential|secret)[=:]\s*[^,\s]+)",
    re.I,
)


def _scrub(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text)


def _git_summary(root: Path) -> tuple[str, list[str]]:
    workspace = root / "workspace"
    if not (workspace / ".git").exists():
        return "No workspace git repository detected.", []
    import subprocess

    try:
        stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        names = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (FileNotFoundError, OSError):
        return "Unable to read workspace git diff summary.", []
    return stat or "No uncommitted workspace diff.", [n.strip() for n in names if n.strip()]


def _write_handoff(root: Path, state: HubState, reason: str) -> None:
    task = state.get("task") or {}
    checkpoint = state.get("checkpoint") or {}
    git_sha = checkpoint.get("git_sha")
    diff_summary, changed_files = _git_summary(root)
    handoff_id = f"H-{uuid.uuid4().hex[:8]}"
    relevant_files = changed_files[:20]
    if task.get("target_folder") and task.get("target_folder") not in relevant_files:
        relevant_files.append(str(task["target_folder"]))

    body = f"""---
handoff_id: {handoff_id}
reason: {reason}
task_id: {task.get("id", "unknown")}
git_sha: {git_sha}
fresh_session_recommended: true
created_at: {_now_iso()}
---

## Goal
{task.get("description") or task.get("title") or "Continue the current task."}

## Done so far
Worker {state.get("chosen_worker", "unknown")} ran once in cycle {state.get("cycle_id", "C-0000")}. Git diff summary:

{diff_summary}

## Current state
The session threshold tripped: {reason}. The workflow stopped after record/report and did not auto-restart a worker.

## Next concrete step
Review this handoff and continue task {task.get("id", "unknown")} in a fresh worker session if appropriate.

## Relevant files
{chr(10).join(f"- {path}" for path in relevant_files) if relevant_files else "- None"}
"""
    safety = load_safety_rules(root)
    safe_write_text(root / "project" / "HANDOFF.md", _scrub(body), safety.approved_folders, root)


def _approval_allowed_worker(state: HubState, root: Path) -> str | None:
    task = state.get("task") or {}
    request_id = state.get("approval_request_id")
    decisions = load_approval_decisions(root)
    for decision in decisions.decisions:
        if request_id and decision.request_id != request_id:
            continue
        scope = decision.approved_scope
        if scope and scope.task_id == task.get("id"):
            return scope.allowed_worker
    return None


def _queue_fallback_approval(state: HubState, fallback_worker: str, root: Path) -> str:
    task = state["task"]
    queue = load_approval_queue(root)
    request_id = f"A-{len(queue.pending) + len(load_approval_decisions(root).decisions) + 1:04d}"
    request = ApprovalRequest(
        request_id=request_id,
        task_id=task["id"],
        tier=state.get("tier", task.get("risk_tier", 2)),
        action_summary=f"Fallback worker {fallback_worker} requested for {task.get('title')}",
        target_folder=task.get("target_folder", ""),
        risk_notes=(
            "Original Tier-2 approval does not authorize this fallback worker; "
            "new approval required before execution."
        ),
        requested_at=_now_iso(),
    )
    write_approval_queue_entry(request, root)
    return request_id


def record_node(state: HubState) -> HubState:
    root = Path(state.get("root", hub_root()))
    messages = list(state.get("messages", []))

    if state.get("outcome") in ("approval_queued", "approval_paused"):
        status = load_status(root)
        status.mode = load_safety_rules(root).mode
        outcome = state.get("outcome", "approval_paused")
        status.last_cycle = LastCycle(
            id=state.get("cycle_id", "C-0000"),
            outcome=outcome,
            ended_at=_now_iso(),
        )
        status.active_task_id = None
        save_status(status, root)

        task = state.get("task") or {}
        request_id = state.get("approval_request_id", "A-????")
        tier = state.get("tier", task.get("risk_tier", "?"))
        reason = "no matching approved scope in APPROVAL_DECISIONS.yaml"
        if outcome == "approval_paused":
            reason = "approval scope mismatch or missing decision"
        entry = (
            f"\n## {request_id} — {task.get('id', 'unknown')}\n"
            f"- Decision: approval required (Tier {tier})\n"
            f"- Outcome: {outcome} — {reason}\n"
            f"- Target: {task.get('target_folder', 'unknown')}\n"
        )
        append_markdown(root / "project" / "DECISION_LOG.md", entry, root)

        messages.append(f"Recorded {outcome} outcome")
        return {**state, "messages": messages}

    if not state.get("task"):
        return state

    task = state["task"]
    worker_result = state.get("worker_result") or {}
    validation = state.get("validation") or {}
    worker_name = state.get("chosen_worker", "mock_worker")

    if state.get("outcome") in {"safe_stop", "queue"} and not worker_result:
        if state.get("outcome") == "safe_stop":
            _mark_task(root, task["id"], "blocked")
        status = load_status(root)
        status.mode = load_safety_rules(root).mode
        status.last_cycle = LastCycle(
            id=state.get("cycle_id", "C-0000"),
            outcome=state.get("outcome", "safe_stop"),
            ended_at=_now_iso(),
        )
        status.active_task_id = None
        save_status(status, root)
        messages.append(f"Recorded outcome={state.get('outcome')}")
        return {**state, "messages": messages}

    if worker_result:
        update_limits_after_run(
            worker_name,
            worker_result.get("status", "failed"),
            root,
            worker_result=worker_result,
        )
        context_tracking.update(
            worker_name,
            worker_result,
            str(task.get("description") or ""),
            root,
        )
        should_handoff, handoff_reason = context_tracking.check_thresholds(worker_name, root)
        if should_handoff and handoff_reason:
            ctx = load_context_state(root)
            sess = ctx.sessions.get(worker_name)
            if sess:
                sess.fresh_session_recommended = True
                sess.reason = handoff_reason
                save_context_state(ctx, root)
            _write_handoff(root, state, handoff_reason)
            append_markdown(
                root / "project" / "DAILY_REPORT.md",
                (
                    f"\n## Handoff — {_now_iso()}\n"
                    f"- Task: {task['id']}\n"
                    f"- Worker: {worker_name}\n"
                    f"- Reason: {handoff_reason}\n"
                    "- Cycle stopped for fresh session pickup.\n"
                ),
                root,
            )
            status = load_status(root)
            status.mode = load_safety_rules(root).mode
            status.last_cycle = LastCycle(
                id=state.get("cycle_id", "C-0000"),
                outcome="handoff",
                ended_at=_now_iso(),
            )
            status.active_task_id = None
            save_status(status, root)
            messages.append(f"Handoff written: {handoff_reason}")
            return {**state, "outcome": "handoff", "retry_execute": False, "messages": messages}

    failed_for_fallback = worker_result.get("status") in {"failed", "limited", "timeout"}
    fallbacks = list(state.get("fallbacks", []))
    retries_used = int(state.get("retries", 0) or 0)
    max_retries = int(state.get("max_retries", 0) or 0)
    if failed_for_fallback and fallbacks and retries_used < max_retries:
        fallback_worker = fallbacks.pop(0)
        tier = state.get("tier", task.get("risk_tier", 1))
        if tier >= 2:
            allowed_worker = _approval_allowed_worker(state, root)
            if allowed_worker and fallback_worker != allowed_worker:
                _mark_task(root, task["id"], "paused")
                request_id = _queue_fallback_approval(state, fallback_worker, root)
                messages.append(
                    f"Tier-2 fallback {fallback_worker} requires new approval {request_id}"
                )
                return {
                    **state,
                    "fallbacks": fallbacks,
                    "approval_request_id": request_id,
                    "outcome": "approval_paused",
                    "retry_execute": False,
                    "messages": messages,
                }
        messages.append(f"Retrying task {task['id']} with fallback {fallback_worker}")
        return {
            **state,
            "chosen_worker": fallback_worker,
            "fallbacks": fallbacks,
            "worker_result": None,
            "validation": None,
            "retries": retries_used + 1,
            "retry_execute": True,
            "messages": messages,
        }

    if failed_for_fallback and (not fallbacks or retries_used >= max_retries):
        _mark_task(root, task["id"], "blocked")
        blocker = f"Task {task['id']} blocked after all fallback workers failed"
        _add_blocker(root, blocker)
        append_markdown(
            root / "project" / "DAILY_REPORT.md",
            f"\n## Fallbacks exhausted — {_now_iso()}\n- {blocker}\n",
            root,
        )
        status = load_status(root)
        status.mode = load_safety_rules(root).mode
        status.last_cycle = LastCycle(
            id=state.get("cycle_id", "C-0000"),
            outcome="blocked",
            ended_at=_now_iso(),
        )
        status.active_task_id = None
        save_status(status, root)
        messages.append(blocker)
        return {**state, "outcome": "blocked", "retry_execute": False, "messages": messages}

    backlog = load_backlog(root)
    failure_type = (worker_result.get("usage_signal") or {}).get("failure_type")
    for t in backlog.tasks:
        if t.id == task["id"]:
            if validation.get("passed"):
                t.status = "done"
            elif failure_type == "auth_expired":
                t.status = "paused"
            elif worker_result.get("status") == "blocked":
                t.status = "blocked"
            else:
                t.status = "blocked"
            break
    save_backlog(backlog, root)

    outcome = "success" if validation.get("passed") else "failed"
    status = load_status(root)
    status.mode = load_safety_rules(root).mode
    status.last_cycle = LastCycle(
        id=state.get("cycle_id", "C-0000"),
        outcome=outcome,
        ended_at=_now_iso(),
    )
    status.active_task_id = None
    save_status(status, root)

    entry = (
        f"\n## {state.get('cycle_id')} — {task['id']}\n"
        f"- Outcome: {outcome}\n"
        f"- Worker: {worker_name}\n"
    )
    append_markdown(root / "project" / "DECISION_LOG.md", entry, root)

    messages.append(f"Recorded outcome={outcome}")
    return {**state, "outcome": outcome, "retry_execute": False, "messages": messages}


def report_node(state: HubState) -> HubState:
    root = Path(state.get("root", hub_root()))
    messages = list(state.get("messages", []))

    cycle_id = state.get("cycle_id", "C-0000")
    task = state.get("task")
    outcome = state.get("outcome", "no_task")
    task_id = task["id"] if task else "none"
    task_title = task.get("title", "") if task else ""

    report = (
        f"\n## Cycle {cycle_id} — {_now_iso()}\n"
        f"- Task: {task_id} {task_title}\n"
        f"- Outcome: {outcome}\n"
        f"- Mode: {state.get('mode', 'dry_run')}\n"
    )
    if state.get("approval_request_id"):
        report += f"- Approval request: {state['approval_request_id']}\n"
    if state.get("worker_result"):
        wr = state["worker_result"]
        report += f"- Worker status: {wr.get('status')}\n"

    append_markdown(root / "project" / "DAILY_REPORT.md", report, root)
    messages.append("Daily report updated")
    return {**state, "outcome": outcome, "messages": messages}
