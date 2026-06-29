"""Tier resolution and approval gating tests."""

from orchestrator.safety.tiers import (
    resolve_tier,
    tier_auto_allowed,
    tier_requires_approval,
)


def test_resolve_tier_from_task():
    task = {"risk_tier": 2, "type": "docs"}
    assert resolve_tier(task) == 2


def test_resolve_tier_prefers_plan():
    task = {"risk_tier": 1}
    plan = {"risk_tier": 2}
    assert resolve_tier(task, plan) == 2


def test_tier_auto_allowed():
    assert tier_auto_allowed(0, 1)
    assert tier_auto_allowed(1, 1)
    assert not tier_auto_allowed(2, 1)


def test_tier_requires_approval():
    required = [2, 3, 4]
    assert tier_requires_approval(2, required)
    assert not tier_requires_approval(1, required)
