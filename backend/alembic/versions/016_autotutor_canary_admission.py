"""Add AutoTutor canary admission provenance.

Revision ID: 016
Revises: 015
Create Date: 2026-09-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = {
    "assignment_reason": sa.Text(),
    "admission_status": sa.Text(),
    "admission_reason": sa.Text(),
    "admission_checked_at": sa.Text(),
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
    if "idx_rollout_observation_admission" not in _indexes():
        op.create_index(
            "idx_rollout_observation_admission",
            "agent_rollout_observations",
            ["agent_type", "admission_status", "created_at"],
        )


def downgrade() -> None:
    if "agent_rollout_observations" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "idx_rollout_observation_admission" in _indexes():
        op.drop_index("idx_rollout_observation_admission", table_name="agent_rollout_observations")
    existing = _columns()
    for name in reversed(tuple(_COLUMNS)):
        if name in existing:
            op.drop_column("agent_rollout_observations", name)
