from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from db.engine import engine, get_connection
from tracing import current_trace_id, truncate_text

STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
MAX_LIST_ITEMS = 10
MAX_METADATA_CHARS = 1200


class LearningEvent(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    feature: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    grade: str | None = None
    topic: str | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    success: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("student_id")
    @classmethod
    def validate_student_id(cls, value: str) -> str:
        if not STUDENT_ID_RE.match(value):
            raise ValueError("student_id 只能包含字母、数字、下划线、短横线和点。")
        return value


class StudentProfile(BaseModel):
    student_id: str
    grade: str | None = None
    recent_topics: list[str] = Field(default_factory=list)
    recent_lessons: list[dict[str, str]] = Field(default_factory=list)
    weak_topics: list[str] = Field(default_factory=list)
    strong_topics: list[str] = Field(default_factory=list)
    quiz_stats: dict[str, Any] = Field(default_factory=dict)
    game_stats: dict[str, Any] = Field(default_factory=dict)
    character_interests: list[str] = Field(default_factory=list)
    interaction_summary: dict[str, str] = Field(default_factory=dict)
    updated_at: str


class MemoryEntry(BaseModel):
    id: str
    student_id: str
    type: str = Field(min_length=1, max_length=80)
    content: Any
    source_feature: str | None = None
    source_event_id: str | None = None
    confidence: float = Field(default=0.7, ge=0, le=1)
    status: str = "enabled"
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    last_used_at: str | None = None
    disabled_at: str | None = None
    deleted_at: str | None = None


class MemoryEntryUpsert(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=80)
    content: Any
    source_feature: str | None = None
    source_event_id: str | None = None
    confidence: float = Field(default=0.7, ge=0, le=1)
    reason: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("student_id")
    @classmethod
    def validate_student_id(cls, value: str) -> str:
        return validate_student_id_value(value)


VALID_MEMORY_TYPES = {"weak_point", "interest", "learning_preference", "recent_mistake", "teacher_note", "review_goal", "recent_activity"}
VALID_MEMORY_STATUSES = {"enabled", "disabled", "deleted"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS students (
              student_id TEXT PRIMARY KEY, grade TEXT, display_name TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS learning_events (
              id TEXT PRIMARY KEY, student_id TEXT NOT NULL, session_id TEXT,
              feature TEXT NOT NULL, event_type TEXT NOT NULL, grade TEXT,
              topic TEXT, lesson_id TEXT, book_id TEXT, score REAL, success INTEGER,
              metadata_json TEXT NOT NULL, created_at TEXT NOT NULL)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS student_profiles (
              student_id TEXT PRIMARY KEY, grade TEXT,
              recent_topics_json TEXT NOT NULL, recent_lessons_json TEXT NOT NULL,
              weak_topics_json TEXT NOT NULL, strong_topics_json TEXT NOT NULL,
              quiz_stats_json TEXT NOT NULL, game_stats_json TEXT NOT NULL,
              character_interests_json TEXT NOT NULL,
              interaction_summary_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS memory_entries (
              id TEXT PRIMARY KEY, student_id TEXT NOT NULL, type TEXT NOT NULL,
              content_json TEXT NOT NULL, source_feature TEXT, source_event_id TEXT,
              confidence REAL NOT NULL, status TEXT NOT NULL, reason TEXT,
              metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL, last_used_at TEXT,
              disabled_at TEXT, deleted_at TEXT)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS homework_reviews (
              id TEXT PRIMARY KEY, student_id TEXT, actor_id TEXT,
              grade_request_json TEXT NOT NULL, grade_result_json TEXT NOT NULL,
              needs_human_review INTEGER NOT NULL DEFAULT 0,
              decision TEXT NOT NULL DEFAULT 'pending',
              teacher_id TEXT, teacher_note TEXT, teacher_score REAL,
              created_at TEXT NOT NULL, reviewed_at TEXT)"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_learning_events_student_created ON learning_events(student_id, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_memory_entries_student_status ON memory_entries(student_id, status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_memory_entries_source_event ON memory_entries(source_event_id)"))
        # SQLite only: patch older databases missing interaction_summary_json
        if engine.dialect.name == "sqlite":
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(student_profiles)"))}
            if "interaction_summary_json" not in cols:
                conn.execute(text("ALTER TABLE student_profiles ADD COLUMN interaction_summary_json TEXT NOT NULL DEFAULT '{}'"))


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def validate_student_id_value(student_id: str) -> str:
    if not STUDENT_ID_RE.match(student_id):
        raise ValueError("student_id 只能包含字母、数字、下划线、短横线和点。")
    return student_id


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    blocked = {"api_key", "authorization", "auth_header", "token", "password", "secret", "prompt", "essay"}
    for key, value in metadata.items():
        lowered = key.lower()
        if any(part in lowered for part in blocked):
            continue
        if isinstance(value, (dict, list)):
            safe[key] = _json_load(truncate_text(_json_dump(value), MAX_METADATA_CHARS), value if len(_json_dump(value)) <= MAX_METADATA_CHARS else None)
            if safe[key] is None:
                safe[key] = truncate_text(_json_dump(value), MAX_METADATA_CHARS)
        elif isinstance(value, str):
            safe[key] = truncate_text(value, MAX_METADATA_CHARS)
        else:
            safe[key] = value
    return safe


def _prepend_unique(items: list[Any], item: Any, *, limit: int = MAX_LIST_ITEMS) -> list[Any]:
    normalized = [existing for existing in items if existing != item]
    return [item, *normalized][:limit]


def _memory_content_key(content: Any) -> str:
    return hashlib.sha1(_json_dump(content).encode("utf-8")).hexdigest()[:16]


def memory_entry_id(student_id: str, memory_type: str, content: Any) -> str:
    validate_student_id_value(student_id)
    clean_type = re.sub(r"[^A-Za-z0-9_-]+", "_", memory_type)[:32] or "memory"
    return f"mem_{student_id}_{clean_type}_{_memory_content_key(content)}"


def _normalize_memory_type(memory_type: str) -> str:
    normalized = memory_type.strip().lower()
    return normalized if normalized in VALID_MEMORY_TYPES else "learning_preference"


def _memory_from_row(row: Any) -> MemoryEntry:
    return MemoryEntry(
        id=row["id"],
        student_id=row["student_id"],
        type=row["type"],
        content=_json_load(row["content_json"], None),
        source_feature=row["source_feature"],
        source_event_id=row["source_event_id"],
        confidence=float(row["confidence"]),
        status=row["status"],
        reason=row["reason"],
        metadata=_json_load(row["metadata_json"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
        disabled_at=row["disabled_at"],
        deleted_at=row["deleted_at"],
    )


def _profile_from_row(student_id: str, row: Any | None) -> StudentProfile:
    if row is None:
        return StudentProfile(student_id=student_id, updated_at=now_iso())
    return StudentProfile(
        student_id=student_id,
        grade=row["grade"],
        recent_topics=_json_load(row["recent_topics_json"], []),
        recent_lessons=_json_load(row["recent_lessons_json"], []),
        weak_topics=_json_load(row["weak_topics_json"], []),
        strong_topics=_json_load(row["strong_topics_json"], []),
        quiz_stats=_json_load(row["quiz_stats_json"], {}),
        game_stats=_json_load(row["game_stats_json"], {}),
        character_interests=_json_load(row["character_interests_json"], []),
        interaction_summary=_json_load(row.get("interaction_summary_json"), {}),
        updated_at=row["updated_at"],
    )


def _load_profile(conn: Any, student_id: str) -> StudentProfile:
    row = conn.execute(text("SELECT * FROM student_profiles WHERE student_id = :sid"), {"sid": student_id}).mappings().fetchone()
    return _profile_from_row(student_id, row)


def _save_profile(conn: Any, profile: StudentProfile) -> None:
    conn.execute(
        text("""INSERT INTO student_profiles (
            student_id, grade, recent_topics_json, recent_lessons_json, weak_topics_json,
            strong_topics_json, quiz_stats_json, game_stats_json, character_interests_json,
            interaction_summary_json, updated_at
        ) VALUES (
            :student_id, :grade, :recent_topics, :recent_lessons, :weak_topics,
            :strong_topics, :quiz_stats, :game_stats, :char_interests, :interaction, :updated_at
        ) ON CONFLICT(student_id) DO UPDATE SET
            grade = excluded.grade,
            recent_topics_json = excluded.recent_topics_json,
            recent_lessons_json = excluded.recent_lessons_json,
            weak_topics_json = excluded.weak_topics_json,
            strong_topics_json = excluded.strong_topics_json,
            quiz_stats_json = excluded.quiz_stats_json,
            game_stats_json = excluded.game_stats_json,
            character_interests_json = excluded.character_interests_json,
            interaction_summary_json = excluded.interaction_summary_json,
            updated_at = excluded.updated_at"""),
        {
            "student_id": profile.student_id,
            "grade": profile.grade,
            "recent_topics": _json_dump(profile.recent_topics),
            "recent_lessons": _json_dump(profile.recent_lessons),
            "weak_topics": _json_dump(profile.weak_topics),
            "strong_topics": _json_dump(profile.strong_topics),
            "quiz_stats": _json_dump(profile.quiz_stats),
            "game_stats": _json_dump(profile.game_stats),
            "char_interests": _json_dump(profile.character_interests),
            "interaction": _json_dump(profile.interaction_summary),
            "updated_at": profile.updated_at,
        },
    )


def _upsert_student(conn: Any, student_id: str, grade: str | None) -> None:
    timestamp = now_iso()
    conn.execute(
        text("""INSERT INTO students (student_id, grade, display_name, created_at, updated_at)
        VALUES (:student_id, :grade, NULL, :ts, :ts)
        ON CONFLICT(student_id) DO UPDATE SET
            grade = COALESCE(excluded.grade, students.grade),
            updated_at = excluded.updated_at"""),
        {"student_id": student_id, "grade": grade, "ts": timestamp},
    )


def _update_profile(profile: StudentProfile, event: LearningEvent) -> StudentProfile:
    if event.grade:
        profile.grade = event.grade
    if event.topic:
        profile.recent_topics = _prepend_unique(profile.recent_topics, event.topic)
    if event.book_id and event.lesson_id:
        lesson = {"book_id": event.book_id, "lesson_id": event.lesson_id}
        if event.topic:
            lesson["topic"] = event.topic
        profile.recent_lessons = _prepend_unique(profile.recent_lessons, lesson)

    score = event.score
    if event.topic and (event.success is False or (score is not None and score < 0.6)):
        profile.weak_topics = _prepend_unique([item for item in profile.weak_topics if item != event.topic], event.topic)
        profile.strong_topics = [item for item in profile.strong_topics if item != event.topic]
    elif event.topic and (event.success is True or (score is not None and score >= 0.85)):
        profile.strong_topics = _prepend_unique([item for item in profile.strong_topics if item != event.topic], event.topic)
        profile.weak_topics = [item for item in profile.weak_topics if item != event.topic]

    if "quiz" in event.event_type:
        attempts = int(profile.quiz_stats.get("attempts", 0)) + 1
        profile.quiz_stats["attempts"] = attempts
        if score is not None:
            previous = float(profile.quiz_stats.get("average_score", 0))
            profile.quiz_stats["average_score"] = round((previous * (attempts - 1) + score) / attempts, 3)
    if "game" in event.event_type or "timeline" in event.event_type or "card" in event.event_type:
        attempts = int(profile.game_stats.get("attempts", 0)) + 1
        profile.game_stats["attempts"] = attempts
        if score is not None:
            previous = float(profile.game_stats.get("average_score", 0))
            profile.game_stats["average_score"] = round((previous * (attempts - 1) + score) / attempts, 3)

    names = event.metadata.get("characters") or event.metadata.get("character_names") or event.metadata.get("recommendations")
    if isinstance(names, list):
        for name in reversed([item for item in names if isinstance(item, str)]):
            profile.character_interests = _prepend_unique(profile.character_interests, name)
    elif isinstance(names, str):
        profile.character_interests = _prepend_unique(profile.character_interests, names)

    profile.updated_at = now_iso()
    return profile


def _upsert_memory_entry(conn: Any, entry: MemoryEntryUpsert, *, now: str, status: str = "enabled") -> str:
    memory_type = _normalize_memory_type(entry.type)
    memory_id = memory_entry_id(entry.student_id, memory_type, entry.content)
    metadata = _safe_metadata(entry.metadata)
    conn.execute(
        text("""INSERT INTO memory_entries (
            id, student_id, type, content_json, source_feature, source_event_id,
            confidence, status, reason, metadata_json, created_at, updated_at,
            last_used_at, disabled_at, deleted_at
        ) VALUES (
            :id, :student_id, :type, :content, :source_feature, :source_event_id,
            :confidence, :status, :reason, :metadata, :now, :now,
            NULL, NULL, NULL
        ) ON CONFLICT(id) DO UPDATE SET
            source_feature = COALESCE(excluded.source_feature, memory_entries.source_feature),
            source_event_id = COALESCE(excluded.source_event_id, memory_entries.source_event_id),
            confidence = CASE
                WHEN memory_entries.confidence >= excluded.confidence THEN memory_entries.confidence
                ELSE excluded.confidence
            END,
            status = CASE WHEN memory_entries.status IN ('deleted', 'disabled') THEN memory_entries.status ELSE excluded.status END,
            reason = COALESCE(excluded.reason, memory_entries.reason),
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at,
            disabled_at = CASE WHEN excluded.status = 'enabled' THEN NULL ELSE memory_entries.disabled_at END"""),
        {
            "id": memory_id,
            "student_id": entry.student_id,
            "type": memory_type,
            "content": _json_dump(entry.content),
            "source_feature": entry.source_feature,
            "source_event_id": entry.source_event_id,
            "confidence": max(0.0, min(float(entry.confidence), 1.0)),
            "status": status,
            "reason": entry.reason,
            "metadata": _json_dump(metadata),
            "now": now,
        },
    )
    return memory_id


def _record_profile_memories_for_event(conn: Any, event: LearningEvent, *, event_id: str, created_at: str) -> None:
    source = event.feature
    if event.topic and (event.success is False or (event.score is not None and event.score < 0.6)):
        _upsert_memory_entry(conn, MemoryEntryUpsert(
            student_id=event.student_id,
            type="weak_point",
            content=event.topic,
            source_feature=source,
            source_event_id=event_id,
            confidence=0.82,
            reason="学习事件显示该主题需要复习。",
            metadata={"event_type": event.event_type, "score": event.score, "success": event.success},
        ), now=created_at)
    if event.topic:
        _upsert_memory_entry(conn, MemoryEntryUpsert(
            student_id=event.student_id,
            type="recent_activity",
            content=event.topic,
            source_feature=source,
            source_event_id=event_id,
            confidence=0.68,
            reason="最近学习或提问涉及该主题。",
            metadata={"event_type": event.event_type},
        ), now=created_at)
    names = event.metadata.get("characters") or event.metadata.get("character_names") or event.metadata.get("recommendations")
    if isinstance(names, str):
        names = [names]
    if isinstance(names, list):
        for name in [item for item in names if isinstance(item, str) and item.strip()][:5]:
            _upsert_memory_entry(conn, MemoryEntryUpsert(
                student_id=event.student_id,
                type="interest",
                content=name.strip(),
                source_feature=source,
                source_event_id=event_id,
                confidence=0.74,
                reason="学生近期与该历史人物互动或收到相关推荐。",
                metadata={"event_type": event.event_type},
            ), now=created_at)


def record_learning_event(event: LearningEvent) -> str | None:
    init_db()
    metadata = dict(event.metadata)
    trace_id = current_trace_id()
    if trace_id and "trace_id" not in metadata:
        metadata["trace_id"] = trace_id
    event = LearningEvent.model_validate({**event.model_dump(), "metadata": _safe_metadata(metadata)})
    event_id = uuid4().hex
    created_at = now_iso()
    with get_connection() as conn:
        _upsert_student(conn, event.student_id, event.grade)
        conn.execute(
            text("""INSERT INTO learning_events (
                id, student_id, session_id, feature, event_type, grade, topic, lesson_id,
                book_id, score, success, metadata_json, created_at
            ) VALUES (
                :id, :student_id, :session_id, :feature, :event_type, :grade, :topic, :lesson_id,
                :book_id, :score, :success, :metadata, :created_at
            )"""),
            {
                "id": event_id,
                "student_id": event.student_id,
                "session_id": event.session_id,
                "feature": event.feature,
                "event_type": event.event_type,
                "grade": event.grade,
                "topic": event.topic,
                "lesson_id": event.lesson_id,
                "book_id": event.book_id,
                "score": event.score,
                "success": None if event.success is None else int(event.success),
                "metadata": _json_dump(event.metadata),
                "created_at": created_at,
            },
        )
        profile = _update_profile(_load_profile(conn, event.student_id), event)
        _save_profile(conn, profile)
        _record_profile_memories_for_event(conn, event, event_id=event_id, created_at=created_at)
    return event_id


def try_record_learning_event(event: LearningEvent) -> str | None:
    try:
        return record_learning_event(event)
    except Exception:
        return None


def get_student_profile(student_id: str) -> StudentProfile:
    validate_student_id_value(student_id)
    init_db()
    with get_connection() as conn:
        return _load_profile(conn, student_id)


def upsert_memory_entry(entry: MemoryEntryUpsert) -> str:
    init_db()
    now = now_iso()
    with get_connection() as conn:
        _upsert_student(conn, entry.student_id, None)
        return _upsert_memory_entry(conn, entry, now=now)


def list_memory_entries(
    student_id: str,
    *,
    limit: int = 100,
    status: str | None = "enabled",
    memory_type: str | None = None,
    include_deleted: bool = False,
) -> list[MemoryEntry]:
    validate_student_id_value(student_id)
    init_db()
    filters = ["student_id = :student_id"]
    params: dict[str, Any] = {"student_id": student_id}
    if memory_type:
        filters.append("type = :memory_type")
        params["memory_type"] = _normalize_memory_type(memory_type)
    if status:
        if status not in VALID_MEMORY_STATUSES:
            raise ValueError("memory status 无效。")
        filters.append("status = :status")
        params["status"] = status
    elif not include_deleted:
        filters.append("status != 'deleted'")
    params["limit"] = max(1, min(int(limit), 500))
    with get_connection() as conn:
        rows = conn.execute(
            text(f"""SELECT * FROM memory_entries
            WHERE {' AND '.join(filters)}
            ORDER BY COALESCE(last_used_at, updated_at, created_at) DESC, created_at DESC
            LIMIT :limit"""),
            params,
        ).mappings().fetchall()
    return [_memory_from_row(row) for row in rows]


def get_memory_entry(student_id: str, memory_id: str) -> MemoryEntry | None:
    validate_student_id_value(student_id)
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM memory_entries WHERE id = :id AND student_id = :student_id"),
            {"id": memory_id, "student_id": student_id},
        ).mappings().fetchone()
    return _memory_from_row(row) if row else None


def set_memory_entry_status(memory_id: str, student_id: str, status: str) -> bool:
    if status not in {"enabled", "disabled", "deleted"}:
        raise ValueError("memory status 无效。")
    validate_student_id_value(student_id)
    init_db()
    timestamp = now_iso()
    disabled_at = timestamp if status == "disabled" else None
    deleted_at = timestamp if status == "deleted" else None
    with get_connection() as conn:
        result = conn.execute(
            text("""UPDATE memory_entries
            SET status = :status, updated_at = :ts,
                disabled_at = CASE WHEN :disabled_at IS NOT NULL THEN :disabled_at WHEN :status = 'enabled' THEN NULL ELSE disabled_at END,
                deleted_at = CASE WHEN :deleted_at IS NOT NULL THEN :deleted_at ELSE deleted_at END
            WHERE id = :id AND student_id = :student_id AND status != 'deleted'"""),
            {"status": status, "ts": timestamp, "disabled_at": disabled_at,
             "deleted_at": deleted_at, "id": memory_id, "student_id": student_id},
        )
        return result.rowcount > 0


def mark_memory_entries_used(student_id: str, memory_ids: list[str]) -> int:
    validate_student_id_value(student_id)
    ids = [memory_id for memory_id in dict.fromkeys(memory_ids) if memory_id]
    if not ids:
        return 0
    init_db()
    timestamp = now_iso()
    id_params = {f"id{i}": v for i, v in enumerate(ids)}
    placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
    with get_connection() as conn:
        result = conn.execute(
            text(f"UPDATE memory_entries SET last_used_at = :ts, updated_at = :ts WHERE student_id = :student_id AND status = 'enabled' AND id IN ({placeholders})"),
            {"ts": timestamp, "student_id": student_id, **id_params},
        )
        return result.rowcount


def ensure_profile_memory_entries(student_id: str) -> list[MemoryEntry]:
    profile = get_student_profile(student_id)
    now = now_iso()
    with get_connection() as conn:
        for topic in profile.weak_topics[:MAX_LIST_ITEMS]:
            _upsert_memory_entry(conn, MemoryEntryUpsert(
                student_id=student_id, type="weak_point", content=topic,
                source_feature="student_profile", confidence=0.78,
                reason="由学生画像中的薄弱主题迁移生成。",
            ), now=now)
        for topic in profile.recent_topics[:MAX_LIST_ITEMS]:
            _upsert_memory_entry(conn, MemoryEntryUpsert(
                student_id=student_id, type="recent_activity", content=topic,
                source_feature="student_profile", confidence=0.62,
                reason="由学生画像中的最近主题迁移生成。",
            ), now=now)
        for character in profile.character_interests[:MAX_LIST_ITEMS]:
            _upsert_memory_entry(conn, MemoryEntryUpsert(
                student_id=student_id, type="interest", content=character,
                source_feature="student_profile", confidence=0.72,
                reason="由学生画像中的人物兴趣迁移生成。",
            ), now=now)
    return list_memory_entries(student_id, limit=100, status="enabled")


_NON_HISTORY_PATTERNS = tuple('出题 练习题 选择题 简答题 推荐 来一局 帮我 用一句话 选择教材 游戏 时间线'.split())

def _is_history_topic(topic: str) -> bool:
    return len(topic) <= 20 and not any(p in topic for p in _NON_HISTORY_PATTERNS)

def suggest_review_plan(student_id: str, *, limit: int = 5) -> dict[str, Any]:
    profile = get_student_profile(student_id)
    actions: list[str] = []
    valid_recent = [t for t in profile.recent_topics if _is_history_topic(t)]
    for topic in profile.weak_topics[:limit]:
        actions.append('复习"' + topic + '"，再完成3道相关练习题。')
    for topic in valid_recent[:limit]:
        if len(actions) >= limit:
            break
        actions.append('用一句话解释"' + topic + '"的原因、经过和影响。')
    if profile.character_interests and len(actions) < limit:
        actions.append('继续和' + profile.character_interests[0] + '对话，追问一个教材相关问题。')
    if not actions:
        actions.append('先选择一个正在学习的历史主题，完成一次问答或练习。')

    # 计算学习进度（简化版）
    progress = {}
    for topic in profile.weak_topics:
        progress[topic] = 0.5  # 默认中等进度
    for topic in profile. strong_topics:
        progress[topic] = 0.8  # 优势点进度较高

    return {
        'student_id': student_id,
        'weak_topics': profile.weak_topics[:limit],
        'recent_topics': valid_recent[:limit],
        'recommended_actions': actions[:limit],
        'next_questions': [(topic + '为什么重要？') for topic in valid_recent[: min(3, limit)]],
        'progress': progress,
    }


def list_learning_events(
    *,
    limit: int = 100,
    student_id: str | None = None,
    feature: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    init_db()
    filters = []
    params: dict[str, Any] = {}
    if student_id:
        filters.append("student_id = :student_id")
        params["student_id"] = validate_student_id_value(student_id)
    if feature:
        filters.append("feature = :feature")
        params["feature"] = feature
    if event_type:
        filters.append("event_type = :event_type")
        params["event_type"] = event_type
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params["limit"] = max(1, min(int(limit), 500))
    with get_connection() as conn:
        rows = conn.execute(
            text(f"SELECT * FROM learning_events {where} ORDER BY created_at DESC LIMIT :limit"),
            params,
        ).mappings().fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["success"] = None if item["success"] is None else bool(item["success"])
        item["metadata"] = _json_load(item.pop("metadata_json"), {})
        events.append(item)
    return events


def delete_learning_event(event_id: str, student_id: str) -> bool:
    """Delete a learning event. Returns True if a row was deleted."""
    init_db()
    with get_connection() as conn:
        result = conn.execute(
            text("DELETE FROM learning_events WHERE id = :id AND student_id = :student_id"),
            {"id": event_id, "student_id": validate_student_id_value(student_id)},
        )
        return result.rowcount > 0
