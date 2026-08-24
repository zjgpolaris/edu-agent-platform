"""API contract smoke for safe content-blocked sessions and kill switch."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-content-blocked-api.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from api.routers.learning import AutoTutorStartRequest, autotutor_start_session
from security.auth import Actor


def main() -> None:
    student_id = "blocked-api-student"
    response = asyncio.run(autotutor_start_session(
        AutoTutorStartRequest(
            student_id=student_id,
            grade="八年级上册",
            focus_tags=["长平之战逐日行军路线"],
            lesson_id="lesson-unknown",
            max_minutes=10,
        ),
        Actor(actor_id=student_id, role="student"),
    ))
    assert response["status"] == "needs_content"
    assert response["phase"] == "content_blocked"
    assert response["current_question"] is None
    assert "不会改变" in response["content_blocked"]["message"]
    assert "reason" not in response["content_blocked"]
    assert "source_ids" not in str(response)

    os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_KILL_SWITCH"] = "true"
    try:
        asyncio.run(autotutor_start_session(
            AutoTutorStartRequest(student_id=student_id, focus_tags=["鸦片战争影响"]),
            Actor(actor_id=student_id, role="student"),
        ))
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("kill switch did not block a new session")
    print("autotutor_content_blocked_api_smoke=PASS")


if __name__ == "__main__":
    main()
