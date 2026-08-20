from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-recovery-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from sqlalchemy import text  # noqa: E402
from agent_runtime.event_store import append_run_event, create_run, get_run  # noqa: E402
from agent_runtime.models import AgentContext  # noqa: E402
from agent_runtime.recovery import recover_stale_runs  # noqa: E402
from db.engine import get_connection  # noqa: E402


def make_context(run_id: str, mode: str) -> AgentContext:
    return AgentContext(
        run_id=run_id,
        agent_type="test_agent",
        actor_id="student-r",
        actor_role="student",
        student_id="student-r",
        trace_id=f"trace-{run_id}",
        durability_mode=mode,
        config_version="recovery-test",
    )


def start_running(run_id: str, mode: str) -> None:
    create_run(make_context(run_id, mode), objective="recovery")
    append_run_event(run_id, expected_revision=0, event_type="route_decided", next_status="routed")
    append_run_event(run_id, expected_revision=1, event_type="plan_created", next_status="planned")
    append_run_event(run_id, expected_revision=2, event_type="step_started", next_status="running")
    with get_connection() as conn:
        conn.execute(text("UPDATE agent_runs SET updated_at='2000-01-01T00:00:00+00:00' WHERE run_id=:run_id"), {"run_id": run_id})


def main() -> None:
    start_running("run_observable_recovery", "observable")
    start_running("run_resumable_recovery", "resumable")
    result = recover_stale_runs(updated_before="2001-01-01T00:00:00+00:00")
    assert result["failed"] == 1, result
    assert result["awaiting_resume"] == 1, result
    assert get_run("run_observable_recovery")["status"] == "failed"
    assert get_run("run_resumable_recovery")["status"] == "running"
    print("agent_runtime_recovery_smoke=PASS")


if __name__ == "__main__":
    main()
