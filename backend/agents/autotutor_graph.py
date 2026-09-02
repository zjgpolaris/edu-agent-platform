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
    before: Any
    command: dict[str, Any]
    observations: Any
    outcome: Any
    diagnostics: list[str]
    visited_nodes: list[str]


def _active_load_context(state: AutoTutorActiveGraphState) -> dict[str, Any]:
    observation = state.get("observations")
    diagnostics: list[str] = []
    if observation is None or getattr(observation, "schema_version", None) != "v1.49.1-observation":
        diagnostics.append("active_observation_invalid")
    return {"diagnostics": diagnostics, "visited_nodes": ["load_context"]}


def _active_route(state: AutoTutorActiveGraphState) -> str:
    if state.get("diagnostics"):
        return "fail"
    observation = state.get("observations")
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
    before = state.get("before")
    payload = before.model_dump(mode="json") if hasattr(before, "model_dump") else (before or {})
    steps = payload.get("lesson_plan") if isinstance(payload, dict) else []
    index = int(payload.get("current_step_index") or 0) if isinstance(payload, dict) else 0
    current = steps[index] if isinstance(steps, list) and 0 <= index < len(steps) and isinstance(steps[index], dict) else {}
    question = current.get("question") if isinstance(current.get("question"), dict) else {}
    selected = str((state.get("command") or {}).get("answer") or "").strip()[:1].upper()
    correct = str(question.get("answer") or "").strip()[:1].upper()
    attempts = int(current.get("attempts") or 0) + 1
    replans = int(payload.get("replans") or 0) if isinstance(payload, dict) else 0
    if selected == correct:
        return "advance"
    if attempts < 3 and replans < 3:
        return "reflect"
    return "mark_struggling"


def _active_compute(state: AutoTutorActiveGraphState) -> dict[str, Any]:
    """Independently compute the complete transition from observations."""
    from agents.autotutor_transition_kernel import execute_autotutor_transition

    try:
        outcome = execute_autotutor_transition(
            before=state.get("before"),
            command=state.get("command") or {},
            observations=state.get("observations"),
        )
    except Exception:
        return {"diagnostics": [*(state.get("diagnostics") or []), "active_outcome_invalid"]}
    outcome.executor_mode = "graph_active"
    outcome.diagnostics.visited_nodes = [*(state.get("visited_nodes") or []), "build_outcome"]
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
    graph.add_node("advance", _active_visit("advance"))
    graph.add_node("next_content_or_exit", _active_visit("next_content_or_exit"))
    graph.add_node("mark_struggling", _active_visit("mark_struggling"))
    graph.add_node("reflect", _active_visit("reflect"))
    graph.add_node("re_plan", _active_visit("re_plan"))
    graph.add_node("reteach", _active_visit("reteach"))
    graph.add_node("verify_exit_ticket", _active_visit("verify_exit_ticket"))
    graph.add_node("calculate_mastery", _active_visit("calculate_mastery"))
    graph.add_node("build_effect_intents", _active_visit("build_effect_intents"))
    graph.add_node("recovery_resume", _active_visit("recovery_resume"))
    graph.add_node("validate_state", _active_visit("validate_state"))
    graph.add_node("route_current_phase", _active_visit("route_current_phase"))
    graph.add_node("build_outcome", _active_compute)
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
    graph.add_edge("prepare_assessment", "build_outcome")
    graph.add_conditional_edges(
        "judge",
        _active_lesson_route,
        {"advance": "advance", "reflect": "reflect", "mark_struggling": "mark_struggling"},
    )
    graph.add_edge("advance", "next_content_or_exit")
    graph.add_edge("mark_struggling", "advance")
    graph.add_edge("next_content_or_exit", "build_effect_intents")
    graph.add_edge("reflect", "re_plan")
    graph.add_edge("re_plan", "reteach")
    graph.add_edge("reteach", "build_effect_intents")
    graph.add_edge("verify_exit_ticket", "calculate_mastery")
    graph.add_edge("calculate_mastery", "build_effect_intents")
    graph.add_edge("build_effect_intents", "build_outcome")
    graph.add_edge("recovery_resume", "validate_state")
    graph.add_edge("validate_state", "route_current_phase")
    graph.add_edge("route_current_phase", "build_outcome")
    graph.add_edge("build_outcome", END)
    graph.add_edge("fail", END)
    return graph.compile()


AUTOTUTOR_ACTIVE_GRAPH = build_autotutor_active_graph()


def execute_autotutor_active(*, before: Any, command: dict[str, Any], observations: Any) -> Any:
    result = AUTOTUTOR_ACTIVE_GRAPH.invoke(
        {
            "before": before,
            "command": command,
            "observations": observations,
            "diagnostics": [],
            "visited_nodes": [],
        },
        config={"callbacks": [], "recursion_limit": 20},
    )
    diagnostics = list(result.get("diagnostics") or []) if isinstance(result, dict) else ["active_execution_failed"]
    outcome = result.get("outcome") if isinstance(result, dict) else None
    if diagnostics or outcome is None:
        raise RuntimeError(diagnostics[0] if diagnostics else "active_execution_failed")
    return outcome
