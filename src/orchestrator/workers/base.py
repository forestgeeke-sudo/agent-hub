"""Worker adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class WorkerResult:
    status: Literal["success", "failed", "limited", "blocked", "timeout"]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    files_changed: list[str] = field(default_factory=list)
    diff: str | None = None
    usage_signal: dict | None = None
    context_signal: dict | None = None
    notes: str | None = None


class WorkerAdapter(ABC):
    name: str
    capabilities: set[str]

    @abstractmethod
    def availability(self) -> Literal["available", "limited", "unknown", "failed"]: ...

    @abstractmethod
    def run(
        self,
        task: dict[str, Any],
        context: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> WorkerResult: ...
