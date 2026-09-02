"""Forced Graph transitions use the existing CAS/effect transaction exactly once."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-active-transaction.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
os.environ["EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE"] = "legacy"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents.auto_tutor import _load_persisted_session, start_session, submit_answer  # noqa: E402
from agents.autotutor_execution import AutoTutorObservationBundle  # noqa: E402
from db.engine import get_connection  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _answer(session_id: str) -> str:
    state = _load_persisted_session(session_id)
    assert state is not None
    if state.phase == "exit_ticket":
        assert state.exit_ticket is not None
        return str(state.exit_ticket.question["answer"])
    return str(state.lesson_plan[state.current_step_index].question["answer"])


def main() -> None:
    before = {"revision": 0}
    bundle = AutoTutorObservationBundle(
        transition_id="immutability-smoke",
        transition_kind="start",
        command={},
    )
    try:
        bundle.command = {"bad": True}  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("observation bundle must be immutable")
    assert before == {"revision": 0}

    started = start_session(
        "active-transition-student",
        grade="八年级上册",
        focus_tags=["洋务运动目的"],
        actor_id="active-transition-student",
        actor_role="student",
        account_status="active",
        traffic_cohort="verified",
        rollout_eligible=True,
        eligibility_reason="verified_runtime_actor",
        internal_force_graph=True,
        idempotency_key="active-start-key",
    )
    state = _load_persisted_session(started["session_id"])
    assert state is not None and state.executor_mode == "graph_active"
    practice = submit_answer(
        state.session_id,
        _answer(state.session_id),
        actor_id=state.student_id,
        actor_role="student",
        account_status="active",
        traffic_cohort="verified",
        rollout_eligible=True,
        eligibility_reason="verified_runtime_actor",
        expected_revision=started["revision"],
        idempotency_key="active-practice-key",
    )
    assert practice["phase"] == "exit_ticket"
    persisted = _load_persisted_session(state.session_id)
    assert persisted is not None and persisted.executor_mode == "graph_active"
    exit_answer = _answer(state.session_id)
    completed = submit_answer(
        state.session_id,
        exit_answer,
        actor_id=state.student_id,
        actor_role="student",
        account_status="active",
        traffic_cohort="verified",
        rollout_eligible=True,
        eligibility_reason="verified_runtime_actor",
        expected_revision=practice["revision"],
        idempotency_key="active-exit-key",
    )
    assert completed["status"] == "completed"
    replay = submit_answer(
        state.session_id,
        exit_answer,
        expected_revision=practice["revision"],
        idempotency_key="active-exit-key",
    )
    assert replay["idempotent_replay"] is True
    with get_connection() as conn:
        duplicates = int(conn.execute(text("""SELECT COUNT(*) FROM (
            SELECT effect_key FROM learning_events WHERE session_id=:session_id
            AND effect_key IS NOT NULL GROUP BY effect_key HAVING COUNT(*) > 1
        ) duplicates"""), {"session_id": state.session_id}).scalar() or 0)
    assert duplicates == 0

    with patch("agents.autotutor_graph.execute_autotutor_active", side_effect=RuntimeError("forced")):
        fallback = start_session(
            "active-fallback-student",
            grade="八年级上册",
            focus_tags=["洋务运动目的"],
            actor_id="active-fallback-student",
            actor_role="student",
            account_status="active",
            traffic_cohort="verified",
            rollout_eligible=True,
            eligibility_reason="verified_runtime_actor",
            internal_force_graph=True,
            idempotency_key="active-fallback-start-key",
        )
    fallback_state = _load_persisted_session(fallback["session_id"])
    assert fallback_state is not None
    assert fallback_state.executor_mode == "legacy"
    assert str(fallback_state.executor_fallback_reason).startswith("graph_precommit_fallback")
    print("autotutor_langgraph_active_transaction_smoke=PASS")


if __name__ == "__main__":
    main()
