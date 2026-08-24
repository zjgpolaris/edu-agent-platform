from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-recovery-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass

from fastapi import HTTPException
from agents.auto_tutor import get_latest_session, get_session, start_session
from api.routers.learning import AutoTutorAnswerRequest, autotutor_submit_answer
from security.auth import Actor


def main() -> None:
    started = start_session("demo-student", grade="八年级上册")
    session_id = started["session_id"]

    latest = get_latest_session("demo-student")
    assert latest["session_id"] == session_id
    assert latest["status"] == "awaiting_answer"
    assert latest["current_question"] is not None

    loaded = get_session(session_id)
    assert loaded["session_id"] == session_id
    assert loaded["current_question"] is not None

    # The answer endpoint must authorize against the stored session owner even
    # when the optional client-supplied student_id is omitted.
    request = AutoTutorAnswerRequest(
        session_id=session_id,
        answer="A",
        expected_revision=loaded["revision"],
    )
    try:
        asyncio.run(autotutor_submit_answer(request, Actor(actor_id="other-student", role="student")))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-student answer was not rejected")

    answered = asyncio.run(autotutor_submit_answer(request, Actor(actor_id="demo-student", role="student")))
    assert answered["revision"] == loaded["revision"] + 1
    attempts_after_first = sum(step["attempts"] for step in answered["lesson_plan"])

    # Replaying the same optimistic revision and payload must return the stored
    # transition response without judging a second question.
    replayed = asyncio.run(autotutor_submit_answer(request, Actor(actor_id="demo-student", role="student")))
    assert replayed.get("idempotent_replay") is True
    assert sum(step["attempts"] for step in replayed["lesson_plan"]) == attempts_after_first
    print("autotutor_session_recovery_smoke=PASS")


if __name__ == "__main__":
    main()
