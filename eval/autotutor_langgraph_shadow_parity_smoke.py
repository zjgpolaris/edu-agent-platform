"""Deterministic parity and side-effect contract for the AutoTutor shadow graph."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_domain import canonical_autotutor_projection  # noqa: E402
from agents.autotutor_shadow import (  # noqa: E402
    DenyShadowEffects,
    ShadowSideEffectForbidden,
    compare_shadow_projection,
    maybe_run_autotutor_shadow,
    run_autotutor_shadow,
)


def _state(*, status: str, phase: str) -> dict:
    state = {
        "session_id": "at-shadow-secret-id",
        "student_id": "student-secret-id",
        "trace_id": "trace-secret-id",
        "status": status,
        "phase": phase,
        "current_step_index": 0,
        "replans": 1,
        "lesson_plan": [{
            "knowledge_point": "洋务运动目的",
            "difficulty": "easy",
            "status": "struggling" if phase == "lesson" else "mastered",
            "attempts": 1,
            "replanned": True,
            "question": {"assessment_id": "assessment-safe", "answer": "A", "prompt": "private"},
        }],
        "reflect_log": [{"adjustment": "reteach", "diagnosis": "private diagnosis"}],
        "runtime_steps": [
            {"step_id": "plan", "event_type": "plan"},
            {"step_id": "retrieve", "event_type": "tool_result"},
            {"step_id": "teach", "event_type": "teach"},
            {"step_id": "question", "event_type": "act"},
            {"step_id": "observe", "event_type": "observe"},
            {"step_id": "judge", "event_type": "judge"},
            {"step_id": "reflect", "event_type": "reflect"},
            {"step_id": "replan", "event_type": "re_plan"},
        ],
        "verified_mastery": False,
    }
    if phase == "content_blocked":
        state["runtime_steps"].append({"step_id": "gate", "event_type": "content_gate"})
    if phase in {"exit_ticket", "completed"}:
        state["exit_ticket"] = {"knowledge_point": "洋务运动目的", "question": {"answer": "B"}}
        state["runtime_steps"].append({"step_id": "exit_ticket_prepare", "event_type": "exit_ticket"})
    if phase == "completed":
        state["exit_ticket_result"] = {"is_correct": True, "selected_answer": "B", "correct_answer": "B"}
        state["verified_mastery"] = True
        state["evidence"] = {
            "exit_ticket_recorded": True,
            "weakpoint_action": "verified_correct_evidence_recorded",
            "review_action": "retention_scheduled",
        }
        state["runtime_steps"].extend([
            {"step_id": "exit_ticket_judge", "event_type": "exit_ticket"},
            {"step_id": "finalize", "event_type": "memory"},
        ])
    return state


def _assert_parity(state: dict) -> None:
    before = copy.deepcopy(state)
    result = run_autotutor_shadow(state)
    assert result.matched, result
    assert not result.reason_codes, result
    assert result.visited_nodes, result
    assert state == before, "shadow mutated captured active state"


def main() -> None:
    for status, phase in (
        ("awaiting_answer", "lesson"),
        ("needs_content", "content_blocked"),
        ("awaiting_answer", "exit_ticket"),
        ("completed", "completed"),
    ):
        _assert_parity(_state(status=status, phase=phase))

    legacy = canonical_autotutor_projection(_state(status="awaiting_answer", phase="lesson"))
    altered = copy.deepcopy(legacy)
    altered["next_action"] = "finalize"
    assert compare_shadow_projection(legacy, altered) == ["next_action_mismatch"]

    try:
        DenyShadowEffects().save({"must": "never persist"})
    except ShadowSideEffectForbidden as exc:
        assert str(exc) == "shadow_side_effect_forbidden:save"
    else:
        raise AssertionError("shadow effect sink unexpectedly accepted a write")

    state = _state(status="awaiting_answer", phase="lesson")
    with patch("agents.autotutor_graph.AUTOTUTOR_SHADOW_GRAPH.invoke", side_effect=RuntimeError("secret failure")):
        failed = run_autotutor_shadow(state)
    assert failed.reason_codes == ("shadow_execution_failed",), failed
    assert "secret" not in json.dumps(failed.__dict__).lower(), failed

    with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED": "false"}):
        assert maybe_run_autotutor_shadow(state) is None
    print("autotutor_langgraph_shadow_parity_smoke=PASS")


if __name__ == "__main__":
    main()
