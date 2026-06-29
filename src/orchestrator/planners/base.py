"""Planner interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.state import HubState
    from orchestrator.workers.base import WorkerResult


@dataclass
class Plan:
    steps: list[str]
    task_type: str
    risk_tier: int
    suggested_worker: str | None
    fallbacks: list[str]
    confidence: float
    rationale: str


@dataclass
class ReviewResult:
    passed: bool
    notes: str = ""


class PlannerInterface(ABC):
    @abstractmethod
    def plan(self, state: HubState) -> Plan: ...

    @abstractmethod
    def review(self, state: HubState, result: WorkerResult) -> ReviewResult: ...

    @abstractmethod
    def summarize(self, runs: list[dict]) -> str: ...
