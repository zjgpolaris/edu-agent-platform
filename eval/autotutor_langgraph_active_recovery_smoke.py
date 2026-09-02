"""A restarted process restores the sticky Graph executor from session state."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-active-recovery.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents import auto_tutor as at  # noqa: E402


def main() -> None:
    started = at.start_session(
        "active-recovery-student",
        actor_id="active-recovery-student",
        actor_role="student",
        account_status="active",
        traffic_cohort="verified",
        rollout_eligible=True,
        eligibility_reason="verified_runtime_actor",
        internal_force_graph=True,
    )
    with at._store._lock:
        at._store._sessions.clear()
        at._store._timestamps.clear()
    restored = at._store.get(started["session_id"])
    assert restored is not None
    assert restored.executor_mode == "graph_active"
    answer = str(restored.lesson_plan[restored.current_step_index].question["answer"])
    result = at.submit_answer(
        restored.session_id,
        answer,
        actor_id=restored.student_id,
        actor_role="student",
        account_status="active",
        traffic_cohort="verified",
        rollout_eligible=True,
        eligibility_reason="verified_runtime_actor",
        expected_revision=restored.revision,
        idempotency_key="active-recovery-answer",
    )
    assert result["revision"] == restored.revision + 1
    persisted = at._load_persisted_session(restored.session_id)
    assert persisted is not None and persisted.executor_mode == "graph_active"
    print("autotutor_langgraph_active_recovery_smoke=PASS")


if __name__ == "__main__":
    main()
