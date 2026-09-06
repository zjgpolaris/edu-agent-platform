"""Atomic persistence plus real Graph orchestration failure/recovery/idempotency."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="autotutor-atomic-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP.name}/test.sqlite3"
os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "a" * 40
os.environ["EDU_AGENT_ENVIRONMENT"] = "local"
os.environ["EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE"] = "legacy"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text
from db.schema import metadata
from db.engine import engine, get_connection
from agent_runtime.rollout_observations import RolloutObservationWriteError, observation_write_health
from autotutor_atomic_observation_checks import check_atomic_observation_transactions, reject_observation_insert
from agents import auto_tutor as at


def main():
    metadata.create_all(engine)
    check_atomic_observation_transactions()
    actor = dict(actor_id="atomic-actor", actor_role="student", account_status="active",
                 traffic_cohort="verified", rollout_eligible=True, eligibility_reason="verified_runtime_actor")
    from agents.autotutor_execution import AutoTutorExecutionContext
    control_context = AutoTutorExecutionContext(**actor, environment="production", deployed_commit="a" * 40)
    with patch.object(at, "_execution_context", return_value=control_context), reject_observation_insert():
        try:
            at.start_session("atomic-actor", focus_tags=["洋务运动目的"], idempotency_key="atomic-control-start", **actor)
            raise AssertionError("production Control committed without observation")
        except RolloutObservationWriteError:
            pass
    assert at._load_start_idempotent_session("atomic-actor", "atomic-control-start") is None
    start = dict(student_id="atomic-actor", grade="八年级上册", focus_tags=["洋务运动目的"],
                 internal_force_graph=True, idempotency_key="atomic-start", **actor)
    with reject_observation_insert(), patch("agents.autotutor_canary_admission.clear_autotutor_canary_admission_cache") as clear:
        try:
            at.start_session(**start)
            raise AssertionError("failed start returned a response")
        except RolloutObservationWriteError:
            pass
        clear.assert_called_once()
    assert at._load_start_idempotent_session("atomic-actor", "atomic-start") is None
    assert observation_write_health()["ok"] is False
    started = at.start_session(**start)
    state = at._load_persisted_session(started["session_id"])
    assert state.executor_mode == "graph_active"
    def snapshot():
        with get_connection() as conn:
            row = dict(conn.execute(text("SELECT * FROM autotutor_sessions WHERE session_id=:id"), {"id": state.session_id}).mappings().one())
            events = conn.execute(text("SELECT COUNT(*) FROM learning_events WHERE session_id=:id"), {"id": state.session_id}).scalar()
            obs = conn.execute(text("SELECT COUNT(*) FROM agent_rollout_observations WHERE trace_id=:id"), {"id": state.trace_id}).scalar()
            return row, events, obs
    before = snapshot()
    answer = str(state.lesson_plan[state.current_step_index].question["answer"])
    kwargs = dict(session_id=state.session_id, answer=answer, expected_revision=state.revision,
                  idempotency_key="atomic-answer", **actor)
    with reject_observation_insert():
        try:
            at.submit_answer(**kwargs)
            raise AssertionError("failed answer returned a response")
        except RolloutObservationWriteError:
            pass
    after = snapshot()
    # Claim cleanup may refresh updated_at; business state and response must not change.
    assert after[0]["inflight_idempotency_key"] is None
    for key in ("state_json", "revision", "last_response_json", "last_idempotency_key", "last_request_hash"):
        assert after[0][key] == before[0][key], key
    assert after[1:] == before[1:]
    assert at._store.get(state.session_id).revision == state.revision
    result = at.submit_answer(**kwargs)
    assert result["revision"] == state.revision + 1
    saved = snapshot()
    assert saved[2] == before[2] + 1
    with reject_observation_insert():
        assert at.submit_answer(**kwargs)["idempotent_replay"] is True
        assert at.start_session(**start)["idempotent_replay"] is True
    assert snapshot() == saved
    # The API returns a stable 503 code without DB details for either transition.
    import asyncio
    from fastapi import HTTPException
    from api.routers import learning
    from security.auth import Actor
    api_actor = Actor(actor_id="atomic-actor", role="student", traffic_cohort="verified")
    async def api_errors():
        for function, request, target in (
            (learning.autotutor_start_session, learning.AutoTutorStartRequest(student_id="atomic-actor"), "start_session"),
            (learning.autotutor_submit_answer, learning.AutoTutorAnswerRequest(session_id=state.session_id, answer="A"), "submit_answer"),
        ):
            with patch.object(at, target, side_effect=RolloutObservationWriteError(RuntimeError("private SQL params"), {})):
                try:
                    await function(request, actor=api_actor, verification_run_id=None, verification_attestation=None)
                    raise AssertionError("API did not fail closed")
                except HTTPException as exc:
                    assert exc.status_code == 503 and exc.detail == "autotutor_observation_write_failed"
    asyncio.run(api_errors())
    # Failure after COMMIT cannot undo business work. Keep a durable pending marker,
    # return the committed response and never re-execute the business transition.
    with patch("agent_runtime.rollout_observations.complete_rollout_observation_latency", side_effect=RuntimeError("timing write unavailable")):
        pending = at.start_session(**{**start, "idempotency_key": "pending-timing-start", "trace_id": "pending-timing-trace"})
    pending_state = at._load_persisted_session(pending["session_id"])
    assert pending_state is not None
    with get_connection() as conn:
        assert conn.execute(text("SELECT status FROM agent_rollout_observations WHERE trace_id=:id"), {"id": pending_state.trace_id}).scalar_one() == "measurement_pending"
    assert at.start_session(**{**start, "idempotency_key": "pending-timing-start"})["idempotent_replay"]
    print("autotutor_atomic_observation_smoke=PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        engine.dispose()
        TEMP.cleanup()
