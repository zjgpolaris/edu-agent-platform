"""Add production account authority and trusted rollout cohorts.

Revision ID: 012
Revises: 011
Create Date: 2026-08-30
"""
from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "accounts" in tables:
        columns = _columns("accounts")
        if "account_status" not in columns:
            op.add_column("accounts", sa.Column("account_status", sa.Text(), nullable=False, server_default="active"))
        if "traffic_cohort" not in columns:
            op.add_column("accounts", sa.Column("traffic_cohort", sa.Text(), nullable=False, server_default="unverified"))
        if "updated_at" not in columns:
            op.add_column("accounts", sa.Column("updated_at", sa.Text(), nullable=False, server_default=""))
        op.get_bind().execute(
            sa.text("UPDATE accounts SET updated_at=:updated_at WHERE updated_at='' OR updated_at IS NULL"),
            {"updated_at": datetime.now(timezone.utc).isoformat()},
        )

    if "agent_rollout_observations" in tables:
        columns = _columns("agent_rollout_observations")
        if "traffic_cohort" not in columns:
            op.add_column("agent_rollout_observations", sa.Column("traffic_cohort", sa.Text(), nullable=False, server_default="legacy_untrusted"))
        if "rollout_eligible" not in columns:
            op.add_column("agent_rollout_observations", sa.Column("rollout_eligible", sa.Integer(), nullable=False, server_default="0"))
        if "eligibility_reason" not in columns:
            op.add_column("agent_rollout_observations", sa.Column("eligibility_reason", sa.Text(), nullable=False, server_default="legacy_untrusted"))
        if "idx_rollout_observation_eligibility" not in _indexes("agent_rollout_observations"):
            op.create_index(
                "idx_rollout_observation_eligibility",
                "agent_rollout_observations",
                ["rollout_eligible", "eligibility_reason", "created_at"],
            )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "agent_rollout_observations" in tables:
        if "idx_rollout_observation_eligibility" in _indexes("agent_rollout_observations"):
            op.drop_index("idx_rollout_observation_eligibility", table_name="agent_rollout_observations")
        for column in ("eligibility_reason", "rollout_eligible", "traffic_cohort"):
            if column in _columns("agent_rollout_observations"):
                op.drop_column("agent_rollout_observations", column)
    if "accounts" in tables:
        for column in ("updated_at", "traffic_cohort", "account_status"):
            if column in _columns("accounts"):
                op.drop_column("accounts", column)
