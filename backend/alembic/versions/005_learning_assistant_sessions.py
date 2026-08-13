"""Add persistent learning assistant sessions and messages.

Revision ID: 005
Revises: 004
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS assistant_sessions (
        session_id TEXT PRIMARY KEY, student_id TEXT NOT NULL, title TEXT,
        status TEXT NOT NULL, source_feature TEXT NOT NULL, source_session_id TEXT,
        context_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    op.execute("""CREATE TABLE IF NOT EXISTS assistant_messages (
        message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, intent TEXT, trace_id TEXT, tool_results_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_assistant_sessions_student_updated ON assistant_sessions(student_id, updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_assistant_sessions_source ON assistant_sessions(source_feature, source_session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_assistant_messages_session_created ON assistant_messages(session_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_assistant_messages_session_created")
    op.execute("DROP INDEX IF EXISTS idx_assistant_sessions_source")
    op.execute("DROP INDEX IF EXISTS idx_assistant_sessions_student_updated")
    op.execute("DROP TABLE IF EXISTS assistant_messages")
    op.execute("DROP TABLE IF EXISTS assistant_sessions")
