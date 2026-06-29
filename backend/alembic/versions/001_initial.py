"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("student_id", sa.Text, primary_key=True),
        sa.Column("grade", sa.Text),
        sa.Column("display_name", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_table(
        "learning_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("student_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text),
        sa.Column("feature", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("grade", sa.Text),
        sa.Column("topic", sa.Text),
        sa.Column("lesson_id", sa.Text),
        sa.Column("book_id", sa.Text),
        sa.Column("score", sa.Float),
        sa.Column("success", sa.Integer),
        sa.Column("metadata_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_learning_events_student_created", "learning_events", ["student_id", "created_at"])
    op.create_table(
        "student_profiles",
        sa.Column("student_id", sa.Text, primary_key=True),
        sa.Column("grade", sa.Text),
        sa.Column("recent_topics_json", sa.Text, nullable=False),
        sa.Column("recent_lessons_json", sa.Text, nullable=False),
        sa.Column("weak_topics_json", sa.Text, nullable=False),
        sa.Column("strong_topics_json", sa.Text, nullable=False),
        sa.Column("quiz_stats_json", sa.Text, nullable=False),
        sa.Column("game_stats_json", sa.Text, nullable=False),
        sa.Column("character_interests_json", sa.Text, nullable=False),
        sa.Column("interaction_summary_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("student_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("content_json", sa.Text, nullable=False),
        sa.Column("source_feature", sa.Text),
        sa.Column("source_event_id", sa.Text),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("metadata_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("last_used_at", sa.Text),
        sa.Column("disabled_at", sa.Text),
        sa.Column("deleted_at", sa.Text),
    )
    op.create_index("idx_memory_entries_student_status", "memory_entries", ["student_id", "status", "updated_at"])
    op.create_index("idx_memory_entries_source_event", "memory_entries", ["source_event_id"])
    op.create_table(
        "materials",
        sa.Column("material_id", sa.Text, primary_key=True),
        sa.Column("owner_key", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("grade", sa.Text),
        sa.Column("tags_json", sa.Text, nullable=False),
        sa.Column("text_chars", sa.Integer, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False),
        sa.Column("ocr_mode", sa.Text),
        sa.Column("quality_json", sa.Text),
        sa.Column("warnings_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text),
    )
    op.create_index("idx_materials_owner_created", "materials", ["owner_key", "created_at"])
    op.create_table(
        "material_pages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("material_id", sa.Text, nullable=False),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
    )
    op.create_table(
        "material_chunks",
        sa.Column("chunk_id", sa.Text, primary_key=True),
        sa.Column("material_id", sa.Text, nullable=False),
        sa.Column("owner_key", sa.Text, nullable=False),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("metadata_json", sa.Text, nullable=False),
    )
    op.create_index("idx_material_chunks_material", "material_chunks", ["material_id"])
    op.create_index("idx_material_chunks_owner_material", "material_chunks", ["owner_key", "material_id"])
    op.create_table(
        "homework_reviews",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("student_id", sa.Text),
        sa.Column("actor_id", sa.Text),
        sa.Column("grade_request_json", sa.Text, nullable=False),
        sa.Column("grade_result_json", sa.Text, nullable=False),
        sa.Column("needs_human_review", sa.Integer, nullable=False, server_default="0"),
        sa.Column("decision", sa.Text, nullable=False, server_default="pending"),
        sa.Column("teacher_id", sa.Text),
        sa.Column("teacher_note", sa.Text),
        sa.Column("teacher_score", sa.Float),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("reviewed_at", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("homework_reviews")
    op.drop_index("idx_material_chunks_owner_material", table_name="material_chunks")
    op.drop_index("idx_material_chunks_material", table_name="material_chunks")
    op.drop_table("material_chunks")
    op.drop_table("material_pages")
    op.drop_index("idx_materials_owner_created", table_name="materials")
    op.drop_table("materials")
    op.drop_index("idx_memory_entries_source_event", table_name="memory_entries")
    op.drop_index("idx_memory_entries_student_status", table_name="memory_entries")
    op.drop_table("memory_entries")
    op.drop_table("student_profiles")
    op.drop_index("idx_learning_events_student_created", table_name="learning_events")
    op.drop_table("learning_events")
    op.drop_table("students")
