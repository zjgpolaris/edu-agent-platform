"""Add durable agent jobs table.

Revision ID: 004
Revises: 003
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS agent_jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        actor_id TEXT,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        result_json TEXT,
        idempotency_key TEXT,
        trace_id TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        timeout_seconds INTEGER NOT NULL DEFAULT 300,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    )""")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_jobs_actor_idempotency
        ON agent_jobs(actor_id, idempotency_key)""")
    op.execute("""CREATE INDEX IF NOT EXISTS idx_agent_jobs_status_created
        ON agent_jobs(status, created_at)""")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_jobs_status_created")
    op.execute("DROP INDEX IF EXISTS idx_agent_jobs_actor_idempotency")
    op.execute("DROP TABLE IF EXISTS agent_jobs")
