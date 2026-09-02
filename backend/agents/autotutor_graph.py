"""Side-effect-free LangGraph executors for AutoTutor shadow and active transitions."""
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


class AutoTutorActiveGraphState(TypedDict, total=False):
    observation: Any
    outcome: Any
    diagnostics: list[str]
    visited_nodes: list[str]


def _active_load_context(state: AutoTutorActiveGraphState) -> dict[str, Any]:
    observation = state.get("observation")
    diagnostics: list[str] = []
    if observation is None or getattr(observation, "schema_version", None) != "v1.49-observation":
        diagnostics.append("active_observation_invalid")
    return {"diagnostics": diagnostics, "visited_nodes": ["load_context"]}


def _active_route(state: AutoTutorActiveGraphState) -> str:
    if state.get("diagnostics"):
        return "fail"
    observation = state.get("observation")
    kind = str(getattr(observation, "transition_kind", ""))
    return {
        "start": "plan",
        "lesson_answer": "judge",
        "exit_ticket_answer": "verify_exit_ticket",
        "recovery_resume": "recovery_resume",
    }.get(kind, "fail")


def _active_visit(name: str):
    def visit(state: AutoTutorActiveGraphState) -> dict[str, Any]:
        return {"visited_nodes": [*(state.get("visited_nodes") or []), name]}

    return visit


def _active_lesson_route(state: AutoTutorActiveGraphState) -> str:
    observation = state.get("observation")
    materialized = getattr(observation, "materialized", {}) if observation is not None else {}
    next_state = materialized.get("next_state") if isinstance(materialized, dict) else {}
    history = next_state.get("step_history") if isinstance(next_state, dict) else []
    latest = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    steps = next_state.get("lesson_plan") if isinstance(next_state, dict) else []
    index = int(next_state.get("current_step_index") or 0) if isinstance(next_state, dict) else 0
    current = steps[index] if isinstance(steps, list) and 0 <= index < len(steps) and isinstance(steps[index], dict) else {}
    if latest.get("is_correct") is False and current.get("replanned") and next_state.get("phase") == "lesson":
        return "reflect"
    return "build_effect_intents"


def _active_materialize(state: AutoTutorActiveGraphState) -> dict[str, Any]:
    """Materialize the already captured transition without I/O or persistence."""
    from agents.autotutor_execution import AutoTutorTransitionOutcome

    observation = state.get("observation")
    payload = getattr(observation, "materialized", None)
    try:
        outcome = AutoTutorTransitionOutcome.model_validate(payload or {})
    except Exception:
        return {"diagnostics": [*(state.get("diagnostics") or []), "active_outcome_invalid"]}
    outcome.executor_mode = "graph_active"
    outcome.diagnostics.visited_nodes = [*(state.get("visited_nodes") or []), "materialize_outcome"]
    return {"outcome": outcome, "visited_nodes": outcome.diagnostics.visited_nodes}


def _active_fail(state: AutoTutorActiveGraphState) -> dict[str, Any]:
    return {"outcome": None, "visited_nodes": list(state.get("visited_nodes") or [])}


def build_autotutor_active_graph():
    graph = StateGraph(AutoTutorActiveGraphState)
    graph.add_node("load_context", _active_load_context)
    graph.add_node("plan", _active_visit("plan"))
    graph.add_node("content_gate", _active_visit("content_gate"))
    graph.add_node("teach", _active_visit("teach"))
    graph.add_node("prepare_assessment", _active_visit("prepare_assessment"))
    graph.add_node("judge", _active_visit("judge"))
    graph.add_node("reflect", _active_visit("reflect"))
    graph.add_node("re_plan", _active_visit("re_plan"))
    graph.add_node("reteach", _active_visit("reteach"))
    graph.add_node("verify_exit_ticket", _active_visit("verify_exit_ticket"))
    graph.add_node("build_effect_intents", _active_visit("build_effect_intents"))
    graph.add_node("recovery_resume", _active_visit("recovery_resume"))
    graph.add_node("materialize", _active_materialize)
    graph.add_node("fail", _active_fail)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges(
        "load_context",
        _active_route,
        {
            "plan": "plan",
            "judge": "judge",
            "verify_exit_ticket": "verify_exit_ticket",
            "recovery_resume": "recovery_resume",
            "fail": "fail",
        },
    )
    graph.add_edge("plan", "content_gate")
    graph.add_edge("content_gate", "teach")
    graph.add_edge("teach", "prepare_assessment")
    graph.add_edge("prepare_assessment", "materialize")
    graph.add_conditional_edges(
        "judge",
        _active_lesson_route,
        {"reflect": "reflect", "build_effect_intents": "build_effect_intents"},
    )
    graph.add_edge("reflect", "re_plan")
    graph.add_edge("re_plan", "reteach")
    graph.add_edge("reteach", "build_effect_intents")
    graph.add_edge("verify_exit_ticket", "build_effect_intents")
    graph.add_edge("build_effect_intents", "materialize")
    graph.add_edge("recovery_resume", "materialize")
    graph.add_edge("materialize", END)
    graph.add_edge("fail", END)
    return graph.compile()


AUTOTUTOR_ACTIVE_GRAPH = build_autotutor_active_graph()


def execute_autotutor_active(observation: Any) -> Any:
    result = AUTOTUTOR_ACTIVE_GRAPH.invoke(
        {"observation": observation, "diagnostics": [], "visited_nodes": []},
        config={"callbacks": [], "recursion_limit": 20},
    )
    diagnostics = list(result.get("diagnostics") or []) if isinstance(result, dict) else ["active_execution_failed"]
    outcome = result.get("outcome") if isinstance(result, dict) else None
    if diagnostics or outcome is None:
        raise RuntimeError(diagnostics[0] if diagnostics else "active_execution_failed")
    return outcome
