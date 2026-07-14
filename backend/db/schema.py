"""SQLAlchemy table definitions — used by Alembic for migration autogeneration."""
from sqlalchemy import Column, Float, Index, Integer, MetaData, Table, Text, CheckConstraint

metadata = MetaData()

students = Table(
    "students", metadata,
    Column("student_id", Text, primary_key=True),
    Column("grade", Text),
    Column("display_name", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

learning_events = Table(
    "learning_events", metadata,
    Column("id", Text, primary_key=True),
    Column("student_id", Text, nullable=False),
    Column("session_id", Text),
    Column("feature", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("grade", Text),
    Column("topic", Text),
    Column("lesson_id", Text),
    Column("book_id", Text),
    Column("score", Float),
    Column("success", Integer),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Index("idx_learning_events_student_created", "student_id", "created_at"),
)

student_profiles = Table(
    "student_profiles", metadata,
    Column("student_id", Text, primary_key=True),
    Column("grade", Text),
    Column("recent_topics_json", Text, nullable=False),
    Column("recent_lessons_json", Text, nullable=False),
    Column("weak_topics_json", Text, nullable=False),
    Column("strong_topics_json", Text, nullable=False),
    Column("quiz_stats_json", Text, nullable=False),
    Column("game_stats_json", Text, nullable=False),
    Column("character_interests_json", Text, nullable=False),
    Column("interaction_summary_json", Text, nullable=False, server_default="{}"),
    Column("updated_at", Text, nullable=False),
)

memory_entries = Table(
    "memory_entries", metadata,
    Column("id", Text, primary_key=True),
    Column("student_id", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("content_json", Text, nullable=False),
    Column("source_feature", Text),
    Column("source_event_id", Text),
    Column("confidence", Float, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("last_used_at", Text),
    Column("disabled_at", Text),
    Column("deleted_at", Text),
    Index("idx_memory_entries_student_status", "student_id", "status", "updated_at"),
    Index("idx_memory_entries_source_event", "source_event_id"),
)

materials = Table(
    "materials", metadata,
    Column("material_id", Text, primary_key=True),
    Column("owner_key", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("source_type", Text, nullable=False),
    Column("subject", Text),
    Column("grade", Text),
    Column("tags_json", Text, nullable=False),
    Column("text_chars", Integer, nullable=False),
    Column("page_count", Integer, nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("ocr_mode", Text),
    Column("quality_json", Text),
    Column("warnings_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("expires_at", Text),
    Index("idx_materials_owner_created", "owner_key", "created_at"),
)

material_pages = Table(
    "material_pages", metadata,
    Column("id", Text, primary_key=True),
    Column("material_id", Text, nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("source_type", Text, nullable=False),
    Column("text", Text, nullable=False),
)

material_chunks = Table(
    "material_chunks", metadata,
    Column("chunk_id", Text, primary_key=True),
    Column("material_id", Text, nullable=False),
    Column("owner_key", Text, nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("metadata_json", Text, nullable=False),
    Index("idx_material_chunks_material", "material_id"),
    Index("idx_material_chunks_owner_material", "owner_key", "material_id"),
)

homework_reviews = Table(
    "homework_reviews", metadata,
    Column("id", Text, primary_key=True),
    Column("student_id", Text),
    Column("actor_id", Text),
    Column("grade_request_json", Text, nullable=False),
    Column("grade_result_json", Text, nullable=False),
    Column("needs_human_review", Integer, nullable=False, server_default="0"),
    Column("decision", Text, nullable=False, server_default="pending"),
    Column("teacher_id", Text),
    Column("teacher_note", Text),
    Column("teacher_score", Float),
    Column("created_at", Text, nullable=False),
    Column("reviewed_at", Text),
)

accounts = Table(
    "accounts", metadata,
    Column("actor_id", Text, primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("display_name", Text),
    Column("created_at", Text, nullable=False),
    CheckConstraint("role IN ('student','teacher','admin')", name="ck_accounts_role"),
)

audit_events = Table(
    "audit_events", metadata,
    Column("id", Text, primary_key=True),
    Column("actor_id", Text),
    Column("action", Text, nullable=False),
    Column("resource_type", Text),
    Column("resource_id", Text),
    Column("success", Integer, nullable=False),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

weakpoints = Table(
    "weakpoints", metadata,
    Column("student_id", Text, primary_key=True),
    Column("knowledge_tag", Text, primary_key=True),
    Column("wrong_count", Integer, nullable=False, server_default="1"),
    Column("last_wrong_at", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("correct_streak", Integer, nullable=False, server_default="0"),
    Index("idx_weakpoints_student", "student_id"),
)

game_rounds = Table(
    "game_rounds", metadata,
    Column("round_id", Text, primary_key=True),
    Column("round_type", Text, nullable=False),
    Column("data", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Index("idx_game_rounds_type", "round_type"),
)

card_game_wrong_records = Table(
    "card_game_wrong_records", metadata,
    Column("student_key", Text, primary_key=True),
    Column("card_ids", Text, nullable=False),
)

card_game_reports = Table(
    "card_game_reports", metadata,
    Column("id", Text, primary_key=True),
    Column("student_key", Text, nullable=False),
    Column("data", Text, nullable=False),
    Index("idx_card_game_reports_key", "student_key"),
)

review_sessions = Table(
    "review_sessions", metadata,
    Column("id", Text, primary_key=True),
    Column("student_id", Text, nullable=False),
    Column("date", Text, nullable=False),
    Column("tasks_json", Text, nullable=False),
    Column("completed", Integer, nullable=False, server_default="0"),
    Column("total", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
    Index("idx_review_sessions_student_date", "student_id", "date", unique=True),
)

assignments = Table(
    "assignments", metadata,
    Column("id", Text, primary_key=True),
    Column("teacher_id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("subject", Text),
    Column("grade", Text),
    Column("questions_json", Text, nullable=False),
    Column("assignee_ids_json", Text, nullable=False),
    Column("due_date", Text),
    Column("created_at", Text, nullable=False),
    Index("idx_assignments_teacher", "teacher_id", "created_at"),
)

assignment_submissions = Table(
    "assignment_submissions", metadata,
    Column("id", Text, primary_key=True),
    Column("assignment_id", Text, nullable=False),
    Column("student_id", Text, nullable=False),
    Column("answers_json", Text, nullable=False),
    Column("score", Float),
    Column("status", Text, nullable=False, server_default="submitted"),
    Column("submitted_at", Text, nullable=False),
    Column("teacher_feedback", Text),
    Column("reviewed_at", Text),
    Index("idx_assignment_submissions_assignment", "assignment_id"),
    Index("idx_assignment_submissions_student", "student_id", "assignment_id", unique=True),
)

agent_jobs = Table(
    "agent_jobs", metadata,
    Column("id", Text, primary_key=True),
    Column("job_type", Text, nullable=False),
    Column("actor_id", Text),
    Column("status", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("result_json", Text),
    Column("idempotency_key", Text),
    Column("trace_id", Text),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default="3"),
    Column("timeout_seconds", Integer, nullable=False, server_default="300"),
    Column("cancel_requested", Integer, nullable=False, server_default="0"),
    Column("error", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("started_at", Text),
    Column("finished_at", Text),
    Index("idx_agent_jobs_actor_idempotency", "actor_id", "idempotency_key", unique=True),
    Index("idx_agent_jobs_status_created", "status", "created_at"),
)

student_notifications = Table(
    "student_notifications", metadata,
    Column("id", Text, primary_key=True),
    Column("student_id", Text, nullable=False),
    Column("teacher_id", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("assignment_ids_json", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("read_at", Text),
    Index("idx_student_notifications_student", "student_id", "created_at"),
)

learning_preferences = Table(
    "learning_preferences", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Text, nullable=False, unique=True),
    Column("preferences_json", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

root_cause_records = Table(
    "root_cause_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("student_id", Text, nullable=False),
    Column("knowledge_tag", Text, nullable=False),
    Column("question_text", Text),
    Column("student_answer", Text),
    Column("correct_answer", Text),
    Column("root_cause", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("analyzed_at", Text, nullable=False),
    Index("idx_root_cause_student_tag", "student_id", "knowledge_tag", "analyzed_at"),
)
