"""Add Agent Runtime v2 persistence and take ownership of AutoTutor sessions.

Revision ID: 007
Revises: 006
Create Date: 2026-08-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_autotutor_sessions() -> None:
    if "autotutor_sessions" not in _table_names():
        op.create_table(
            "autotutor_sessions",
            sa.Column("session_id", sa.Text(), primary_key=True),
            sa.Column("student_id", sa.Text(), nullable=False),
            sa.Column("trace_id", sa.Text(), nullable=False),
            sa.Column("run_id", sa.Text()),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("state_json", sa.Text(), nullable=False),
            sa.Column("inflight_idempotency_key", sa.Text()),
            sa.Column("start_idempotency_key", sa.Text()),
            sa.Column("last_idempotency_key", sa.Text()),
            sa.Column("last_response_json", sa.Text()),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column("updated_at", sa.Float(), nullable=False),
        )
    else:
        columns = _column_names("autotutor_sessions")
        additions = [
            sa.Column("run_id", sa.Text()),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inflight_idempotency_key", sa.Text()),
            sa.Column("start_idempotency_key", sa.Text()),
            sa.Column("last_idempotency_key", sa.Text()),
            sa.Column("last_response_json", sa.Text()),
        ]
        with op.batch_alter_table("autotutor_sessions") as batch:
            for column in additions:
                if column.name not in columns:
                    batch.add_column(column)
    indexes = _index_names("autotutor_sessions")
    if "idx_autotutor_sessions_student_updated" not in indexes:
        op.create_index("idx_autotutor_sessions_student_updated", "autotutor_sessions", ["student_id", "updated_at"])
    if "idx_autotutor_sessions_run" not in indexes:
        op.create_index("idx_autotutor_sessions_run", "autotutor_sessions", ["run_id"])
    if "idx_autotutor_sessions_start_idempotency" not in indexes:
        op.create_index("idx_autotutor_sessions_start_idempotency", "autotutor_sessions", ["student_id", "start_idempotency_key"], unique=True)


def _create_runtime_tables() -> None:
    tables = _table_names()
    if "agent_runs" not in tables:
        op.create_table(
            "agent_runs",
            sa.Column("run_id", sa.Text(), primary_key=True),
            sa.Column("agent_type", sa.Text(), nullable=False),
            sa.Column("actor_id", sa.Text()),
            sa.Column("student_id", sa.Text()),
            sa.Column("session_id", sa.Text()),
            sa.Column("parent_run_id", sa.Text()),
            sa.Column("durability_mode", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_step_id", sa.Text()),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("context_refs_json", sa.Text(), nullable=False),
            sa.Column("input_artifact_refs_json", sa.Text(), nullable=False),
            sa.Column("plan_json", sa.Text()),
            sa.Column("state_json", sa.Text(), nullable=False),
            sa.Column("completion_json", sa.Text()),
            sa.Column("budget_json", sa.Text(), nullable=False),
            sa.Column("used_budget_json", sa.Text(), nullable=False),
            sa.Column("config_version", sa.Text(), nullable=False),
            sa.Column("trace_id", sa.Text(), nullable=False),
            sa.Column("idempotency_scope", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.Text()),
            sa.Column("last_event_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.Text()),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.Column("finished_at", sa.Text()),
        )
        op.create_index("uq_agent_runs_idempotency", "agent_runs", ["idempotency_scope", "idempotency_key"], unique=True)
        op.create_index("idx_agent_runs_session_created", "agent_runs", ["session_id", "created_at"])
        op.create_index("idx_agent_runs_status_updated", "agent_runs", ["status", "updated_at"])
        op.create_index("idx_agent_runs_agent_created", "agent_runs", ["agent_type", "created_at"])
        op.create_index("idx_agent_runs_parent", "agent_runs", ["parent_run_id"])
    if "agent_run_events" not in tables:
        op.create_table(
            "agent_run_events",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("step_id", sa.Text()),
            sa.Column("operation", sa.Text()),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("public_payload_json", sa.Text(), nullable=False),
            sa.Column("internal_metadata_json", sa.Text(), nullable=False),
            sa.Column("data_scope", sa.Text(), nullable=False, server_default="runtime"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("uq_agent_run_events_sequence", "agent_run_events", ["run_id", "sequence"], unique=True)
        op.create_index("idx_agent_run_events_run_created", "agent_run_events", ["run_id", "created_at"])
        op.create_index("idx_agent_run_events_scope_created", "agent_run_events", ["data_scope", "created_at"])
    if "agent_run_artifacts" not in tables:
        op.create_table(
            "agent_run_artifacts",
            sa.Column("artifact_id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("owner_actor_id", sa.Text()),
            sa.Column("student_id", sa.Text()),
            sa.Column("artifact_type", sa.Text(), nullable=False),
            sa.Column("sensitivity", sa.Text(), nullable=False),
            sa.Column("content_json", sa.Text(), nullable=False),
            sa.Column("content_sha256", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Text()),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_agent_artifacts_run", "agent_run_artifacts", ["run_id"])
        op.create_index("idx_agent_artifacts_owner_created", "agent_run_artifacts", ["owner_actor_id", "created_at"])
        op.create_index("idx_agent_artifacts_student_created", "agent_run_artifacts", ["student_id", "created_at"])
        op.create_index("idx_agent_artifacts_expires", "agent_run_artifacts", ["expires_at"])
    if "agent_checkpoints" not in tables:
        op.create_table(
            "agent_checkpoints",
            sa.Column("checkpoint_id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("node_name", sa.Text(), nullable=False),
            sa.Column("state_json", sa.Text(), nullable=False),
            sa.Column("side_effect_ledger_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_agent_checkpoints_run_revision", "agent_checkpoints", ["run_id", "revision"])


def upgrade() -> None:
    _create_autotutor_sessions()
    _create_runtime_tables()


def downgrade() -> None:
    for table_name in ("agent_checkpoints", "agent_run_artifacts", "agent_run_events", "agent_runs"):
        if table_name in _table_names():
            op.drop_table(table_name)
    if "autotutor_sessions" in _table_names():
        indexes = _index_names("autotutor_sessions")
        # Both indexes reference v2-only columns.  Drop them before SQLite's
        # batch table rebuild, otherwise Alembic attempts to recreate an index
        # against a column that has already been removed.
        if "idx_autotutor_sessions_start_idempotency" in indexes:
            op.drop_index("idx_autotutor_sessions_start_idempotency", table_name="autotutor_sessions")
        if "idx_autotutor_sessions_run" in indexes:
            op.drop_index("idx_autotutor_sessions_run", table_name="autotutor_sessions")
        columns = _column_names("autotutor_sessions")
        with op.batch_alter_table("autotutor_sessions") as batch:
            for column_name in ("last_response_json", "last_idempotency_key", "start_idempotency_key", "inflight_idempotency_key", "revision", "run_id"):
                if column_name in columns:
                    batch.drop_column(column_name)
