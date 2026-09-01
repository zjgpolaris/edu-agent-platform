"""Allowlisted, session-level AutoTutor evidence for students and teachers."""
from __future__ import annotations

from typing import Any

from agents.autotutor_provenance import public_session_decision_summary


def _text(value: Any, *, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def project_autotutor_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Project public AutoTutor state into a bounded evidence-only contract."""
    lesson_plan = state.get("lesson_plan") if isinstance(state.get("lesson_plan"), list) else []
    knowledge_points: list[str] = []
    for item in lesson_plan:
        if not isinstance(item, dict):
            continue
        point = _text(item.get("knowledge_point"))
        if point and point not in knowledge_points:
            knowledge_points.append(point)

    reflections = state.get("reflect_log") if isinstance(state.get("reflect_log"), list) else []
    exit_result = state.get("exit_ticket_result") if isinstance(state.get("exit_ticket_result"), dict) else {}
    evidence = state.get("evidence") if isinstance(state.get("evidence"), dict) else {}
    mastery = state.get("mastery") if isinstance(state.get("mastery"), dict) else {}
    exit_point = _text(exit_result.get("knowledge_point"))

    return {
        "session_id": _text(state.get("session_id"), limit=128),
        "student_id": _text(state.get("student_id"), limit=128),
        "status": _text(state.get("status"), limit=40),
        "knowledge_points": knowledge_points[:8],
        "replans": max(0, int(state.get("replans") or 0)),
        "reflection_count": min(len(reflections), 100),
        "exit_ticket": {
            "recorded": bool(evidence.get("exit_ticket_recorded")),
            "knowledge_point": exit_point or (knowledge_points[0] if knowledge_points else ""),
            "passed": exit_result.get("is_correct") if isinstance(exit_result.get("is_correct"), bool) else None,
        },
        "mastery": {
            "status": "verified" if mastery.get("status") == "verified" else "not_yet_verified",
        },
        "evidence": {
            "learning_event_recorded": bool(evidence.get("exit_ticket_recorded")),
            "weakpoint_action": _text(evidence.get("weakpoint_action"), limit=80),
            "tutor_effectiveness_ready": bool(evidence.get("tutor_effectiveness_ready")),
        },
        "decision_provenance": public_session_decision_summary(state),
    }
