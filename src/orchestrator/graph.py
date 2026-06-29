"""LangGraph workflow definition."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph

from orchestrator.nodes.workflow import (
    approval_gate_node,
    checkpoint_node,
    execute_node,
    intake_node,
    plan_node,
    record_node,
    report_node,
    route_node,
    safety_check_node,
    validate_node,
)
from orchestrator.state import HubState


def _has_task(state: HubState) -> Literal["plan", "report"]:
    if state.get("task") and state.get("outcome") != "stopped":
        return "plan"
    return "report"


def _after_safety(
    state: HubState,
) -> Literal["execute", "approval_gate", "record"]:
    if state.get("skip_execute") and state.get("approval_status") == "pending":
        return "approval_gate"
    if state.get("skip_execute"):
        return "record"
    tier = state.get("tier", 1)
    if tier >= 2:
        return "approval_gate"
    return "execute"


def _after_approval(
    state: HubState,
) -> Literal["checkpoint", "record"]:
    if state.get("approval_status") == "approved":
        return "checkpoint"
    return "record"


def _needs_checkpoint(state: HubState) -> Literal["checkpoint", "execute"]:
    tier = state.get("tier", 1)
    if tier >= 2 and state.get("approval_status") == "approved":
        return "checkpoint"
    return "execute"


def _after_record(state: HubState) -> Literal["execute", "report"]:
    if state.get("retry_execute"):
        return "execute"
    return "report"


def build_graph():
    graph = StateGraph(HubState)

    graph.add_node("intake", intake_node)
    graph.add_node("plan", plan_node)
    graph.add_node("route", route_node)
    graph.add_node("safety_check", safety_check_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("checkpoint", checkpoint_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("record", record_node)
    graph.add_node("report", report_node)

    graph.set_entry_point("intake")
    graph.add_conditional_edges("intake", _has_task, {"plan": "plan", "report": "report"})
    graph.add_edge("plan", "route")
    graph.add_edge("route", "safety_check")
    graph.add_conditional_edges(
        "safety_check",
        _after_safety,
        {"execute": "execute", "approval_gate": "approval_gate", "record": "record"},
    )
    graph.add_conditional_edges(
        "approval_gate",
        _after_approval,
        {"checkpoint": "checkpoint", "record": "record"},
    )
    graph.add_edge("checkpoint", "execute")
    graph.add_edge("execute", "validate")
    graph.add_edge("validate", "record")
    graph.add_conditional_edges(
        "record",
        _after_record,
        {"execute": "execute", "report": "report"},
    )
    graph.add_edge("report", END)

    return graph.compile()


def run_one_cycle(root: str | None = None) -> HubState:
    from pathlib import Path

    from orchestrator.io.state_files import hub_root

    initial: HubState = {
        "root": str(hub_root(Path(root) if root else None)),
        "retries": 0,
        "log_refs": [],
        "messages": [],
    }
    app = build_graph()
    return app.invoke(initial)
