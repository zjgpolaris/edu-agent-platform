"""Add runtime storage tables

Revision ID: 002
Revises: 001
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS accounts (
        actor_id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
        display_name TEXT,
        created_at TEXT NOT NULL
    )""")
    op.execute("""CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        actor_id TEXT,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        success INTEGER NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    op.execute("""CREATE TABLE IF NOT EXISTS weakpoints (
        student_id TEXT NOT NULL,
        knowledge_tag TEXT NOT NULL,
        wrong_count INTEGER NOT NULL DEFAULT 1,
        last_wrong_at TEXT NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (student_id, knowledge_tag)
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_weakpoints_student ON weakpoints(student_id)")
    op.execute("""CREATE TABLE IF NOT EXISTS game_rounds (
        round_id TEXT PRIMARY KEY,
        round_type TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_game_rounds_type ON game_rounds(round_type)")
    op.execute("""CREATE TABLE IF NOT EXISTS card_game_wrong_records (
        student_key TEXT PRIMARY KEY,
        card_ids TEXT NOT NULL
    )""")
    op.execute("""CREATE TABLE IF NOT EXISTS card_game_reports (
        id TEXT PRIMARY KEY,
        student_key TEXT NOT NULL,
        data TEXT NOT NULL
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_card_game_reports_key ON card_game_reports(student_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_card_game_reports_key")
    op.execute("DROP TABLE IF EXISTS card_game_reports")
    op.execute("DROP TABLE IF EXISTS card_game_wrong_records")
    op.execute("DROP INDEX IF EXISTS idx_game_rounds_type")
    op.execute("DROP TABLE IF EXISTS game_rounds")
    op.execute("DROP INDEX IF EXISTS idx_weakpoints_student")
    op.execute("DROP TABLE IF EXISTS weakpoints")
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP TABLE IF EXISTS accounts")
