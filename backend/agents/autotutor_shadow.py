"""AutoTutor LangGraph shadow execution and parity comparison."""
from __future__ import annotations

import copy
import logging
import os
from dataclasses import dataclass
from typing import Any

from agents.autotutor_domain import canonical_autotutor_projection, parity_mismatch_reasons


logger = logging.getLogger(__name__)
_TRUE = {"1", "true", "yes", "on"}


class ShadowSideEffectForbidden(RuntimeError):
    pass


class DenyShadowEffects:
    """Explicit sink used by shadow nodes and tests to reject writes."""

    def __getattr__(self, operation: str):
        def forbidden(*_args: Any, **_kwargs: Any):
            raise ShadowSideEffectForbidden(f"shadow_side_effect_forbidden:{operation}")

        return forbidden


@dataclass(frozen=True)
class AutoTutorShadowResult:
    matched: bool
    reason_codes: tuple[str, ...]
    visited_nodes: tuple[str, ...]
    config_version: str


def shadow_enabled() -> bool:
    return os.getenv("EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED", "").strip().lower() in _TRUE


def shadow_config_version() -> str:
    return os.getenv("EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_CONFIG_VERSION", "v1.48-shadow").strip() or "v1.48-shadow"


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


def run_autotutor_shadow(state: Any) -> AutoTutorShadowResult:
    """Replay one captured active state without model, tool, database or trace writes."""
    from agents.autotutor_graph import AUTOTUTOR_SHADOW_GRAPH

    if hasattr(state, "model_dump"):
        captured = state.model_dump(mode="json")
    elif isinstance(state, dict):
        captured = copy.deepcopy(state)
    else:
        raise TypeError("shadow_input_incomplete")
    legacy_projection = canonical_autotutor_projection(captured)
    try:
        result = AUTOTUTOR_SHADOW_GRAPH.invoke(
            {
                "schema_version": "v1.48-shadow",
                "legacy_state": copy.deepcopy(captured),
                "diagnostics": [],
            },
            config={
                "callbacks": [],
                "recursion_limit": 100,
                "configurable": {"thread_id": f"shadow:{captured.get('session_id') or 'unknown'}"},
            },
        )
        graph_projection = result.get("canonical") if isinstance(result, dict) else None
        diagnostics = list(result.get("diagnostics") or []) if isinstance(result, dict) else ["shadow_execution_failed"]
        if not isinstance(graph_projection, dict):
            graph_projection = {}
            diagnostics.append("shadow_execution_failed")
        reasons = compare_shadow_projection(legacy_projection, graph_projection, diagnostics=diagnostics)
        visited = tuple(str(node) for node in (result.get("visited_nodes") or [])) if isinstance(result, dict) else ()
    except Exception as exc:
        logger.warning("autotutor_langgraph_shadow_failed error_type=%s", exc.__class__.__name__)
        reasons = ["shadow_execution_failed"]
        visited = ()
    return AutoTutorShadowResult(
        matched=not reasons,
        reason_codes=tuple(reasons),
        visited_nodes=visited,
        config_version=shadow_config_version(),
    )


def maybe_run_autotutor_shadow(state: Any) -> AutoTutorShadowResult | None:
    if not shadow_enabled():
        return None
    result = run_autotutor_shadow(state)
    logger.info(
        "autotutor_langgraph_shadow matched=%s reasons=%s visited=%s config_version=%s",
        result.matched,
        ",".join(result.reason_codes) or "none",
        len(result.visited_nodes),
        result.config_version,
    )
    return result
