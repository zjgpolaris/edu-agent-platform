"""Add transition-level AutoTutor rollout observation dimensions.

Revision ID: 014
Revises: 013
Create Date: 2026-09-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = {
    "selected_executor": sa.Text(),
    "transition_kind": sa.Text(),
    "comparator_matched": sa.Integer(),
    "fallback_reason": sa.Text(),
    "provider_latency_ms": sa.Integer(),
    "executor_latency_ms": sa.Integer(),
    "comparator_latency_ms": sa.Integer(),
    "observation_external_calls": sa.Integer(),
    "effect_intent_count": sa.Integer(),
}


def _columns() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns("agent_rollout_observations")}


def _indexes() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("agent_rollout_observations")}


def upgrade() -> None:
    if "agent_rollout_observations" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    existing = _columns()
    for name, type_ in _COLUMNS.items():
        if name not in existing:
            op.add_column("agent_rollout_observations", sa.Column(name, type_, nullable=True))
    if "idx_rollout_observation_transition" not in _indexes():
        op.create_index(
            "idx_rollout_observation_transition",
            "agent_rollout_observations",
            ["agent_type", "selected_executor", "transition_kind", "created_at"],
        )


def downgrade() -> None:
    if "agent_rollout_observations" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "idx_rollout_observation_transition" in _indexes():
        op.drop_index("idx_rollout_observation_transition", table_name="agent_rollout_observations")
    existing = _columns()
    for name in reversed(tuple(_COLUMNS)):
        if name in existing:
            op.drop_column("agent_rollout_observations", name)
