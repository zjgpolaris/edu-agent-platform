"""Authorization contract for the AutoTutor demo-trace endpoint."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-demo-trace-auth.sqlite3"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
os.environ["EDU_AGENT_DB_PATH"] = str(DB_PATH)
sys.path.insert(0, str(ROOT / "backend"))

from api.routers.learning import autotutor_get_demo_trace  # noqa: E402
from security.auth import Actor  # noqa: E402

STATE = {
    "session_id": "at_owner",
    "student_id": "pilot-student",
    "status": "awaiting_answer",
    "runtime_steps": [{"sequence": 1, "event_type": "plan", "status": "success", "metadata": {"targeted_points": ["洋务运动目的"]}}],
}


async def expect_forbidden(actor: Actor) -> None:
    try:
        await autotutor_get_demo_trace("at_owner", actor)
    except HTTPException as exc:
        assert exc.status_code == 403, exc
        return
    raise AssertionError("expected 403")


async def run() -> None:
    with patch("agents.auto_tutor.get_session", return_value=STATE):
        owner = await autotutor_get_demo_trace(
            "at_owner",
            Actor(actor_id="pilot-student", role="student", traffic_cohort="demo"),
        )
        assert owner["enabled"] is True and len(owner["events"]) == 1, owner
        admin = await autotutor_get_demo_trace(
            "at_owner",
            Actor(actor_id="admin", role="admin", traffic_cohort="operator"),
        )
        assert admin["session_id"] == "at_owner", admin
        with patch(
            "security.accounts.get_account",
            return_value={"account_status": "active", "traffic_cohort": "demo"},
        ):
            local_demo_owner = await autotutor_get_demo_trace(
                "at_owner",
                Actor(actor_id="pilot-student", role="student", traffic_cohort="unverified"),
            )
            assert local_demo_owner["enabled"] is True, local_demo_owner
        await expect_forbidden(Actor(actor_id="other", role="student", traffic_cohort="demo"))
        with patch("security.accounts.get_account", return_value=None):
            await expect_forbidden(Actor(actor_id="pilot-student", role="student", traffic_cohort="unverified"))
        await expect_forbidden(Actor(actor_id="pilot-teacher", role="teacher", traffic_cohort="demo"))
    print("demo_trace_authorization_smoke=PASS")


if __name__ == "__main__":
    asyncio.run(run())
