"""Independent transition parity contract for the AutoTutor shadow graph."""
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
    build_transition_envelope,
    compare_shadow_projection,
    maybe_run_autotutor_shadow_transition,
    run_autotutor_shadow,
    run_autotutor_shadow_transition,
)


def _base_state() -> dict:
    return {
        "session_id": "private-session",
        "student_id": "private-student",
        "trace_id": "private-trace",
        "status": "awaiting_answer",
        "phase": "lesson",
        "current_step_index": 0,
        "replans": 0,
        "lesson_plan": [],
        "reflect_log": [],
        "verified_mastery": False,
        "content_gate_mode": "enforce",
    }


def _assert_transition(envelope: dict, expected_after: dict, required_nodes: set[str]) -> None:
    before_copy = copy.deepcopy(envelope["before"])
    after_copy = copy.deepcopy(expected_after)
    result = run_autotutor_shadow_transition(envelope, expected_after)
    assert result.matched, result
    assert not result.reason_codes, result
    assert required_nodes.issubset(set(result.visited_nodes)), result
    assert result.external_call_attempts == 0, result
    assert result.side_effect_attempts == 0, result
    assert envelope["before"] == before_copy, "shadow mutated captured before state"
    assert expected_after == after_copy, "shadow mutated committed Legacy state"
    assert "legacy_after" not in envelope and "expected_projection" not in envelope


def _start_case() -> None:
    before = _base_state()
    after = copy.deepcopy(before)
    after["lesson_plan"] = [{
        "knowledge_point": "洋务运动目的",
        "difficulty": "easy",
        "status": "active",
        "attempts": 0,
        "replanned": False,
        "question": {"assessment_id": "practice-1", "difficulty": "easy"},
    }]
    envelope = build_transition_envelope(
        transition_kind="start",
        before=before,
        observations={
            "plan": [{"knowledge_point": "洋务运动目的", "difficulty": "easy"}],
            "content": {"outcome": "verified", "assessment": {"assessment_id": "practice-1", "difficulty": "easy"}},
        },
    )
    _assert_transition(envelope, after, {"plan", "content_gate", "prepare_assessment", "wait_answer"})


def _replan_case() -> None:
    before = _base_state()
    before["lesson_plan"] = [{
        "knowledge_point": "洋务运动目的",
        "difficulty": "medium",
        "status": "active",
        "attempts": 0,
        "replanned": False,
        "question": {"assessment_id": "practice-1", "objective_id": "obj-1", "answer": "A"},
    }]
    after = copy.deepcopy(before)
    step = after["lesson_plan"][0]
    step.update({
        "difficulty": "easy",
        "status": "active",
        "attempts": 1,
        "replanned": True,
        "question": {"assessment_id": "practice-2", "objective_id": "obj-1", "difficulty": "easy"},
        "practice_result": {
            "assessment_id": "practice-1",
            "objective_id": "obj-1",
            "is_correct": False,
            "content_validation_status": "verified",
        },
    })
    after["replans"] = 1
    after["reflect_log"] = [{"adjustment": "reteach"}]
    envelope = build_transition_envelope(
        transition_kind="lesson_answer",
        before=before,
        command={"answer": "B"},
        observations={
            "reflection": {"adjustment": "reteach", "explanation": "先补讲基础史实"},
            "content": {"outcome": "verified", "assessment": {"assessment_id": "practice-2", "difficulty": "easy"}},
        },
    )
    _assert_transition(envelope, after, {"judge", "reflect", "re_plan", "prepare_assessment"})


def _exit_ticket_case() -> None:
    before = _base_state()
    before["phase"] = "exit_ticket"
    before["lesson_plan"] = [{
        "knowledge_point": "洋务运动目的",
        "difficulty": "easy",
        "status": "practiced",
        "attempts": 1,
        "replanned": False,
        "question": {"assessment_id": "practice-1"},
        "practice_result": {
            "assessment_id": "practice-1",
            "objective_id": "obj-1",
            "is_correct": True,
            "content_validation_status": "verified",
        },
    }]
    before["exit_ticket"] = {
        "knowledge_point": "洋务运动目的",
        "question": {"assessment_id": "exit-1", "objective_id": "obj-1", "answer": "B"},
        "content_validation": {"status": "verified"},
    }
    after = copy.deepcopy(before)
    after["status"] = "completed"
    after["phase"] = "completed"
    after["lesson_plan"][0]["status"] = "mastered"
    after["verified_mastery"] = True
    after["exit_ticket_result"] = {"is_correct": True, "verified_mastery": True}
    after["evidence"] = {
        "exit_ticket_recorded": True,
        "weakpoint_action": "independent_correct_evidence_recorded",
        "review_action": "no_new_review_needed",
    }
    envelope = build_transition_envelope(
        transition_kind="exit_ticket_answer",
        before=before,
        command={"answer": "B"},
    )
    _assert_transition(envelope, after, {"verify_exit_ticket", "build_evidence_intent", "finalize"})


def _content_blocked_case() -> None:
    before = _base_state()
    after = copy.deepcopy(before)
    after["status"] = "needs_content"
    after["phase"] = "content_blocked"
    after["lesson_plan"] = [{
        "knowledge_point": "未审定知识点",
        "difficulty": "medium",
        "status": "content_blocked",
        "attempts": 0,
        "replanned": False,
        "question": None,
    }]
    envelope = build_transition_envelope(
        transition_kind="start",
        before=before,
        observations={
            "plan": [{"knowledge_point": "未审定知识点", "difficulty": "medium"}],
            "content": {"outcome": "blocked"},
        },
    )
    _assert_transition(envelope, after, {"plan", "content_gate"})


def _exit_ticket_blocked_case() -> None:
    before = _base_state()
    before["lesson_plan"] = [{
        "knowledge_point": "未审定知识点",
        "difficulty": "medium",
        "status": "active",
        "attempts": 0,
        "replanned": False,
        "question": {"assessment_id": "practice-1", "objective_id": "obj-1", "answer": "A"},
    }]
    after = copy.deepcopy(before)
    after.update({"status": "needs_content", "phase": "content_blocked"})
    after["lesson_plan"][0].update({
        "status": "content_blocked",
        "attempts": 1,
        "question": None,
        "practice_result": {
            "assessment_id": "practice-1",
            "objective_id": "obj-1",
            "is_correct": True,
            "content_validation_status": "verified",
        },
    })
    envelope = build_transition_envelope(
        transition_kind="lesson_answer",
        before=before,
        command={"answer": "A"},
        observations={"advance": {"outcome": "blocked"}},
    )
    _assert_transition(envelope, after, {"judge", "advance", "content_gate"})


def _false_mastery_case() -> None:
    before = _base_state()
    before["phase"] = "exit_ticket"
    before["lesson_plan"] = [{
        "knowledge_point": "洋务运动目的",
        "difficulty": "easy",
        "status": "practiced",
        "attempts": 1,
        "replanned": False,
        "question": {"assessment_id": "practice-1"},
        "practice_result": {
            "assessment_id": "practice-1",
            "objective_id": "obj-1",
            "is_correct": False,
            "content_validation_status": "verified",
        },
    }]
    before["exit_ticket"] = {
        "knowledge_point": "洋务运动目的",
        "question": {"assessment_id": "exit-1", "objective_id": "obj-1", "answer": "B"},
        "content_validation": {"status": "verified"},
    }
    after = copy.deepcopy(before)
    after.update({
        "status": "completed",
        "phase": "completed",
        "verified_mastery": False,
        "exit_ticket_result": {"is_correct": True, "verified_mastery": False},
        "evidence": {
            "exit_ticket_recorded": True,
            "weakpoint_action": "not_recorded",
            "review_action": "no_new_review_needed",
        },
    })
    envelope = build_transition_envelope(
        transition_kind="exit_ticket_answer",
        before=before,
        command={"answer": "B"},
    )
    _assert_transition(envelope, after, {"verify_exit_ticket", "finalize"})


def _recovery_case() -> None:
    before = _base_state()
    before["lesson_plan"] = [{
        "knowledge_point": "洋务运动目的",
        "difficulty": "easy",
        "status": "active",
        "attempts": 0,
        "replanned": False,
        "question": {"assessment_id": "practice-1"},
    }]
    envelope = build_transition_envelope(
        transition_kind="recovery_resume",
        before=before,
    )
    _assert_transition(envelope, before, {"recovery_resume"})


def main() -> None:
    _start_case()
    _replan_case()
    _exit_ticket_case()
    _content_blocked_case()
    _exit_ticket_blocked_case()
    _false_mastery_case()
    _recovery_case()

    legacy = canonical_autotutor_projection(_base_state())
    altered = copy.deepcopy(legacy)
    altered["next_action"] = "finalize"
    assert compare_shadow_projection(legacy, altered) == ["next_action_mismatch"]

    try:
        DenyShadowEffects().save({"must": "never persist"})
    except ShadowSideEffectForbidden as exc:
        assert str(exc) == "shadow_side_effect_forbidden:session_store"
    else:
        raise AssertionError("shadow effect sink unexpectedly accepted a write")

    rejected = run_autotutor_shadow(_base_state())
    assert rejected.reason_codes == ("shadow_input_incomplete",), rejected

    envelope = build_transition_envelope(
        transition_kind="recovery_resume",
        before=_base_state(),
    )
    with patch("agents.autotutor_graph.AUTOTUTOR_SHADOW_GRAPH.invoke", side_effect=RuntimeError("secret failure")):
        failed = run_autotutor_shadow_transition(envelope, _base_state())
    assert "shadow_execution_failed" in failed.reason_codes, failed
    assert "secret" not in json.dumps(failed.__dict__).lower(), failed

    with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_LANGGRAPH_SHADOW_ENABLED": "false"}):
        assert maybe_run_autotutor_shadow_transition(envelope, _base_state()) is None
    print("autotutor_langgraph_shadow_parity_smoke=PASS")


if __name__ == "__main__":
    main()
