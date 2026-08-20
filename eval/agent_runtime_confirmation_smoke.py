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

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-confirmation-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS"] = "10000"

from agent_runtime.event_store import get_run  # noqa: E402
from agent_runtime.models import ResumeSignal  # noqa: E402
from agent_runtime.resume_registry import dispatch_resume  # noqa: E402
from agents.learning_assistant import stream_learning_assistant_events  # noqa: E402
from security.auth import Actor  # noqa: E402


def main() -> None:
    events = list(stream_learning_assistant_events({
        "message": "演示高风险工具，删除演示记忆",
        "student_id": "student-confirm",
        "actor_id": "student-confirm",
        "actor_role": "student",
        "session_id": "session-confirm",
        "trace_id": "trace-confirm",
        "idempotency_key": "runtime-confirmation-0001",
    }))
    tool_result = next(data for event, data in events if event == "tool_result")
    final = next(data for event, data in events if event == "final")
    token = str((tool_result.get("metadata") or {}).get("confirmation_token") or "")
    assert token.startswith("confirm_")
    run = get_run(str(final["run_id"]))
    assert run["status"] == "waiting_confirmation", run
    assert final["run_revision"] == run["revision"]

    rejected = asyncio.run(dispatch_resume(
        run,
        ResumeSignal(
            expected_revision=run["revision"],
            kind="confirmation",
            correlation_key="runtime-confirmation-resume-0001",
            confirmation_token=f"{token}-tampered",
        ),
        Actor(actor_id="student-confirm", role="student"),
    ))
    assert rejected["ok"] is False
    replacement_token = str(rejected.get("confirmation_token") or "")
    assert replacement_token.startswith("confirm_")
    run = get_run(run["run_id"])
    assert run["status"] == "waiting_confirmation"

    resumed = asyncio.run(dispatch_resume(
        run,
        ResumeSignal(
            expected_revision=run["revision"],
            kind="confirmation",
            correlation_key="runtime-confirmation-resume-0002",
            confirmation_token=replacement_token,
        ),
        Actor(actor_id="student-confirm", role="student"),
    ))
    assert resumed["ok"] is True, resumed
    assert resumed["tool_result"]["data"]["deleted"] is True
    assert get_run(run["run_id"])["status"] == "completed"

    print("agent_runtime_confirmation_smoke=PASS")


if __name__ == "__main__":
    main()
