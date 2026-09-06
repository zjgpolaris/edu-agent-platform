"""Shared SQLite/PostgreSQL checks against the actual business transaction and writer."""
from contextlib import contextmanager
import json
import time
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import event, text

from agent_runtime.rollout_observations import (
    RolloutObservationWriteError, record_rollout_observation_with_connection,
)
from db.engine import engine, get_connection
from services.autotutor_transition_service import (
    AutoTutorTransitionEffects, LearningEventIntent, WeakpointEvidenceIntent,
    commit_autotutor_start, commit_autotutor_transition,
)
from student_profile import LearningEvent, MemoryEntryUpsert


@contextmanager
def reject_observation_insert():
    """Send an invalid NOT NULL value to the real DB, not a mocked writer exception."""
    def reject(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO agent_rollout_observations"):
            if isinstance(parameters, dict):
                parameters = {**parameters, "agent_type": None}
            else:
                parameters = list(parameters)
                parameters[1] = None  # agent_type is the second inserted column
                parameters = tuple(parameters)
        return statement, parameters
    event.listen(engine, "before_cursor_execute", reject, retval=True)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", reject)


class State(BaseModel):
    session_id: str
    student_id: str
    trace_id: str
    run_id: str | None = None
    status: str = "awaiting_answer"
    revision: int = 0
    executor_mode: str = "graph_active"
    executor_assigned_mode: str = "graph_active"
    created_at: float = 0
    updated_at: float = 0


def check_atomic_observation_transactions():
    prefix = "atomic-" + uuid4().hex
    state = State(session_id=prefix, student_id=prefix, trace_id=prefix, created_at=time.time())
    def writer(conn):
        record_rollout_observation_with_connection(
            conn, agent_type="auto_tutor", runtime_mode="active", status="committed",
            latency_ms=1, trace_id=prefix, data_scope="eval", config_version="atomic-test",
            deployed_commit="a" * 40, environment="test", transition_id=f"{prefix}:{state.revision}",
            selected_executor="graph_active", assigned_executor="graph_active",
        )
    def learning(key):
        return LearningEventIntent(effect_key=key, event=LearningEvent(
            student_id=prefix, session_id=prefix, feature="auto_tutor",
            event_type="atomic_test", data_scope="eval",
        ))
    def snapshot():
        with get_connection() as conn:
            session = conn.execute(text("SELECT * FROM autotutor_sessions WHERE session_id=:id"), {"id": prefix}).mappings().first()
            counts = {}
            for table in ("learning_events", "weakpoint_evidence", "weakpoints", "memory_entries", "review_mastery_state"):
                counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE student_id=:id"), {"id": prefix}).scalar()
            counts["observation"] = conn.execute(text("SELECT COUNT(*) FROM agent_rollout_observations WHERE trace_id=:id"), {"id": prefix}).scalar()
            counts["side_effect"] = conn.execute(text("SELECT COUNT(*) FROM agent_side_effects WHERE run_id=:id"), {"id": prefix}).scalar()
            return dict(session) if session else None, counts
    start_args = dict(next_state=state, response={"revision": 0}, start_idempotency_key=prefix,
                      effects=AutoTutorTransitionEffects(session_id=prefix, claimed_revision=0,
                          idempotency_key=prefix, learning_events=[learning(prefix + ":start")]))
    try:
        commit_autotutor_start(**start_args)
        raise AssertionError("Graph commit accepted without atomic observation")
    except ValueError as exc:
        assert str(exc) == "graph_transition_requires_atomic_observation"
    before = snapshot()
    with reject_observation_insert():
        try:
            commit_autotutor_start(**start_args, observation_writer=writer)
            raise AssertionError("writer failure did not abort start")
        except RolloutObservationWriteError as exc:
            if engine.dialect.name == "postgresql":
                assert exc.cause.orig.pgcode == "23502"
    assert snapshot() == before, "start session/effect escaped rollback"
    commit_autotutor_start(**start_args, observation_writer=writer)
    assert snapshot()[1]["observation"] == 1
    # Persist the separate claim exactly as the orchestrator does.
    key = prefix + ":answer"
    with get_connection() as conn:
        conn.execute(text("UPDATE autotutor_sessions SET inflight_idempotency_key=:key, inflight_request_hash='hash' WHERE session_id=:id"), {"key": key, "id": prefix})
    state.revision = 1
    state.status = "completed"
    effects = AutoTutorTransitionEffects(
        session_id=prefix, claimed_revision=0, idempotency_key=key,
        learning_events=[learning(key)],
        weakpoint_evidence=[
            WeakpointEvidenceIntent(evidence_key=key, student_id=prefix,
                knowledge_tag="atomic-test", evidence_type="wrong", source_session_id=prefix),
            WeakpointEvidenceIntent(evidence_key=key + ":retrieval", student_id=prefix,
                knowledge_tag="atomic-test", evidence_type="retrieval_correct", source_session_id=prefix),
            WeakpointEvidenceIntent(evidence_key=key + ":verification", student_id=prefix,
                knowledge_tag="atomic-test", evidence_type="independent_correct", source_session_id=prefix,
                parent_evidence_key=key + ":retrieval"),
        ],
        review_memory=MemoryEntryUpsert(student_id=prefix, type="review_goal", content="test", source_feature="auto_tutor"),
        runtime_run_id=prefix, runtime_finalize_key=key,
    )
    args = dict(previous_revision=0, idempotency_key=key, request_hash="hash", next_state=state,
                response={"revision": 1}, effects=effects, observation_writer=writer)
    before = snapshot()
    with reject_observation_insert():
        try:
            commit_autotutor_transition(**args)
            raise AssertionError("writer failure did not abort answer")
        except RolloutObservationWriteError:
            pass
    assert snapshot() == before, "CAS, mastery, memory or side effects escaped rollback"
    def after_write(name):
        if name == "after_observation_write":
            raise RuntimeError("injected_after_observation")
    try:
        commit_autotutor_transition(**args, fault_hook=after_write)
        raise AssertionError("post-observation fault did not abort")
    except RuntimeError as exc:
        assert str(exc) == "injected_after_observation"
    assert snapshot() == before, "observation committed before business transaction"
    assert commit_autotutor_transition(**args).status == "committed"
    saved = snapshot()
    assert saved[0]["revision"] == json.loads(saved[0]["state_json"])["revision"] == 1
    assert saved[1]["observation"] == 2 and saved[1]["side_effect"] == 1
    assert saved[1]["review_mastery_state"] == 1 and saved[1]["weakpoints"] == 1
    assert saved[1]["memory_entries"] == 1 and saved[1]["weakpoint_evidence"] == 3
    # Even a currently broken writer must not run on replay/conflict/stale paths.
    with reject_observation_insert():
        assert commit_autotutor_transition(**args).status == "replayed"
        assert commit_autotutor_transition(**{**args, "request_hash": "different"}).status == "conflict"
        stale_effects = effects.model_copy(update={"idempotency_key": key + ":stale"})
        assert commit_autotutor_transition(**{**args, "idempotency_key": key + ":stale", "effects": stale_effects}).status == "stale"
    assert snapshot() == saved
    print(f"atomic_observation_transactions_{engine.dialect.name}=PASS")
