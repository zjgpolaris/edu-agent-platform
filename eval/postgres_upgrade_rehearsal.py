from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

database_url = os.getenv("DATABASE_URL", "")
if not database_url.startswith(("postgresql://", "postgres://")):
    raise SystemExit("postgres_upgrade_rehearsal requires a PostgreSQL DATABASE_URL")

from db.engine import get_connection

FIXTURE_STUDENT = "migration-rehearsal-student"
LEGACY_COLUMNS = {
    "students": ("student_id", "grade", "display_name", "created_at", "updated_at"),
    "learning_events": ("id", "student_id", "session_id", "feature", "event_type", "metadata_json", "created_at"),
    "audit_events": ("id", "actor_id", "action", "resource_type", "resource_id", "success", "metadata_json", "created_at"),
    "review_sessions": ("id", "student_id", "date", "tasks_json", "completed", "total", "created_at"),
    "autotutor_sessions": ("session_id", "student_id", "trace_id", "status", "state_json", "created_at", "updated_at"),
    "rag_documents": ("id", "collection", "content", "metadata"),
}


def _legacy_fingerprints(conn) -> dict[str, dict[str, object]]:
    fingerprints: dict[str, dict[str, object]] = {}
    for table_name, columns in LEGACY_COLUMNS.items():
        selected = ", ".join(columns)
        primary_key = columns[0]
        rows = [tuple(row) for row in conn.execute(text(
            f"SELECT {selected} FROM {table_name} ORDER BY {primary_key}"
        )).all()]
        canonical = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        fingerprints[table_name] = {
            "row_count": len(rows),
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }
    return fingerprints


def _revision() -> str | None:
    with get_connection() as conn:
        tables = set(sa_inspect(conn).get_table_names())
        if "alembic_version" not in tables:
            return None
        return str(conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar() or "") or None


def _upgrade_head() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "backend" / "alembic.ini"), "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)


def _prepare_production_shape() -> dict[str, object]:
    with get_connection() as conn:
        assert _revision() == "003"
        conn.execute(text("""CREATE TABLE IF NOT EXISTS review_sessions (
            id TEXT PRIMARY KEY, student_id TEXT NOT NULL, date TEXT NOT NULL,
            tasks_json TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(student_id, date)
        )"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS autotutor_sessions (
            session_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, trace_id TEXT NOT NULL,
            status TEXT NOT NULL, state_json TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
        )"""))
        conn.execute(text("""INSERT INTO students (student_id, grade, display_name, created_at, updated_at)
            VALUES (:student_id, '八年级', '迁移演练', '2026-08-29T00:00:00+00:00', '2026-08-29T00:00:00+00:00')
            ON CONFLICT (student_id) DO NOTHING"""), {"student_id": FIXTURE_STUDENT})
        conn.execute(text("""INSERT INTO learning_events (
            id, student_id, session_id, feature, event_type, metadata_json, created_at
        ) VALUES ('migration-event', :student_id, 'migration-session', 'history_character',
            'character_chat', '{}', '2026-08-29T00:01:00+00:00') ON CONFLICT (id) DO NOTHING"""), {
            "student_id": FIXTURE_STUDENT,
        })
        conn.execute(text("""INSERT INTO audit_events (
            id, actor_id, action, resource_type, resource_id, success, metadata_json, created_at
        ) VALUES ('migration-audit', :student_id, 'migration.rehearsal', 'student', :student_id,
            1, '{}', '2026-08-29T00:02:00+00:00') ON CONFLICT (id) DO NOTHING"""), {
            "student_id": FIXTURE_STUDENT,
        })
        conn.execute(text("""INSERT INTO review_sessions (
            id, student_id, date, tasks_json, completed, total, created_at
        ) VALUES ('migration-review', :student_id, '2026-08-29', '[]', 0, 1,
            '2026-08-29T00:03:00+00:00') ON CONFLICT (student_id, date) DO NOTHING"""), {
            "student_id": FIXTURE_STUDENT,
        })
        conn.execute(text("""INSERT INTO autotutor_sessions (
            session_id, student_id, trace_id, status, state_json, created_at, updated_at
        ) VALUES ('migration-autotutor', :student_id, 'migration-trace', 'active', '{}', 1, 1)
            ON CONFLICT (session_id) DO NOTHING"""), {"student_id": FIXTURE_STUDENT})
        conn.execute(text("""INSERT INTO rag_documents (id, collection, content, metadata, embedding)
            VALUES ('migration-rag', 'history', 'migration rehearsal document', '{}', NULL)
            ON CONFLICT (id) DO NOTHING"""))
        return {
            "legacy_fingerprints": _legacy_fingerprints(conn),
            "student": tuple(conn.execute(text("SELECT student_id, grade, display_name FROM students WHERE student_id=:sid"), {"sid": FIXTURE_STUDENT}).one()),
            "learning": tuple(conn.execute(text("SELECT id, student_id, feature, event_type FROM learning_events WHERE id='migration-event'")).one()),
            "audit": tuple(conn.execute(text("SELECT id, actor_id, action, success FROM audit_events WHERE id='migration-audit'")).one()),
            "review": tuple(conn.execute(text("SELECT id, student_id, date, tasks_json FROM review_sessions WHERE id='migration-review'")).one()),
            "autotutor": tuple(conn.execute(text("SELECT session_id, student_id, trace_id, status FROM autotutor_sessions WHERE session_id='migration-autotutor'")).one()),
            "rag": tuple(conn.execute(text("SELECT id, collection, content FROM rag_documents WHERE id='migration-rag'")).one()),
        }


def _verify_after(before: dict[str, object]) -> None:
    with get_connection() as conn:
        assert _revision() == "014"
        assert _legacy_fingerprints(conn) == before["legacy_fingerprints"]
        assert tuple(conn.execute(text("SELECT student_id, grade, display_name FROM students WHERE student_id=:sid"), {"sid": FIXTURE_STUDENT}).one()) == before["student"]
        assert tuple(conn.execute(text("SELECT id, student_id, feature, event_type FROM learning_events WHERE id='migration-event'")).one()) == before["learning"]
        assert tuple(conn.execute(text("SELECT id, actor_id, action, success FROM audit_events WHERE id='migration-audit'")).one()) == before["audit"]
        assert tuple(conn.execute(text("SELECT id, student_id, date, tasks_json FROM review_sessions WHERE id='migration-review'")).one()) == before["review"]
        assert tuple(conn.execute(text("SELECT session_id, student_id, trace_id, status FROM autotutor_sessions WHERE session_id='migration-autotutor'")).one()) == before["autotutor"]
        assert tuple(conn.execute(text("SELECT id, collection, content FROM rag_documents WHERE id='migration-rag'")).one()) == before["rag"]
        tables = set(sa_inspect(conn).get_table_names())
        assert {"agent_runs", "agent_run_events", "agent_side_effects", "agent_rollout_observations", "agent_release_evidence", "llm_capability_manifests", "review_mastery_state"} <= tables
        learning_columns = {column["name"] for column in sa_inspect(conn).get_columns("learning_events")}
        audit_columns = {column["name"] for column in sa_inspect(conn).get_columns("audit_events")}
        autotutor_columns = {column["name"] for column in sa_inspect(conn).get_columns("autotutor_sessions")}
        review_columns = {column["name"] for column in sa_inspect(conn).get_columns("review_sessions")}
        assert {"data_scope", "effect_key"} <= learning_columns
        assert "data_scope" in audit_columns
        assert {"run_id", "revision", "inflight_request_hash", "last_request_hash"} <= autotutor_columns
        assert {"revision", "status", "last_request_hash", "last_response_json"} <= review_columns
        assert conn.execute(text("SELECT data_scope FROM learning_events WHERE id='migration-event'")).scalar_one() == "runtime"
        assert conn.execute(text("SELECT data_scope FROM audit_events WHERE id='migration-audit'")).scalar_one() == "runtime"


def main() -> None:
    before = _prepare_production_shape()
    _upgrade_head()
    _verify_after(before)
    _upgrade_head()
    _verify_after(before)
    print("postgres_upgrade_rehearsal=PASS")


if __name__ == "__main__":
    main()
