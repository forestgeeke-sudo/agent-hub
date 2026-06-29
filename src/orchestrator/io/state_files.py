"""Typed read/write helpers with pydantic schema validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator


class SchemaError(Exception):
    pass


class WriteGuardError(Exception):
    pass


# --- Pydantic schemas ---


class LastCycle(BaseModel):
    id: str
    outcome: str
    ended_at: str


class StatusFile(BaseModel):
    schema_version: int = 1
    updated_at: str
    mode: str
    active_task_id: Optional[str] = None
    last_cycle: Optional[LastCycle] = None
    blockers: List[str] = Field(default_factory=list)
    workers: Dict[str, str] = Field(default_factory=dict)
    stop_requested: bool = False


class BacklogTask(BaseModel):
    id: str
    title: str
    description: str
    type: str
    risk_tier: int
    priority: int
    target_folder: str
    suggested_worker: str
    depends_on: List[str] = Field(default_factory=list)
    status: str
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def coerce_created_at(cls, v: Any) -> str:
        if hasattr(v, "isoformat"):
            return v.isoformat().replace("+00:00", "Z")
        return str(v)


class BacklogFile(BaseModel):
    schema_version: int = 1
    tasks: List[BacklogTask] = Field(default_factory=list)


class WorkerLimit(BaseModel):
    auth_method: Optional[str] = None
    status: str = "unknown"
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    failure_type: Optional[str] = None
    retry_after: Optional[str] = None
    retry_after_is_guess: bool = True
    retry_confidence: str = "low"
    daily_uses: int = 0
    avoid_until: Optional[str] = None
    notes: Optional[str] = None


class LimitsFile(BaseModel):
    schema_version: int = 1
    workers: Dict[str, WorkerLimit] = Field(default_factory=dict)


class SessionState(BaseModel):
    turns: int = 0
    approx_input_bytes: int = 0
    started_at: Optional[str] = None
    last_activity: Optional[str] = None
    fresh_session_recommended: bool = False
    reason: Optional[str] = None
    consecutive_failures: int = 0


class ContextThresholds(BaseModel):
    max_turns: int = 25
    max_input_bytes: int = 400000
    stale_minutes: int = 120


class ContextStateFile(BaseModel):
    schema_version: int = 1
    sessions: Dict[str, SessionState] = Field(default_factory=dict)
    thresholds: ContextThresholds = Field(default_factory=ContextThresholds)


class RoutingDefaults(BaseModel):
    planner: str = "mock_planner"
    max_retries: int = 1


class TaskTypeRoute(BaseModel):
    primary: str
    fallbacks: List[str] = Field(default_factory=list)


class WorkerSelection(BaseModel):
    prefer_available: bool = True
    avoid_limited: bool = True
    on_all_unavailable: str = "safe_stop"


class RoutingRulesFile(BaseModel):
    schema_version: int = 1
    defaults: RoutingDefaults = Field(default_factory=RoutingDefaults)
    by_task_type: Dict[str, TaskTypeRoute] = Field(default_factory=dict)
    worker_selection: WorkerSelection = Field(default_factory=WorkerSelection)


class Tier2Preconditions(BaseModel):
    require_explicit_approval: bool = True
    require_git_checkpoint: bool = True
    require_validation: bool = True
    require_bounded_scope: bool = True
    forbid_path_substrings: List[str] = Field(default_factory=list)


class SafetyRulesFile(BaseModel):
    schema_version: int = 1
    mode: str = "dry_run"
    approved_folders: List[str] = Field(
        default_factory=lambda: ["workspace", "project", "runs", "approvals"]
    )
    auto_execute_max_tier: int = 1
    approval_required_tiers: List[int] = Field(default_factory=lambda: [2, 3, 4])
    tier2_preconditions: Tier2Preconditions = Field(default_factory=Tier2Preconditions)
    approval_scope_required_fields: List[str] = Field(default_factory=list)
    approval_timeout_minutes: int = 30
    stop_file: str = "STOP"
    never_send_to_cloud_workers: List[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    request_id: str
    task_id: str
    tier: int
    action_summary: str
    target_folder: str
    risk_notes: str = ""
    requested_at: str


class ApprovalQueueFile(BaseModel):
    schema_version: int = 1
    pending: List[ApprovalRequest] = Field(default_factory=list)


class ApprovedScope(BaseModel):
    task_id: str
    tier: int
    target_folder: str
    allowed_files: List[str]
    allowed_worker: str
    expires_at: str


class ApprovalDecision(BaseModel):
    request_id: str
    decision: str
    decided_by: str
    decided_at: str
    approved_scope: Optional[ApprovedScope] = None
    note: str = ""


class ApprovalDecisionsFile(BaseModel):
    schema_version: int = 1
    decisions: List[ApprovalDecision] = Field(default_factory=list)


class WorkersRegistryFile(BaseModel):
    schema_version: int = 1
    workers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


# --- Hub root resolution ---


def hub_root(start: Path | None = None) -> Path:
    """Walk up from *start* until we find project/STATUS.json."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "project" / "STATUS.json").exists():
            return candidate
    return current


# --- Write guard ---


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_write_allowed(target: Path, approved_folders: list[str], root: Path) -> None:
    """Raise WriteGuardError if *target* is outside approved folders."""
    target = target.resolve()
    root = root.resolve()
    for folder in approved_folders:
        approved = (root / folder).resolve()
        if _is_under(target, approved):
            return
    raise WriteGuardError(
        f"Write refused: {target} is outside approved folders {approved_folders}"
    )


def safe_write_text(
    path: Path,
    content: str,
    approved_folders: list[str],
    root: Path,
) -> None:
    assert_write_allowed(path, approved_folders, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def safe_write_json(
    path: Path,
    data: dict,
    approved_folders: list[str],
    root: Path,
) -> None:
    safe_write_text(
        path, json.dumps(data, indent=2) + "\n", approved_folders, root
    )


def safe_append_text(
    path: Path,
    content: str,
    approved_folders: list[str],
    root: Path,
) -> None:
    assert_write_allowed(path, approved_folders, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(content)


# --- Loaders ---


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: expected mapping, got {type(data)}")
    return data


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_status(root: Path | None = None) -> StatusFile:
    root = hub_root(root)
    return StatusFile.model_validate(_load_json(root / "project" / "STATUS.json"))


def save_status(status: StatusFile, root: Path | None = None) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    status.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_write_json(
        root / "project" / "STATUS.json",
        status.model_dump(),
        safety.approved_folders,
        root,
    )


def load_backlog(root: Path | None = None) -> BacklogFile:
    root = hub_root(root)
    return BacklogFile.model_validate(_load_yaml(root / "project" / "BACKLOG.yaml"))


def save_backlog(backlog: BacklogFile, root: Path | None = None) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    safe_write_text(
        root / "project" / "BACKLOG.yaml",
        yaml.safe_dump(backlog.model_dump(), sort_keys=False),
        safety.approved_folders,
        root,
    )


def load_limits(root: Path | None = None) -> LimitsFile:
    root = hub_root(root)
    return LimitsFile.model_validate(_load_json(root / "project" / "LIMITS.json"))


def save_limits(limits: LimitsFile, root: Path | None = None) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    safe_write_json(
        root / "project" / "LIMITS.json",
        limits.model_dump(),
        safety.approved_folders,
        root,
    )


def load_context_state(root: Path | None = None) -> ContextStateFile:
    root = hub_root(root)
    return ContextStateFile.model_validate(
        _load_json(root / "project" / "CONTEXT_STATE.json")
    )


def save_context_state(ctx: ContextStateFile, root: Path | None = None) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    safe_write_json(
        root / "project" / "CONTEXT_STATE.json",
        ctx.model_dump(),
        safety.approved_folders,
        root,
    )


def load_routing_rules(root: Path | None = None) -> RoutingRulesFile:
    root = hub_root(root)
    return RoutingRulesFile.model_validate(
        _load_yaml(root / "config" / "ROUTING_RULES.yaml")
    )


def load_safety_rules(root: Path | None = None) -> SafetyRulesFile:
    root = hub_root(root)
    return SafetyRulesFile.model_validate(
        _load_yaml(root / "config" / "SAFETY_RULES.yaml")
    )


def load_approval_queue(root: Path | None = None) -> ApprovalQueueFile:
    root = hub_root(root)
    return ApprovalQueueFile.model_validate(
        _load_yaml(root / "approvals" / "APPROVAL_QUEUE.yaml")
    )


def save_approval_queue(queue: ApprovalQueueFile, root: Path | None = None) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    safe_write_text(
        root / "approvals" / "APPROVAL_QUEUE.yaml",
        yaml.safe_dump(queue.model_dump(), sort_keys=False),
        safety.approved_folders,
        root,
    )


def write_approval_queue_entry(
    request: ApprovalRequest | dict[str, Any],
    root: Path | None = None,
) -> ApprovalRequest:
    """Append a validated approval request without replacing existing entries."""
    root = hub_root(root)
    queue = load_approval_queue(root)
    validated = (
        request
        if isinstance(request, ApprovalRequest)
        else ApprovalRequest.model_validate(request)
    )
    updated = ApprovalQueueFile(
        schema_version=queue.schema_version,
        pending=[*queue.pending, validated],
    )
    save_approval_queue(updated, root)
    return validated


def load_approval_decisions(root: Path | None = None) -> ApprovalDecisionsFile:
    root = hub_root(root)
    return ApprovalDecisionsFile.model_validate(
        _load_yaml(root / "approvals" / "APPROVAL_DECISIONS.yaml")
    )


def save_approval_decisions(
    decisions: ApprovalDecisionsFile, root: Path | None = None
) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    safe_write_text(
        root / "approvals" / "APPROVAL_DECISIONS.yaml",
        yaml.safe_dump(decisions.model_dump(), sort_keys=False),
        safety.approved_folders,
        root,
    )


def load_workers_registry(root: Path | None = None) -> WorkersRegistryFile:
    root = hub_root(root)
    return WorkersRegistryFile.model_validate(
        _load_yaml(root / "config" / "workers.yaml")
    )


def append_markdown(path: Path, content: str, root: Path | None = None) -> None:
    root = hub_root(root)
    safety = load_safety_rules(root)
    safe_append_text(path, content, safety.approved_folders, root)


def stop_requested(root: Path | None = None) -> bool:
    root = hub_root(root)
    safety = load_safety_rules(root)
    return (root / safety.stop_file).exists()
