"""Add pgvector RAG documents table

Revision ID: 003
Revises: 002
Create Date: 2026-06-29

仅在 Postgres 上创建 pgvector 扩展与 rag_documents 表（含向量列与 ivfflat 索引）。
sqlite 本地库不支持 vector 类型，跳过——本地要用 RAG 请把 DATABASE_URL 指向带
pgvector 的 Postgres（可用 Supabase）。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 1024


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS rag_documents (
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({EMBED_DIM})
        )"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_rag_documents_collection ON rag_documents (collection)")
    # cosine 距离的 ivfflat 近邻索引；lists 适配中小规模语料。
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_documents_embedding "
        "ON rag_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS idx_rag_documents_embedding")
    op.execute("DROP INDEX IF EXISTS idx_rag_documents_collection")
    op.execute("DROP TABLE IF EXISTS rag_documents")
