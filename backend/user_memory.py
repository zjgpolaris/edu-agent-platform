"""长期用户记忆便捷接口 — 基于 student_profile 的封装。"""
from __future__ import annotations

import time
from datetime import datetime
from typing import TypedDict

from rag.knowledge_base import MetadataHints
from student_profile import (
    LearningEvent,
    MemoryEntryUpsert,
    ensure_profile_memory_entries,
    get_student_profile,
    list_memory_entries,
    mark_memory_entries_used,
    try_record_learning_event,
    upsert_memory_entry,
)


class UserMemory(TypedDict, total=False):
    student_id: str
    favorite_characters: list[str]
    weak_topics: list[str]
    interaction_summary: dict[str, str]  # character -> summary
    updated_at: float


_MEMORY_TTL_DAYS = 30
_MEMORY_TTL_SECONDS = _MEMORY_TTL_DAYS * 24 * 3600


def _updated_at_timestamp(updated_at: float | str | None) -> float:
    if updated_at is None:
        return 0.0
    if isinstance(updated_at, (int, float)):
        return float(updated_at)
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _is_memory_expired(updated_at: float | str | None) -> bool:
    """Check if memory entry is older than TTL."""
    ts = _updated_at_timestamp(updated_at)
    return ts <= 0 or time.time() - ts > _MEMORY_TTL_SECONDS


def get_memory(student_id: str) -> UserMemory:
    """Load user memory from student_profile and clean expired entries."""
    try:
        profile = get_student_profile(student_id)
        if not profile:
            return UserMemory(student_id=student_id, favorite_characters=[], weak_topics=[], interaction_summary={}, updated_at=0)

        if _is_memory_expired(profile.updated_at):
            mem = UserMemory(
                student_id=student_id,
                favorite_characters=[],
                weak_topics=profile.weak_topics or [],
                interaction_summary={},
                updated_at=time.time(),
            )
            save_memory(mem)
            return mem

        return UserMemory(
            student_id=student_id,
            favorite_characters=profile.character_interests or [],
            weak_topics=profile.weak_topics or [],
            interaction_summary=profile.interaction_summary or {},
            updated_at=_updated_at_timestamp(profile.updated_at),
        )
    except Exception:
        return UserMemory(student_id=student_id, favorite_characters=[], weak_topics=[], interaction_summary={}, updated_at=0)


def save_memory(mem: UserMemory) -> None:
    """Save user memory back to student_profile."""
    try:
        from student_profile import init_db, now_iso, get_student_profile, StudentProfile, _json_dump
        from db.engine import get_connection
        from sqlalchemy import text
        init_db()
        profile = get_student_profile(mem["student_id"]) or StudentProfile(
            student_id=mem["student_id"],
            updated_at=now_iso(),
        )
        profile.character_interests = mem.get("favorite_characters", [])
        profile.weak_topics = mem.get("weak_topics", [])
        profile.interaction_summary = mem.get("interaction_summary", {})
        profile.updated_at = now_iso()

        with get_connection() as conn:
            conn.execute(
                text("""INSERT INTO student_profiles (
                    student_id, grade, recent_topics_json, recent_lessons_json, weak_topics_json,
                    strong_topics_json, quiz_stats_json, game_stats_json, character_interests_json,
                    interaction_summary_json, updated_at
                ) VALUES (
                    :student_id, :grade, :recent_topics, :recent_lessons, :weak_topics,
                    :strong_topics, :quiz_stats, :game_stats, :char_interests, :interaction, :updated_at
                ) ON CONFLICT(student_id) DO UPDATE SET
                    character_interests_json = excluded.character_interests_json,
                    weak_topics_json = excluded.weak_topics_json,
                    interaction_summary_json = excluded.interaction_summary_json,
                    updated_at = excluded.updated_at"""),
                {
                    "student_id": profile.student_id,
                    "grade": profile.grade,
                    "recent_topics": _json_dump(profile.recent_topics or []),
                    "recent_lessons": _json_dump(profile.recent_lessons or []),
                    "weak_topics": _json_dump(profile.weak_topics or []),
                    "strong_topics": _json_dump(profile.strong_topics or []),
                    "quiz_stats": _json_dump(profile.quiz_stats or {}),
                    "game_stats": _json_dump(profile.game_stats or {}),
                    "char_interests": _json_dump(profile.character_interests),
                    "interaction": _json_dump(profile.interaction_summary),
                    "updated_at": profile.updated_at,
                },
            )
    except Exception:
        pass


def update_memory_after_chat(student_id: str, character: str, messages: list, grade: str | None = None) -> None:
    """Update memory after a character chat interaction."""
    if not student_id:
        return

    mem = get_memory(student_id)

    # Add to favorite characters if not already present
    favorites = mem.get("favorite_characters", [])
    if character not in favorites:
        favorites.append(character)
        mem["favorite_characters"] = favorites[:10]  # Keep top 10

    # Update interaction summary if >= 10 messages
    if len(messages) >= 10:
        from llm_config import llm_fast
        try:
            history = "\n".join(f"{m.get('role', 'user')}: {str(m.get('content', ''))[:200]}" for m in messages[-10:])
            prompt = f"用50字以内概括以下历史人物对话的关键内容：\n{history}"
            resp = llm_fast.invoke([{"role": "user", "content": prompt}])
            summary = resp.content.strip()[:100]
            mem.setdefault("interaction_summary", {})[character] = summary
        except Exception:
            pass

    mem["updated_at"] = time.time()
    save_memory(mem)
    record_typed_memory(
        student_id,
        memory_type="interest",
        content=character,
        source_feature="history_character",
        confidence=0.76,
        reason="学生近期与该历史人物对话。",
        metadata={"grade": grade},
    )
    if mem.get("interaction_summary", {}).get(character):
        record_typed_memory(
            student_id,
            memory_type="learning_preference",
            content={"character": character, "summary": mem["interaction_summary"][character]},
            source_feature="history_character",
            confidence=0.64,
            reason="由较长历史人物对话摘要生成。",
            metadata={"grade": grade},
        )


def get_character_interests(student_id: str | None) -> list[str]:
    if not student_id:
        return []
    try:
        profile = get_student_profile(student_id)
        return profile.character_interests if profile else []
    except Exception:
        return []


def get_used_memory_entries(student_id: str | None, *, limit: int = 6) -> list[dict]:
    if not student_id:
        return []
    try:
        entries = ensure_profile_memory_entries(student_id)
    except Exception:
        try:
            entries = list_memory_entries(student_id, limit=limit, status="enabled")
        except Exception:
            return []
    used = []
    for entry in entries[:limit]:
        reason = entry.reason or "用于个性化学习建议。"
        if entry.type == "weak_point":
            reason = "用于优先生成复习建议。"
        elif entry.type == "recent_activity":
            reason = "用于推荐可继续追问的历史主题。"
        elif entry.type == "interest":
            reason = "用于个性化历史人物对话建议。"
        used.append({
            "memory_id": entry.id,
            "type": entry.type,
            "content": entry.content,
            "reason": reason,
            "source_feature": entry.source_feature,
            "confidence": entry.confidence,
            "last_used_at": entry.last_used_at,
            "created_at": entry.created_at,
        })
    try:
        mark_memory_entries_used(student_id, [item["memory_id"] for item in used])
    except Exception:
        pass
    return used


def record_typed_memory(
    student_id: str,
    *,
    memory_type: str,
    content,
    source_feature: str | None = None,
    confidence: float = 0.7,
    reason: str | None = None,
    metadata: dict | None = None,
) -> str | None:
    try:
        return upsert_memory_entry(MemoryEntryUpsert(
            student_id=student_id,
            type=memory_type,
            content=content,
            source_feature=source_feature,
            confidence=confidence,
            reason=reason,
            metadata=metadata or {},
        ))
    except Exception:
        return None


def enrich_hints_with_memory(
    hints: MetadataHints,
    student_id: str | None,
) -> MetadataHints:
    interests = get_character_interests(student_id)
    if not interests:
        return hints
    existing_topics = hints.get("topic", [])
    if isinstance(existing_topics, str):
        existing_topics = [existing_topics]
    hints["topic"] = list(dict.fromkeys([*existing_topics, *interests[:3]]))
    return hints


def record_character_interaction(student_id: str | None, character: str, grade: str | None = None) -> None:
    if not student_id:
        return
    try:
        try_record_learning_event(
            LearningEvent(
                student_id=student_id,
                feature="history_character",
                event_type="character_chat",
                grade=grade,
                topic=character,
                metadata={"characters": [character]},
            )
        )
    except Exception:
        pass
