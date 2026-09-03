"""Add provenance for controlled AutoTutor verification traffic.

Revision ID: 017
Revises: 016
Create Date: 2026-09-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "agent_rollout_observations" in tables:
        columns = _columns("agent_rollout_observations")
        if "traffic_source" not in columns:
            op.add_column(
                "agent_rollout_observations",
                sa.Column("traffic_source", sa.Text(), nullable=False, server_default="organic"),
            )
        if "verification_run_id" not in columns:
            op.add_column("agent_rollout_observations", sa.Column("verification_run_id", sa.Text(), nullable=True))
        if "idx_rollout_observation_traffic_source" not in _indexes("agent_rollout_observations"):
            op.create_index(
                "idx_rollout_observation_traffic_source",
                "agent_rollout_observations",
                ["agent_type", "traffic_source", "verification_run_id", "created_at"],
            )
    if "autotutor_verification_nonces" not in tables:
        op.create_table(
            "autotutor_verification_nonces",
            sa.Column("nonce_sha256", sa.Text(), primary_key=True),
            sa.Column("verification_run_id", sa.Text(), nullable=False),
            sa.Column("actor_id_sha256", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index(
            "idx_autotutor_verification_nonces_expires",
            "autotutor_verification_nonces",
            ["expires_at"],
        )


def downgrade() -> None:
    tables = _tables()
    if "autotutor_verification_nonces" in tables:
        op.drop_table("autotutor_verification_nonces")
    if "agent_rollout_observations" in tables:
        if "idx_rollout_observation_traffic_source" in _indexes("agent_rollout_observations"):
            op.drop_index("idx_rollout_observation_traffic_source", table_name="agent_rollout_observations")
        columns = _columns("agent_rollout_observations")
        if "verification_run_id" in columns:
            op.drop_column("agent_rollout_observations", "verification_run_id")
        if "traffic_source" in columns:
            op.drop_column("agent_rollout_observations", "traffic_source")
