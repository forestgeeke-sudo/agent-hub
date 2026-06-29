"""HubState carried through the LangGraph workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


class HubState(TypedDict, total=False):
    cycle_id: str
    mode: str
    root: str
    task: Optional[Dict[str, Any]]
    plan: Optional[Dict[str, Any]]
    chosen_worker: Optional[str]
    fallbacks: List[str]
    tier: int
    approval_status: Literal[
        "not_required", "pending", "approved", "denied", "timeout"
    ]
    approval_request_id: Optional[str]
    checkpoint: Optional[Dict[str, Any]]
    worker_result: Optional[Dict[str, Any]]
    validation: Optional[Dict[str, Any]]
    retries: int
    max_retries: int
    outcome: Optional[str]
    log_refs: List[str]
    skip_execute: bool
    dry_run: bool
    retry_execute: bool
    messages: List[str]
