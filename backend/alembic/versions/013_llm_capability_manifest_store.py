"""Add the append-only LLM capability manifest store.

Revision ID: 013
Revises: 012
Create Date: 2026-08-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "llm_capability_manifests" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "llm_capability_manifests",
        sa.Column("manifest_id", sa.Text(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("deployed_commit", sa.Text(), nullable=False),
        sa.Column("image_digest", sa.Text(), nullable=False),
        sa.Column("runtime_config_version", sa.Text(), nullable=False),
        sa.Column("endpoint_fingerprint", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("uq_llm_capability_manifest_hash", "llm_capability_manifests", ["manifest_sha256"], unique=True)
    op.create_index(
        "idx_llm_capability_manifest_provenance_expiry",
        "llm_capability_manifests",
        ["provider", "environment", "deployed_commit", "image_digest", "runtime_config_version", "endpoint_fingerprint", "expires_at"],
    )


def downgrade() -> None:
    if "llm_capability_manifests" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("llm_capability_manifests")
