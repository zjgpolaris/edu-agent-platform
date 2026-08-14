"""Add first-class event data scopes for reliable AgentOps windows.

Revision ID: 006
Revises: 005
Create Date: 2026-08-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "data_scope" not in {column["name"] for column in inspector.get_columns("audit_events")}:
        with op.batch_alter_table("audit_events") as batch:
            batch.add_column(sa.Column("data_scope", sa.Text(), nullable=False, server_default="runtime"))
    if "data_scope" not in {column["name"] for column in inspector.get_columns("learning_events")}:
        with op.batch_alter_table("learning_events") as batch:
            batch.add_column(sa.Column("data_scope", sa.Text(), nullable=False, server_default="runtime"))

    inspector = sa.inspect(bind)
    audit_indexes = {index["name"] for index in inspector.get_indexes("audit_events")}
    learning_indexes = {index["name"] for index in inspector.get_indexes("learning_events")}
    if "idx_audit_events_scope_created" not in audit_indexes:
        op.create_index("idx_audit_events_scope_created", "audit_events", ["data_scope", "created_at"])
    if "idx_learning_events_scope_created" not in learning_indexes:
        op.create_index("idx_learning_events_scope_created", "learning_events", ["data_scope", "created_at"])
    if "idx_learning_events_feature_type_created" not in learning_indexes:
        op.create_index(
            "idx_learning_events_feature_type_created",
            "learning_events",
            ["feature", "event_type", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    audit_indexes = {index["name"] for index in inspector.get_indexes("audit_events")}
    learning_indexes = {index["name"] for index in inspector.get_indexes("learning_events")}
    if "idx_learning_events_feature_type_created" in learning_indexes:
        op.drop_index("idx_learning_events_feature_type_created", table_name="learning_events")
    if "idx_learning_events_scope_created" in learning_indexes:
        op.drop_index("idx_learning_events_scope_created", table_name="learning_events")
    if "idx_audit_events_scope_created" in audit_indexes:
        op.drop_index("idx_audit_events_scope_created", table_name="audit_events")
    if "data_scope" in {column["name"] for column in inspector.get_columns("learning_events")}:
        with op.batch_alter_table("learning_events") as batch:
            batch.drop_column("data_scope")
    if "data_scope" in {column["name"] for column in inspector.get_columns("audit_events")}:
        with op.batch_alter_table("audit_events") as batch:
            batch.drop_column("data_scope")
