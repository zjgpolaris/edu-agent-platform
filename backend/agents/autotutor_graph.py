"""Side-effect-free LangGraph executor for AutoTutor transition parity."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.autotutor_domain import apply_autotutor_transition, canonical_autotutor_projection


class AutoTutorShadowGraphState(TypedDict, total=False):
    schema_version: str
    envelope: dict[str, Any]
    ports: Any
    candidate: dict[str, Any]
    canonical: dict[str, Any]
    effect_intents: list[dict[str, Any]]
    visited_nodes: list[str]
    diagnostics: list[str]


def _load_context(state: AutoTutorShadowGraphState) -> dict[str, Any]:
    envelope = state.get("envelope") if isinstance(state.get("envelope"), dict) else {}
    diagnostics = list(state.get("diagnostics") or [])
    ports = state.get("ports")
    if not envelope or envelope.get("schema_version") != "v1.48.1-transition":
        diagnostics.append("shadow_input_incomplete")
    if ports is None or not getattr(ports, "fail_closed", False):
        diagnostics.append("shadow_ports_missing")
    elif getattr(ports, "attempts", None):
        attempts = getattr(ports, "attempts", {})
        if any(attempts.get(key, 0) for key in ("model", "retrieval", "tool", "network")):
            diagnostics.append("shadow_external_call_attempted")
        if any(value for key, value in attempts.items() if key not in {"model", "retrieval", "tool", "network"}):
            diagnostics.append("shadow_side_effect_attempted")
    return {
        "schema_version": "v1.48.1-transition",
        "diagnostics": diagnostics,
        "visited_nodes": [],
        "effect_intents": [],
    }


def _route(state: AutoTutorShadowGraphState) -> str:
    return "fail" if state.get("diagnostics") else "transition"


def _transition(state: AutoTutorShadowGraphState) -> dict[str, Any]:
    try:
        candidate = apply_autotutor_transition(state.get("envelope") or {})
    except ValueError as exc:
        code = str(exc)
        if code not in {"shadow_input_incomplete", "shadow_expected_state_forbidden"}:
            code = "shadow_execution_failed"
        return {"diagnostics": [*(state.get("diagnostics") or []), code]}
    except Exception:
        return {"diagnostics": [*(state.get("diagnostics") or []), "shadow_execution_failed"]}
    return {
        "candidate": candidate.after,
        "effect_intents": list(candidate.effect_intents),
        "visited_nodes": list(candidate.visited_nodes),
    }


def _project(state: AutoTutorShadowGraphState) -> dict[str, Any]:
    candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else {}
    if not candidate:
        return {"diagnostics": [*(state.get("diagnostics") or []), "shadow_execution_failed"]}
    return {"canonical": canonical_autotutor_projection(candidate)}


def _fail(_state: AutoTutorShadowGraphState) -> dict[str, Any]:
    return {"canonical": {}}


def build_autotutor_shadow_graph():
    graph = StateGraph(AutoTutorShadowGraphState)
    graph.add_node("load_context", _load_context)
    graph.add_node("transition", _transition)
    graph.add_node("project", _project)
    graph.add_node("fail", _fail)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges(
        "load_context",
        _route,
        {"transition": "transition", "fail": "fail"},
    )
    graph.add_edge("transition", "project")
    graph.add_edge("project", END)
    graph.add_edge("fail", END)
    return graph.compile()


AUTOTUTOR_SHADOW_GRAPH = build_autotutor_shadow_graph()
