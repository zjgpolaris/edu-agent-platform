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

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-autotutor-resume-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_CONFIG_VERSION"] = "autotutor-resume-test"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_AUTOTUTOR_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED"] = "true"

from agent_runtime.checkpoint_store import latest_checkpoint  # noqa: E402
from agent_runtime.event_store import get_run, list_run_events  # noqa: E402
from agent_runtime.models import ResumeSignal  # noqa: E402
from agent_runtime.resume_registry import dispatch_resume  # noqa: E402
from agents.auto_tutor import _load_persisted_session, start_session  # noqa: E402
from security.auth import Actor  # noqa: E402


def main() -> None:
    started = start_session(
        "student-autotutor-runtime",
        grade="八年级上册",
        actor_id="student-autotutor-runtime",
        actor_role="student",
        idempotency_key="autotutor-runtime-start-0001",
    )
    run_id = str(started["run_id"])
    run = get_run(run_id)
    assert run["status"] == "waiting_input", run
    checkpoint = latest_checkpoint(run_id)
    assert checkpoint and checkpoint["revision"] == run["revision"]
    assert checkpoint["state"]["question_sha256"]
    assert "question" not in checkpoint["state"]
    initial_events = list_run_events(run_id)
    assert any(event.event == "autotutor_milestone" for event in initial_events)

    internal = _load_persisted_session(started["session_id"])
    assert internal is not None
    answer = str((internal.lesson_plan[internal.current_step_index].question or {}).get("answer") or "A")
    result = asyncio.run(dispatch_resume(
        run,
        ResumeSignal(
            expected_revision=run["revision"],
            kind="input",
            correlation_key="autotutor-runtime-answer-0001",
            input_patch={"answer": answer},
        ),
        Actor(actor_id="student-autotutor-runtime", role="student"),
    ))
    assert result["revision"] == started["revision"] + 1
    current = get_run(run_id)
    assert current["status"] in {"waiting_input", "completed"}, current
    checkpoint = latest_checkpoint(run_id)
    assert checkpoint and checkpoint["revision"] <= current["revision"]

    try:
        asyncio.run(dispatch_resume(
            current,
            ResumeSignal(
                expected_revision=run["revision"],
                kind="input",
                correlation_key="autotutor-runtime-answer-stale",
                input_patch={"answer": answer},
            ),
            Actor(actor_id="student-autotutor-runtime", role="student"),
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("stale AutoTutor resume was accepted")

    for index in range(1, 10):
        if current["status"] == "completed":
            break
        internal = _load_persisted_session(started["session_id"])
        assert internal is not None
        if internal.phase == "exit_ticket" and internal.exit_ticket:
            answer = str(internal.exit_ticket.question.get("answer") or "A")
        else:
            answer = str((internal.lesson_plan[internal.current_step_index].question or {}).get("answer") or "A")
        asyncio.run(dispatch_resume(
            current,
            ResumeSignal(
                expected_revision=current["revision"],
                kind="input",
                correlation_key=f"autotutor-runtime-answer-{index + 1:04d}",
                input_patch={"answer": answer},
            ),
            Actor(actor_id="student-autotutor-runtime", role="student"),
        ))
        current = get_run(run_id)
    assert current["status"] == "completed", current
    checkpoint = latest_checkpoint(run_id)
    assert checkpoint and checkpoint["node_name"] == "finalize"
    assert checkpoint["side_effect_ledger"]
    assert all(item["status"] == "committed" for item in checkpoint["side_effect_ledger"])

    events = list_run_events(run_id, limit=500)
    sequences = [event.sequence for event in events]
    assert sequences == sorted(set(sequences))
    milestone_types = {
        str(event.data.get("event_type"))
        for event in events
        if event.event == "autotutor_milestone"
    }
    assert {"plan", "act", "judge", "exit_ticket", "memory"} <= milestone_types, milestone_types
    persisted = " ".join(str(event.data) for event in events)
    assert "correct_answer" not in persisted
    assert "selected_answer" not in persisted

    print("agent_runtime_autotutor_resume_smoke=PASS")


if __name__ == "__main__":
    main()
