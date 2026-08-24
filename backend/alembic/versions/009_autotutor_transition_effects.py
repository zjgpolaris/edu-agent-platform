"""Add idempotent AutoTutor transition effects.

Revision ID: 009
Revises: 008
Create Date: 2026-08-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "effect_key" not in _columns("learning_events"):
        with op.batch_alter_table("learning_events") as batch:
            batch.add_column(sa.Column("effect_key", sa.Text(), nullable=True))
    if "uq_learning_events_effect_key" not in _indexes("learning_events"):
        op.create_index(
            "uq_learning_events_effect_key",
            "learning_events",
            ["effect_key"],
            unique=True,
        )

    if "weakpoint_evidence" not in _tables():
        op.create_table(
            "weakpoint_evidence",
            sa.Column("evidence_key", sa.Text(), primary_key=True),
            sa.Column("student_id", sa.Text(), nullable=False),
            sa.Column("knowledge_tag", sa.Text(), nullable=False),
            sa.Column("evidence_type", sa.Text(), nullable=False),
            sa.Column("source_feature", sa.Text(), nullable=False),
            sa.Column("source_session_id", sa.Text()),
            sa.Column("assessment_id", sa.Text()),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index(
            "idx_weakpoint_evidence_student_tag_created",
            "weakpoint_evidence",
            ["student_id", "knowledge_tag", "created_at"],
        )

    session_columns = _columns("autotutor_sessions")
    with op.batch_alter_table("autotutor_sessions") as batch:
        if "inflight_request_hash" not in session_columns:
            batch.add_column(sa.Column("inflight_request_hash", sa.Text()))
        if "last_request_hash" not in session_columns:
            batch.add_column(sa.Column("last_request_hash", sa.Text()))


def downgrade() -> None:
    if "weakpoint_evidence" in _tables():
        op.drop_table("weakpoint_evidence")
    if "uq_learning_events_effect_key" in _indexes("learning_events"):
        op.drop_index("uq_learning_events_effect_key", table_name="learning_events")
    if "effect_key" in _columns("learning_events"):
        with op.batch_alter_table("learning_events") as batch:
            batch.drop_column("effect_key")
    session_columns = _columns("autotutor_sessions")
    with op.batch_alter_table("autotutor_sessions") as batch:
        if "last_request_hash" in session_columns:
            batch.drop_column("last_request_hash")
        if "inflight_request_hash" in session_columns:
            batch.drop_column("inflight_request_hash")
