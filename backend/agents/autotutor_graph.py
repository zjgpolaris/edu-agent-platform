"""Side-effect-free LangGraph replay for AutoTutor shadow parity."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.autotutor_domain import canonical_autotutor_projection


class AutoTutorShadowGraphState(TypedDict, total=False):
    schema_version: str
    legacy_state: dict[str, Any]
    remaining_nodes: list[str]
    visited_nodes: list[str]
    diagnostics: list[str]
    canonical: dict[str, Any]


_PHASE_NODES = (
    "plan",
    "retrieve",
    "content_gate",
    "teach",
    "prepare_assessment",
    "wait_answer",
    "judge",
    "reflect",
    "re_plan",
    "reteach",
    "prepare_exit_ticket",
    "verify_exit_ticket",
    "build_evidence_intent",
    "finalize",
)

_EVENT_NODE = {
    "plan": "plan",
    "tool_result": "retrieve",
    "content_gate": "content_gate",
    "teach": "teach",
    "act": "prepare_assessment",
    "observe": "wait_answer",
    "judge": "judge",
    "reflect": "reflect",
    "re_plan": "re_plan",
    "reteach": "reteach",
    "memory": "build_evidence_intent",
}


def _trace_nodes(legacy_state: dict[str, Any]) -> list[str]:
    nodes: list[str] = []
    steps = legacy_state.get("runtime_steps") if isinstance(legacy_state.get("runtime_steps"), list) else []
    for item in steps:
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("event_type") or "")
        if event_type == "exit_ticket":
            node = "verify_exit_ticket" if str(item.get("step_id") or "") == "exit_ticket_judge" else "prepare_exit_ticket"
        else:
            node = _EVENT_NODE.get(event_type)
        if node and (not nodes or nodes[-1] != node):
            nodes.append(node)
    status = str(legacy_state.get("status") or "")
    phase = str(legacy_state.get("phase") or "")
    if status == "completed" or phase == "completed":
        if not nodes or nodes[-1] != "finalize":
            nodes.append("finalize")
    elif status == "needs_content" or phase == "content_blocked":
        if not nodes or nodes[-1] != "content_gate":
            nodes.append("content_gate")
    elif phase == "exit_ticket":
        if not nodes or nodes[-1] != "wait_answer":
            nodes.append("wait_answer")
    elif status == "awaiting_answer" and (not nodes or nodes[-1] != "wait_answer"):
        nodes.append("wait_answer")
    return nodes


def _load_context(state: AutoTutorShadowGraphState) -> dict[str, Any]:
    legacy_state = state.get("legacy_state") if isinstance(state.get("legacy_state"), dict) else {}
    diagnostics = list(state.get("diagnostics") or [])
    if not legacy_state:
        diagnostics.append("shadow_input_incomplete")
    return {
        "schema_version": "v1.48-shadow",
        "remaining_nodes": _trace_nodes(legacy_state),
        "visited_nodes": [],
        "diagnostics": diagnostics,
    }


def _route(state: AutoTutorShadowGraphState) -> str:
    remaining = state.get("remaining_nodes") or []
    return remaining[0] if remaining else "project"


def _consume(expected: str):
    def consume(state: AutoTutorShadowGraphState) -> dict[str, Any]:
        remaining = list(state.get("remaining_nodes") or [])
        diagnostics = list(state.get("diagnostics") or [])
        if not remaining or remaining[0] != expected:
            diagnostics.append("shadow_execution_failed")
        elif remaining:
            remaining.pop(0)
        return {
            "remaining_nodes": remaining,
            "visited_nodes": [*(state.get("visited_nodes") or []), expected],
            "diagnostics": diagnostics,
        }

    return consume


def _project(state: AutoTutorShadowGraphState) -> dict[str, Any]:
    return {"canonical": canonical_autotutor_projection(state.get("legacy_state") or {})}


def build_autotutor_shadow_graph():
    graph = StateGraph(AutoTutorShadowGraphState)
    graph.add_node("load_context", _load_context)
    graph.add_node("project", _project)
    for node in _PHASE_NODES:
        graph.add_node(node, _consume(node))
    graph.add_edge(START, "load_context")
    routes = {node: node for node in _PHASE_NODES}
    routes["project"] = "project"
    graph.add_conditional_edges("load_context", _route, routes)
    for node in _PHASE_NODES:
        graph.add_conditional_edges(node, _route, routes)
    graph.add_edge("project", END)
    return graph.compile()


AUTOTUTOR_SHADOW_GRAPH = build_autotutor_shadow_graph()
