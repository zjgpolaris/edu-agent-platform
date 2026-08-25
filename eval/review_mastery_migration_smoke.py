"""Alembic 009 -> 010 -> 009 -> 010 compatibility gate."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ALEMBIC_CONFIG = BACKEND / "alembic.ini"


def migrate(db_path: Path, action: str, revision: str) -> None:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env.pop("DIRECT_URL", None)
    env.pop("PYTHONPATH", None)
    env["EDU_AGENT_DB_PATH"] = str(db_path)
    alembic_cli = Path(sys.executable).with_name("alembic")
    result = subprocess.run(
        [str(alembic_cli), "-c", str(ALEMBIC_CONFIG), action, revision],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def assert_v138(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "review_mastery_state" in tables and "review_sessions" in tables, tables
        assert {
            "evidence_stage", "assessment_fingerprint", "parent_evidence_key", "eligible_at", "occurred_at",
        } <= columns(conn, "weakpoint_evidence")
        assert {"revision", "status", "last_idempotency_key", "last_request_hash", "last_response_json"} <= columns(
            conn, "review_sessions"
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="review-mastery-migration-") as tmp:
        db_path = Path(tmp) / "review.sqlite3"
        migrate(db_path, "upgrade", "009")
        with sqlite3.connect(db_path) as conn:
            conn.execute("""INSERT INTO weakpoint_evidence (
                evidence_key, student_id, knowledge_tag, evidence_type, source_feature,
                source_session_id, assessment_id, created_at
            ) VALUES ('legacy-evidence', 'student', 'tag', 'verified_correct', 'legacy', NULL, 'legacy-q', '2026-08-24T00:00:00Z')""")
        migrate(db_path, "upgrade", "010")
        assert_v138(db_path)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("""SELECT evidence_stage, assessment_fingerprint, occurred_at
                FROM weakpoint_evidence WHERE evidence_key='legacy-evidence'""").fetchone()
            assert row == (None, None, None), row
        migrate(db_path, "downgrade", "009")
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT evidence_type FROM weakpoint_evidence WHERE evidence_key='legacy-evidence'"
            ).fetchone() == ("verified_correct",)
        migrate(db_path, "upgrade", "010")
        assert_v138(db_path)
    print("review_mastery_migration_smoke=PASS")


if __name__ == "__main__":
    main()
