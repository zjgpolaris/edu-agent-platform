"""Add independent review verification and retention evidence.

Revision ID: 010
Revises: 009
Create Date: 2026-08-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    evidence_columns = _columns("weakpoint_evidence")
    with op.batch_alter_table("weakpoint_evidence") as batch:
        for name in (
            "evidence_stage",
            "assessment_fingerprint",
            "parent_evidence_key",
            "eligible_at",
            "occurred_at",
        ):
            if name not in evidence_columns:
                batch.add_column(sa.Column(name, sa.Text()))
    if "idx_weakpoint_evidence_chain" not in _indexes("weakpoint_evidence"):
        op.create_index(
            "idx_weakpoint_evidence_chain",
            "weakpoint_evidence",
            ["student_id", "knowledge_tag", "evidence_stage", "assessment_fingerprint", "occurred_at"],
        )

    if "review_mastery_state" not in _tables():
        op.create_table(
            "review_mastery_state",
            sa.Column("student_id", sa.Text(), nullable=False),
            sa.Column("knowledge_tag", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("retrieval_evidence_key", sa.Text()),
            sa.Column("verification_evidence_key", sa.Text()),
            sa.Column("retention_evidence_key", sa.Text()),
            sa.Column("retention_due_at", sa.Text()),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("student_id", "knowledge_tag"),
        )
        op.create_index("idx_review_mastery_due", "review_mastery_state", ["status", "retention_due_at"])

    if "review_sessions" not in _tables():
        op.create_table(
            "review_sessions",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("student_id", sa.Text(), nullable=False),
            sa.Column("date", sa.Text(), nullable=False),
            sa.Column("tasks_json", sa.Text(), nullable=False),
            sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.Text(), nullable=False, server_default="active"),
            sa.Column("last_idempotency_key", sa.Text()),
            sa.Column("last_request_hash", sa.Text()),
            sa.Column("last_response_json", sa.Text()),
        )
        op.create_index("idx_review_sessions_student_date", "review_sessions", ["student_id", "date"], unique=True)
    else:
        session_columns = _columns("review_sessions")
        with op.batch_alter_table("review_sessions") as batch:
            if "revision" not in session_columns:
                batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
            if "status" not in session_columns:
                batch.add_column(sa.Column("status", sa.Text(), nullable=False, server_default="active"))
            for name in ("last_idempotency_key", "last_request_hash", "last_response_json"):
                if name not in session_columns:
                    batch.add_column(sa.Column(name, sa.Text()))


def downgrade() -> None:
    session_columns = _columns("review_sessions")
    with op.batch_alter_table("review_sessions") as batch:
        for name in ("last_response_json", "last_request_hash", "last_idempotency_key", "status", "revision"):
            if name in session_columns:
                batch.drop_column(name)
    if "review_mastery_state" in _tables():
        op.drop_table("review_mastery_state")
    if "idx_weakpoint_evidence_chain" in _indexes("weakpoint_evidence"):
        op.drop_index("idx_weakpoint_evidence_chain", table_name="weakpoint_evidence")
    evidence_columns = _columns("weakpoint_evidence")
    with op.batch_alter_table("weakpoint_evidence") as batch:
        for name in ("occurred_at", "eligible_at", "parent_evidence_key", "assessment_fingerprint", "evidence_stage"):
            if name in evidence_columns:
                batch.drop_column(name)
