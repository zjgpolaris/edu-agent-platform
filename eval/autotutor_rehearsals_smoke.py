"""Scoped signed facts, real SQLite read-only failure and unchanged global state."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
temporary = tempfile.TemporaryDirectory(prefix="autotutor-rehearsals-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temporary.name) / "db.sqlite3")
os.environ.update(EDU_AGENT_ENVIRONMENT="production", EDU_AGENT_DEPLOYED_COMMIT="c" * 40,
    EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE="active_canary", EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS="100",
    EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT="rehearsal-smoke", EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH="false",
    EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION="rehearsal-smoke", EDU_AGENT_AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET="s" * 48)
from sqlalchemy import text
from fastapi import HTTPException
from db.engine import engine, get_connection
from db.schema import metadata, accounts, autotutor_sessions
from agents.autotutor_execution import stable_executor_bucket
from agent_runtime.rollout_observations import record_rollout_observation
from agent_runtime import autotutor_rehearsals as rehearsal

STUDENT = next(f"private-student-{i}" for i in range(10000) if stable_executor_bucket(f"private-student-{i}", salt="rehearsal-smoke") < 100)
os.environ["EDU_AGENT_AUTOTUTOR_VERIFICATION_STUDENT_IDS"] = STUDENT
STATE = {"revision": 0, "status": "awaiting_answer", "executor_mode": "graph_active", "private": "private-content"}
BASE = dict(student_id=STUDENT, session_id="private-session", verification_run_id="private-verification-run",
            expected_commit="c" * 40, expected_config_version="rehearsal-smoke")


def observation(index, selected="graph_active", fallback=None):
    record_rollout_observation(agent_type="auto_tutor", runtime_mode="active", status="committed",
        latency_ms=1, trace_id="private-trace", config_version="rehearsal-smoke", deployed_commit="c" * 40,
        environment="production", data_scope="runtime", traffic_source="release_verification",
        verification_run_id=BASE["verification_run_id"], selected_executor=selected,
        transition_id=f"transition-{index}", fallback_reason=fallback)


def main():
    metadata.create_all(engine)
    with get_connection() as conn:
        conn.execute(text("CREATE TABLE alembic_version(version_num TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('017')"))
        conn.execute(accounts.insert().values(actor_id=STUDENT, username="private-user", password_hash="unused",
            role="student", account_status="active", traffic_cohort="verified", created_at="now", updated_at="now"))
        conn.execute(autotutor_sessions.insert().values(session_id=BASE["session_id"], student_id=STUDENT,
            trace_id="private-trace", status="awaiting_answer", revision=0, state_json=json.dumps(STATE), created_at=0, updated_at=0))
    observation(0)
    before = rehearsal.capture_rehearsal(**BASE)
    assert "private" not in json.dumps(before)
    for update in ({"student_id": "organic-student"}, {"session_id": "foreign-session"}, {"verification_run_id": "foreign-run"}, {"expected_commit": "b" * 40}):
        try:
            rehearsal.capture_rehearsal(**{**BASE, **update})
            raise AssertionError("invalid binding admitted")
        except ValueError:
            pass
    no_restart = rehearsal.capture_rehearsal(**BASE, operation="restart_verify", previous=before)
    assert not no_restart["payload"]["checks"]["state_survived_process_change"]
    tampered = json.loads(json.dumps(before))
    tampered["payload"]["revision"] = 99
    expired = json.loads(json.dumps(before["payload"]))
    expired["captured_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    for invalid in (tampered, rehearsal._seal(expired)):
        try:
            rehearsal.capture_rehearsal(**BASE, operation="restart_verify", previous=invalid)
            raise AssertionError("untrusted receipt admitted")
        except ValueError:
            pass
    with patch.object(rehearsal, "_BOOT", "new-process"):
        restored = rehearsal.capture_rehearsal(**BASE, operation="restart_verify", previous=before)
        assert restored["payload"]["checks"]["state_survived_process_change"]
        STATE["revision"] = 1
        with get_connection() as conn:
            conn.execute(autotutor_sessions.update().values(revision=1, state_json=json.dumps(STATE)))
        observation(1)
        resumed = rehearsal.capture_rehearsal(**BASE, operation="restart_resume_verify", previous=restored)
        assert resumed["payload"]["checks"]["resumed_once_after_process_change"]
    with get_connection() as conn:
        before_rows = conn.execute(text("SELECT COUNT(*) FROM agent_rollout_observations")).scalar()
        audit_rows = conn.execute(text("SELECT COUNT(*) FROM audit_events")).scalar()
    probe = rehearsal.capture_rehearsal(**BASE, operation="writer_probe")
    assert probe["payload"]["writer_probe"]["status"] == "pass"
    assert probe["payload"]["checks"]["uncached_admission_denied_on_writer_unavailable"]
    assert probe["payload"]["production_attestation"] is False
    with get_connection() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM agent_rollout_observations")).scalar() == before_rows
        assert conn.execute(text("SELECT COUNT(*) FROM audit_events")).scalar() == audit_rows
        assert conn.execute(text("PRAGMA query_only")).scalar() == 0
    kill_before = rehearsal.capture_rehearsal(**BASE)
    STATE.update(revision=2, executor_mode="legacy")
    with get_connection() as conn:
        conn.execute(autotutor_sessions.update().values(revision=2, state_json=json.dumps(STATE)))
    observation(2, "legacy", "kill_switch_enabled")
    with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "true"}):
        killed = rehearsal.capture_rehearsal(**BASE, operation="kill_switch_verify", previous=kill_before)
        assert killed["payload"]["checks"]["kill_switch_downgraded_transition"]
    from api.routers.agent_runtime import AutoTutorRehearsalRequest, capture_autotutor_rehearsal
    from security.auth import Actor
    request = AutoTutorRehearsalRequest(**BASE)
    for enabled, actor, expected in (("false", Actor(actor_id="autotutor-verifier:current", role="admin"), "rehearsals_disabled"),
                                    ("true", Actor(actor_id="ordinary-admin", role="admin"), "rehearsal_machine_identity_required")):
        with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_REHEARSALS_ENABLED": enabled}):
            try:
                asyncio.run(capture_autotutor_rehearsal(request, actor))
                raise AssertionError("rehearsal route accepted unauthorized caller")
            except HTTPException as exc:
                assert exc.status_code == 403 and exc.detail == expected
    print("autotutor_rehearsals_smoke=PASS")


if __name__ == "__main__":
    main()
