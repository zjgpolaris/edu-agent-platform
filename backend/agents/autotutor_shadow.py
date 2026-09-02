"""AutoTutor LangGraph shadow transition execution and parity evidence."""
from __future__ import annotations

import copy
import logging
import os
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from agents.autotutor_domain import canonical_autotutor_projection, parity_mismatch_reasons


logger = logging.getLogger(__name__)
_TRUE = {"1", "true", "yes", "on"}
TRANSITION_SCHEMA_VERSION = "v1.48.1-transition"
_FORBIDDEN_ENVELOPE_KEYS = {"legacy_after", "expected_projection", "expected_state"}


class ShadowSideEffectForbidden(RuntimeError):
    pass


class DenyShadowPorts:
    """Fail-closed dependency boundary supplied to every shadow graph run."""

    fail_closed = True

    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}

    def _forbid(self, operation: str) -> None:
        self.attempts[operation] = self.attempts.get(operation, 0) + 1
        if operation in {"model", "retrieval", "tool", "network"}:
            raise ShadowSideEffectForbidden(f"shadow_external_call_forbidden:{operation}")
        raise ShadowSideEffectForbidden(f"shadow_side_effect_forbidden:{operation}")

    def model(self, *_args: Any, **_kwargs: Any) -> None:
        self._forbid("model")

    def retrieve(self, *_args: Any, **_kwargs: Any) -> None:
        self._forbid("retrieval")

    def tool(self, *_args: Any, **_kwargs: Any) -> None:
        self._forbid("tool")

    def network(self, *_args: Any, **_kwargs: Any) -> None:
        self._forbid("network")

    def save(self, *_args: Any, **_kwargs: Any) -> None:
        self._forbid("session_store")

    def write_runtime(self, *_args: Any, **_kwargs: Any) -> None:
        self._forbid("runtime_store")


class DenyShadowEffects(DenyShadowPorts):
    """Backward-compatible alias used by existing callers and tests."""

    def __getattr__(self, operation: str):
        def forbidden(*_args: Any, **_kwargs: Any):
            self._forbid(operation)

        return forbidden


@dataclass(frozen=True)
class AutoTutorShadowResult:
    matched: bool
    reason_codes: tuple[str, ...]
    visited_nodes: tuple[str, ...]
    config_version: str
    transition_kind: str = "unknown"
    duration_ms: float = 0.0
    external_call_attempts: int = 0
    side_effect_attempts: int = 0


_METRICS: deque[dict[str, Any]] = deque(maxlen=500)
_METRICS_LOCK = Lock()


def shadow_enabled() -> bool:
    return os.getenv("EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED", "").strip().lower() in _TRUE


def shadow_config_version() -> str:
    return os.getenv("EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_CONFIG_VERSION", "v1.48.1-shadow").strip() or "v1.48.1-shadow"


def shadow_timeout_ms() -> float:
    try:
        return max(1.0, float(os.getenv("EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_TIMEOUT_MS", "50")))
    except ValueError:
        return 50.0


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _content_observation(state: dict[str, Any], step_index: int) -> dict[str, Any]:
    steps = state.get("lesson_plan") if isinstance(state.get("lesson_plan"), list) else []
    if step_index < 0 or step_index >= len(steps) or not isinstance(steps[step_index], dict):
        return {}
    step = steps[step_index]
    validation = step.get("content_validation") if isinstance(step.get("content_validation"), dict) else {}
    question = step.get("question") if isinstance(step.get("question"), dict) else {}
    if state.get("phase") == "content_blocked" or validation.get("status") == "blocked":
        return {"outcome": "blocked"}
    return {
        "outcome": "verified",
        "assessment": {
            "assessment_id": question.get("assessment_id"),
            "objective_id": question.get("objective_id"),
            "difficulty": question.get("difficulty") or step.get("difficulty"),
        },
    }


def _exit_ticket_observation(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("phase") == "content_blocked":
        return {"outcome": "blocked"}
    ticket = state.get("exit_ticket") if isinstance(state.get("exit_ticket"), dict) else {}
    question = ticket.get("question") if isinstance(ticket.get("question"), dict) else {}
    return {
        "outcome": "verified" if ticket else "blocked",
        "ticket": {
            "knowledge_point": ticket.get("knowledge_point"),
            "source_tag": ticket.get("source_tag"),
            "generated_from": ticket.get("generated_from"),
            "assessment": {
                "assessment_id": question.get("assessment_id"),
                "objective_id": question.get("objective_id"),
                "difficulty": question.get("difficulty") or ticket.get("difficulty"),
            },
        },
    }


def capture_transition_observations(transition_kind: str, before: Any, legacy_after: Any) -> dict[str, Any]:
    """Capture only non-deterministic results; never return the Legacy after state."""
    before_data = _dump(before)
    after_data = _dump(legacy_after)
    if transition_kind == "start":
        plan = []
        for raw in after_data.get("lesson_plan") or []:
            if isinstance(raw, dict):
                plan.append({"knowledge_point": raw.get("knowledge_point"), "difficulty": raw.get("difficulty")})
        return {"plan": plan, "content": _content_observation(after_data, 0)}
    if transition_kind == "lesson_answer":
        observations: dict[str, Any] = {}
        before_reflections = before_data.get("reflect_log") if isinstance(before_data.get("reflect_log"), list) else []
        after_reflections = after_data.get("reflect_log") if isinstance(after_data.get("reflect_log"), list) else []
        if len(after_reflections) > len(before_reflections) and isinstance(after_reflections[-1], dict):
            latest = after_reflections[-1]
            observations["reflection"] = {
                "adjustment": latest.get("adjustment"),
                "explanation": latest.get("explanation"),
            }
        before_index = int(before_data.get("current_step_index") or 0)
        after_index = int(after_data.get("current_step_index") or 0)
        if after_data.get("phase") == "exit_ticket" or after_data.get("exit_ticket"):
            observations["advance"] = _exit_ticket_observation(after_data)
        elif after_index != before_index:
            observations["advance"] = _content_observation(after_data, after_index)
        else:
            observations["content"] = _content_observation(after_data, after_index)
            observations.setdefault("advance", observations["content"])
        return observations
    return {}


def build_transition_envelope(
    *,
    transition_kind: Literal["start", "lesson_answer", "exit_ticket_answer", "recovery_resume"],
    before: Any,
    command: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TRANSITION_SCHEMA_VERSION,
        "transition_id": f"shadow_{uuid4().hex}",
        "transition_kind": transition_kind,
        "before": _dump(before),
        "command": copy.deepcopy(command or {}),
        "observations": copy.deepcopy(observations or {}),
    }


def compare_shadow_projection(
    legacy_projection: dict[str, Any],
    graph_projection: dict[str, Any],
    *,
    diagnostics: list[str] | None = None,
) -> list[str]:
    reasons = list(dict.fromkeys(diagnostics or []))
    for reason in parity_mismatch_reasons(legacy_projection, graph_projection):
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def _attempt_counts(ports: DenyShadowPorts) -> tuple[int, int]:
    external = sum(ports.attempts.get(key, 0) for key in ("model", "retrieval", "tool", "network"))
    side_effects = sum(value for key, value in ports.attempts.items() if key not in {"model", "retrieval", "tool", "network"})
    return external, side_effects


def run_autotutor_shadow_transition(
    envelope: dict[str, Any],
    legacy_after: Any,
    *,
    ports: DenyShadowPorts | None = None,
) -> AutoTutorShadowResult:
    """Compute Graph candidate from before/command/observations, then compare after."""
    from agents.autotutor_graph import AUTOTUTOR_SHADOW_GRAPH

    started = perf_counter()
    ports = ports or DenyShadowPorts()
    kind = str(envelope.get("transition_kind") or "unknown")
    diagnostics: list[str] = []
    if _FORBIDDEN_ENVELOPE_KEYS.intersection(envelope):
        diagnostics.append("shadow_expected_state_forbidden")
    try:
        result = AUTOTUTOR_SHADOW_GRAPH.invoke(
            {
                "schema_version": TRANSITION_SCHEMA_VERSION,
                "envelope": copy.deepcopy(envelope),
                "ports": ports,
                "diagnostics": diagnostics,
            },
            config={
                "callbacks": [],
                "recursion_limit": 30,
                "configurable": {"thread_id": str(envelope.get("transition_id") or "shadow")},
            },
        )
        graph_projection = result.get("canonical") if isinstance(result, dict) else None
        diagnostics = list(result.get("diagnostics") or []) if isinstance(result, dict) else ["shadow_execution_failed"]
        if not isinstance(graph_projection, dict):
            graph_projection = {}
            diagnostics.append("shadow_execution_failed")
        visited = tuple(str(node) for node in (result.get("visited_nodes") or [])) if isinstance(result, dict) else ()
    except ShadowSideEffectForbidden as exc:
        code = "shadow_external_call_attempted" if "external_call" in str(exc) else "shadow_side_effect_attempted"
        diagnostics = [code]
        graph_projection = {}
        visited = ()
    except Exception as exc:
        logger.warning("autotutor_langgraph_shadow_failed error_type=%s", exc.__class__.__name__)
        diagnostics = ["shadow_execution_failed"]
        graph_projection = {}
        visited = ()
    duration_ms = round((perf_counter() - started) * 1000, 3)
    if duration_ms > shadow_timeout_ms() and "shadow_timeout" not in diagnostics:
        diagnostics.append("shadow_timeout")
    legacy_projection = canonical_autotutor_projection(legacy_after)
    reasons = compare_shadow_projection(legacy_projection, graph_projection, diagnostics=diagnostics)
    external, side_effects = _attempt_counts(ports)
    if external and "shadow_external_call_attempted" not in reasons:
        reasons.append("shadow_external_call_attempted")
    if side_effects and "shadow_side_effect_attempted" not in reasons:
        reasons.append("shadow_side_effect_attempted")
    result_value = AutoTutorShadowResult(
        matched=not reasons,
        reason_codes=tuple(reasons),
        visited_nodes=visited,
        config_version=shadow_config_version(),
        transition_kind=kind,
        duration_ms=duration_ms,
        external_call_attempts=external,
        side_effect_attempts=side_effects,
    )
    with _METRICS_LOCK:
        _METRICS.append({
            "transition_kind": kind,
            "matched": result_value.matched,
            "reason_codes": list(result_value.reason_codes),
            "duration_ms": duration_ms,
            "external_call_attempts": external,
            "side_effect_attempts": side_effects,
            "config_version": result_value.config_version,
        })
    return result_value


def run_autotutor_shadow(_state: Any) -> AutoTutorShadowResult:
    """Reject the old same-terminal-state parity mode instead of self-attesting."""
    return AutoTutorShadowResult(
        matched=False,
        reason_codes=("shadow_input_incomplete",),
        visited_nodes=(),
        config_version=shadow_config_version(),
    )


def maybe_run_autotutor_shadow_transition(envelope: dict[str, Any], legacy_after: Any) -> AutoTutorShadowResult | None:
    if not shadow_enabled():
        return None
    result = run_autotutor_shadow_transition(envelope, legacy_after)
    logger.info(
        "autotutor_langgraph_shadow kind=%s matched=%s reasons=%s visited=%s duration_ms=%.3f config_version=%s",
        result.transition_kind,
        result.matched,
        ",".join(result.reason_codes) or "none",
        len(result.visited_nodes),
        result.duration_ms,
        result.config_version,
    )
    return result


def maybe_run_autotutor_shadow(state: Any) -> AutoTutorShadowResult | None:
    """Backward-compatible entry point; old terminal-state replay is intentionally disabled."""
    if not shadow_enabled():
        return None
    return run_autotutor_shadow(state)


def shadow_metrics_snapshot(*, clear: bool = False) -> list[dict[str, Any]]:
    with _METRICS_LOCK:
        values = [copy.deepcopy(item) for item in _METRICS]
        if clear:
            _METRICS.clear()
    return values


def record_shadow_metric(
    *,
    transition_kind: str,
    matched: bool,
    duration_ms: float,
    reason_codes: list[str] | tuple[str, ...] = (),
) -> None:
    """Compatibility evidence sink for the v1.49 pre-commit full-outcome Shadow."""
    with _METRICS_LOCK:
        _METRICS.append({
            "transition_kind": transition_kind,
            "matched": matched,
            "reason_codes": list(reason_codes),
            "duration_ms": round(max(0.0, duration_ms), 3),
            "external_call_attempts": 0,
            "side_effect_attempts": 0,
            "config_version": shadow_config_version(),
        })
