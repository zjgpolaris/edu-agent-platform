"""SQLite upgrade/downgrade coverage for Agent Runtime v2 migrations 007/008."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = ROOT / "backend" / "alembic.ini"
RUNTIME_TABLES = {
    "agent_runs",
    "agent_run_events",
    "agent_run_artifacts",
    "agent_checkpoints",
    "agent_side_effects",
}
LEGACY_AUTOTUTOR_COLUMNS = {
    "session_id",
    "student_id",
    "trace_id",
    "status",
    "state_json",
    "created_at",
    "updated_at",
}
V2_AUTOTUTOR_COLUMNS = {
    "run_id",
    "revision",
    "inflight_idempotency_key",
    "start_idempotency_key",
    "last_idempotency_key",
    "last_response_json",
}


def _migrate(db_path: Path, command: str, revision: str) -> None:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env.pop("DIRECT_URL", None)
    # The suite runner prepends backend/ to PYTHONPATH; that directory contains
    # our migration scripts package named ``alembic`` and would shadow the
    # installed Alembic CLI package in this child process.
    env.pop("PYTHONPATH", None)
    env["EDU_AGENT_DB_PATH"] = str(db_path)
    alembic_cli = Path(sys.executable).with_name("alembic")
    completed = subprocess.run(
        [str(alembic_cli), "-c", str(ALEMBIC_CONFIG), command, revision],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)


def _schema(db_path: Path) -> tuple[set[str], set[str], set[str]]:
    with sqlite3.connect(db_path) as conn:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(autotutor_sessions)")}
        indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(autotutor_sessions)")}
    return tables, columns, indexes


def _assert_v2(db_path: Path) -> None:
    tables, columns, indexes = _schema(db_path)
    assert RUNTIME_TABLES <= tables
    assert LEGACY_AUTOTUTOR_COLUMNS | V2_AUTOTUTOR_COLUMNS <= columns
    assert "idx_autotutor_sessions_run" in indexes
    assert "idx_autotutor_sessions_start_idempotency" in indexes


def _assert_downgraded(db_path: Path) -> None:
    tables, columns, indexes = _schema(db_path)
    assert not (RUNTIME_TABLES & tables)
    assert columns == LEGACY_AUTOTUTOR_COLUMNS
    assert "idx_autotutor_sessions_student_updated" in indexes
    assert "idx_autotutor_sessions_run" not in indexes
    assert "idx_autotutor_sessions_start_idempotency" not in indexes


def _create_legacy_autotutor_table(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE autotutor_sessions (
                session_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX idx_autotutor_sessions_student_updated
                ON autotutor_sessions(student_id, updated_at DESC);
            INSERT INTO autotutor_sessions (
                session_id, student_id, trace_id, status, state_json, created_at, updated_at
            ) VALUES ('legacy_session', 'student_1', 'trace_1', 'active', '{}', 1.0, 1.0);
            """
        )


def _assert_legacy_row_survives(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT student_id, trace_id, status, state_json FROM autotutor_sessions WHERE session_id='legacy_session'"
        ).fetchone()
    assert row == ("student_1", "trace_1", "active", "{}")


def main() -> None:
    with TemporaryDirectory(prefix="edu-agent-runtime-migration-") as tmp:
        temp_root = Path(tmp)

        fresh_db = temp_root / "fresh.sqlite3"
        _migrate(fresh_db, "upgrade", "head")
        _assert_v2(fresh_db)
        _migrate(fresh_db, "downgrade", "006")
        _assert_downgraded(fresh_db)

        legacy_db = temp_root / "legacy.sqlite3"
        _migrate(legacy_db, "upgrade", "006")
        _create_legacy_autotutor_table(legacy_db)
        _migrate(legacy_db, "upgrade", "head")
        _assert_v2(legacy_db)
        _assert_legacy_row_survives(legacy_db)
        _migrate(legacy_db, "downgrade", "006")
        _assert_downgraded(legacy_db)
        _assert_legacy_row_survives(legacy_db)

    print("agent_runtime_migration_smoke=PASS")


if __name__ == "__main__":
    main()
