"""Smoke: AutoTutor -> free-question handoff is owner-safe and state-neutral."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-handoff.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from agents.auto_tutor import get_session, start_session
from api.routers.learning import (
    LearningAssistantSessionCreateRequest,
    learning_assistant_create_session,
    learning_assistant_return_to_source,
)
from security.auth import Actor
from student_profile import list_learning_events


def _state_signature(state: dict) -> tuple:
    return (
        state["revision"],
        state["phase"],
        state["current_step_index"],
        tuple(step["attempts"] for step in state["lesson_plan"]),
        (state.get("current_question") or {}).get("question"),
    )


def main() -> None:
    student_id = "handoff-student"
    started = start_session(student_id, grade="八年级上册", focus_tags=["洋务运动"])
    before = get_session(started["session_id"])
    req = LearningAssistantSessionCreateRequest(
        student_id=student_id,
        source_feature="auto_tutor",
        source_session_id=started["session_id"],
    )
    created = asyncio.run(learning_assistant_create_session(req, Actor(actor_id=student_id, role="student")))
    context = created["context"]
    serialized = str(context).lower()
    assert context["knowledge_point"]
    assert context["autotutor_session_id"] == started["session_id"]
    assert "correct_answer" not in serialized
    assert "'answer'" not in serialized and '"answer"' not in serialized
    assert _state_signature(get_session(started["session_id"])) == _state_signature(before)

    resumed = asyncio.run(learning_assistant_create_session(req, Actor(actor_id=student_id, role="student")))
    assert resumed["session_id"] == created["session_id"]
    assert resumed["messages"] == []
    assert _state_signature(get_session(started["session_id"])) == _state_signature(before)

    returned = asyncio.run(learning_assistant_return_to_source(created["session_id"], Actor(actor_id=student_id, role="student")))
    assert returned["return_path"] == "/student/auto-tutor"
    return_events = list_learning_events(student_id=student_id, feature="auto_tutor", event_type="autotutor_question_returned")
    assert len(return_events) == 1
    assert return_events[0]["metadata"]["assistant_session_id"] == created["session_id"]
    assert _state_signature(get_session(started["session_id"])) == _state_signature(before)

    try:
        asyncio.run(learning_assistant_return_to_source(created["session_id"], Actor(actor_id="other-student", role="student")))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-student return telemetry was not rejected")

    try:
        asyncio.run(learning_assistant_create_session(req, Actor(actor_id="other-student", role="student")))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-student AutoTutor handoff was not rejected")
    print("autotutor_question_handoff_smoke=PASS")


if __name__ == "__main__":
    main()
