"""Add durable Agent Runtime side-effect ledger.

Revision ID: 008
Revises: 007
Create Date: 2026-08-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "agent_side_effects" in _table_names():
        return
    op.create_table(
        "agent_side_effects",
        sa.Column("side_effect_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("resource_ref", sa.Text()),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "uq_agent_side_effects_run_key",
        "agent_side_effects",
        ["run_id", "idempotency_key"],
        unique=True,
    )
    op.create_index("idx_agent_side_effects_run_step", "agent_side_effects", ["run_id", "step_id"])
    op.create_index("idx_agent_side_effects_status_updated", "agent_side_effects", ["status", "updated_at"])


def downgrade() -> None:
    if "agent_side_effects" in _table_names():
        op.drop_table("agent_side_effects")
