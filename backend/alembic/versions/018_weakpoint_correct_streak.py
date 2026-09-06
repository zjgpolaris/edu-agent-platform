"""Add the weakpoint streak column missing from the PostgreSQL migration chain.

Revision ID: 018
Revises: 017
"""
import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("weakpoints")}
    # SQLite compatibility bootstrapping or a prior operator repair may already
    # have created this column. Preserve existing streaks and business rows.
    if "correct_streak" not in columns:
        op.add_column("weakpoints", sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("weakpoints")}
    if "correct_streak" in columns:
        op.drop_column("weakpoints", "correct_streak")
