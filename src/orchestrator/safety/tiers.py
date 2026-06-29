"""Permission tier resolution."""

from __future__ import annotations

from typing import Any


def resolve_tier(task: dict[str, Any], plan: dict[str, Any] | None = None) -> int:
    """Return the effective risk tier for a task."""
    if plan and "risk_tier" in plan:
        return int(plan["risk_tier"])
    return int(task.get("risk_tier", 1))


def tier_requires_approval(tier: int, approval_required_tiers: list[int]) -> bool:
    return tier in approval_required_tiers


def tier_auto_allowed(tier: int, auto_execute_max_tier: int) -> bool:
    return tier <= auto_execute_max_tier
