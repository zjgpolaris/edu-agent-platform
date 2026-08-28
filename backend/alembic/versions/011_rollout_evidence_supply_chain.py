"""Add rollout observations and durable aggregate release evidence.

Revision ID: 011
Revises: 010
Create Date: 2026-08-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "agent_rollout_observations" not in tables:
        op.create_table(
            "agent_rollout_observations",
            sa.Column("observation_id", sa.Text(), primary_key=True),
            sa.Column("agent_type", sa.Text(), nullable=False),
            sa.Column("config_version", sa.Text(), nullable=False),
            sa.Column("runtime_mode", sa.Text(), nullable=False),
            sa.Column("deployed_commit", sa.Text(), nullable=False),
            sa.Column("environment", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("trace_id", sa.Text()),
            sa.Column("data_scope", sa.Text(), nullable=False, server_default="runtime"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index(
            "idx_rollout_observation_slice_created",
            "agent_rollout_observations",
            ["agent_type", "config_version", "runtime_mode", "data_scope", "created_at"],
        )
        op.create_index(
            "idx_rollout_observation_commit_created",
            "agent_rollout_observations",
            ["deployed_commit", "created_at"],
        )

    if "agent_release_evidence" not in tables:
        op.create_table(
            "agent_release_evidence",
            sa.Column("evidence_id", sa.Text(), primary_key=True),
            sa.Column("agent_type", sa.Text(), nullable=False),
            sa.Column("config_version", sa.Text(), nullable=False),
            sa.Column("runtime_mode", sa.Text(), nullable=False),
            sa.Column("deployed_commit", sa.Text(), nullable=False),
            sa.Column("environment", sa.Text(), nullable=False),
            sa.Column("evidence_sha256", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index(
            "uq_agent_release_evidence_hash",
            "agent_release_evidence",
            ["evidence_sha256"],
            unique=True,
        )
        op.create_index(
            "idx_release_evidence_slice_created",
            "agent_release_evidence",
            ["agent_type", "config_version", "runtime_mode", "deployed_commit", "created_at"],
        )


def downgrade() -> None:
    tables = _tables()
    if "agent_release_evidence" in tables:
        op.drop_table("agent_release_evidence")
    if "agent_rollout_observations" in tables:
        op.drop_table("agent_rollout_observations")
