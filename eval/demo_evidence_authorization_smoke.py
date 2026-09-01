"""Allowlist and authorization contract for session-level AutoTutor evidence."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-demo-evidence-auth.sqlite3"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
os.environ["EDU_AGENT_DB_PATH"] = str(DB_PATH)
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_evidence import project_autotutor_evidence  # noqa: E402
from api.routers.learning import autotutor_get_evidence  # noqa: E402
from security.auth import Actor  # noqa: E402

STATE = {
    "session_id": "at_evidence",
    "student_id": "pilot-student",
    "status": "completed",
    "lesson_plan": [{"knowledge_point": "洋务运动目的", "correct_answer": "A"}],
    "replans": 1,
    "reflect_log": [{
        "diagnosis": "raw private diagnosis",
        "prompt": "secret",
        "decision_provenance": {
            "decision_source": "deterministic_fallback",
            "fallback_used": True,
            "request_id": "request-secret",
        },
    }],
    "exit_ticket_result": {
        "knowledge_point": "洋务运动目的",
        "is_correct": True,
        "selected_answer": "A",
        "correct_answer": "A",
        "explanation": "private answer explanation",
    },
    "mastery": {"status": "verified", "raw_score": 1.0},
    "evidence": {
        "exit_ticket_recorded": True,
        "weakpoint_action": "verified_correct_evidence_recorded",
        "tutor_effectiveness_ready": True,
        "database_url": "postgres://secret",
    },
    "trace_id": "trace-secret",
    "run_id": "run-secret",
}


async def expect_forbidden(actor: Actor) -> None:
    try:
        await autotutor_get_evidence("at_evidence", actor)
    except HTTPException as exc:
        assert exc.status_code == 403, exc
        return
    raise AssertionError("expected 403")


async def run() -> None:
    projected = project_autotutor_evidence(STATE)
    assert projected["replans"] == 1 and projected["reflection_count"] == 1, projected
    assert projected["exit_ticket"]["passed"] is True, projected
    assert projected["mastery"]["status"] == "verified", projected
    assert projected["decision_provenance"]["deterministic_fallback_used"] is True, projected
    assert projected["decision_provenance"]["llm_decision_succeeded"] is False, projected
    serialized = json.dumps(projected, ensure_ascii=False).lower()
    for forbidden in (
        "correct_answer", "selected_answer", "private answer", "raw private",
        "prompt", "database_url", "postgres://", "trace-secret", "run-secret", "request_id", "request-secret",
    ):
        assert forbidden not in serialized, serialized

    with patch("agents.auto_tutor.get_session", return_value=STATE):
        owner = await autotutor_get_evidence(
            "at_evidence", Actor(actor_id="pilot-student", role="student", traffic_cohort="demo")
        )
        assert owner["session_id"] == "at_evidence", owner

        with patch("security.auth.teacher_has_student_access", return_value=True):
            teacher = await autotutor_get_evidence(
                "at_evidence", Actor(actor_id="pilot-teacher", role="teacher", traffic_cohort="demo")
            )
            assert teacher["student_id"] == "pilot-student", teacher

        with patch("security.auth.teacher_has_student_access", return_value=False):
            await expect_forbidden(Actor(actor_id="other-teacher", role="teacher"))

        await expect_forbidden(Actor(actor_id="other-student", role="student"))
        admin = await autotutor_get_evidence(
            "at_evidence", Actor(actor_id="admin", role="admin", traffic_cohort="operator")
        )
        assert admin["evidence"]["tutor_effectiveness_ready"] is True, admin

    with patch("agents.auto_tutor.get_session", side_effect=LookupError):
        try:
            await autotutor_get_evidence("missing", Actor(actor_id="admin", role="admin"))
        except HTTPException as exc:
            assert exc.status_code == 404, exc
        else:
            raise AssertionError("expected 404")
    print("demo_evidence_authorization_smoke=PASS")


if __name__ == "__main__":
    asyncio.run(run())
