"""Deterministic mock planner."""

from __future__ import annotations

from orchestrator.planners.base import Plan, PlannerInterface, ReviewResult
from orchestrator.state import HubState
from orchestrator.workers.base import WorkerResult


class MockPlanner(PlannerInterface):
    def plan(self, state: HubState) -> Plan:
        task = state.get("task") or {}
        task_type = task.get("type", "planning")
        risk_tier = int(task.get("risk_tier", 1))
        suggested = task.get("suggested_worker", "mock_worker")
        return Plan(
            steps=[
                f"Analyze task {task.get('id', '?')}",
                f"Execute {task_type} work in {task.get('target_folder', 'project')}",
                "Record results and validate",
            ],
            task_type=task_type,
            risk_tier=risk_tier,
            suggested_worker=suggested,
            fallbacks=[],
            confidence=0.9,
            rationale=f"Deterministic plan from BACKLOG fields for {task.get('id')}",
        )

    def review(self, state: HubState, result: WorkerResult) -> ReviewResult:
        passed = result.status == "success"
        return ReviewResult(
            passed=passed,
            notes=f"Mock review: worker status={result.status}",
        )

    def summarize(self, runs: list[dict]) -> str:
        lines = [f"- {r.get('id', '?')}: {r.get('outcome', '?')}" for r in runs]
        return "Mock summary:\n" + "\n".join(lines)
