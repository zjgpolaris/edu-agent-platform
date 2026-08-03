"""Timeline 游戏流程：启动轮次、提交答案、生成记录。"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from random import shuffle
from typing import Any
from uuid import uuid4
from agents.card_game import generate_card_game_round, generate_retry_explanation
from agents.timeline_question_generator import (
    event_count_for_difficulty,
    generate_timeline_round_from_corpus,
    generate_timeline_round_with_llm,
)
from agents.history_games_pkg._types import (
    TimelineDifficulty, TimelineEventInternal,
    TimelineLevel, TimelineRoundRecord,
)
from agents.history_games_pkg._catalog import TIMELINE_LEVELS
from agents.history_games_pkg._utils import (
    choose_level, normalize_difficulty, public_event,
    validate_submission, build_learning_tip, student_key,
)
from game_store import cleanup_expired_rounds, get_wrong_records, load_round, save_round, save_wrong_records
from services.weakpoint_service import record_weakpoint

def list_history_games() -> list[HistoryGameDefinition]:
    return HISTORY_GAMES


def start_timeline_round(
    grade: str | None = None,
    difficulty: str = "easy",
    topic: str | None = None,
    student_id: str | None = None,
    mode: str = "llm",
) -> dict:
    cleanup_expired_rounds()
    normalized_difficulty = normalize_difficulty(difficulty)
    normalized_mode = (mode or "llm").strip().lower()
    if normalized_mode not in {"llm", "static"}:
        raise ValueError("不支持的时间线出题模式，请选择 llm 或 static。")

    if normalized_mode == "static":
        return create_static_timeline_round(grade, normalized_difficulty, topic, student_id, fallback_used=False, generation_reason="mode=static")

    try:
        generated_round = generate_timeline_round_from_corpus(
            grade=grade,
            difficulty=normalized_difficulty,
            topic=topic,
            student_id=student_id,
            recent_store=TIMELINE_RECENT_EVENTS,
        )
        return create_timeline_round_record(
            level_id="llm-dynamic",
            title=generated_round["title"],
            grade=generated_round["grade"],
            difficulty=normalized_difficulty,
            topic=generated_round["topic"],
            events=generated_round["events"],
            source="llm",
            fallback_used=False,
            generation_reason=None,
            learning_goal=generated_round.get("learning_goal"),
            student_id=student_id,
        )
    except Exception as exc:
        logger.warning(
            "timeline_round_fallback difficulty=%s topic=%s reason=%s",
            normalized_difficulty,
            topic,
            str(exc),
        )
        return create_static_timeline_round(grade, normalized_difficulty, topic, student_id, fallback_used=True, generation_reason=str(exc))


def create_static_timeline_round(
    grade: str | None,
    difficulty: TimelineDifficulty,
    topic: str | None,
    student_id: str | None,
    fallback_used: bool,
    generation_reason: str | None,
) -> dict:
    level = choose_level(grade, difficulty, topic)
    return create_timeline_round_record(
        level_id=level["id"],
        title=level["title"],
        grade=level["grade"],
        difficulty=level["difficulty"],
        topic=level["topic"],
        events=[event.copy() for event in level["events"]],
        source="static",
        fallback_used=fallback_used,
        generation_reason=generation_reason,
        learning_goal=None,
        student_id=student_id,
    )


def create_timeline_round_record(
    *,
    level_id: str,
    title: str,
    grade: str,
    difficulty: TimelineDifficulty,
    topic: str,
    events: list[TimelineEventInternal] | list[dict[str, Any]],
    source: Literal["llm", "static"],
    fallback_used: bool,
    generation_reason: str | None,
    learning_goal: str | None,
    student_id: str | None,
) -> dict:
    round_events = [event.copy() for event in events]
    correct_order = [event["id"] for event in sorted(round_events, key=lambda item: item["year"])]
    shuffled_events = round_events.copy()
    shuffle(shuffled_events)
    if [event["id"] for event in shuffled_events] == correct_order and len(shuffled_events) > 1:
        shuffled_events[0], shuffled_events[1] = shuffled_events[1], shuffled_events[0]

    round_id = f"timeline-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    record: TimelineRoundRecord = {
        "round_id": round_id,
        "level_id": level_id,
        "title": title,
        "grade": grade,
        "difficulty": difficulty,
        "topic": topic,
        "events": round_events,  # type: ignore[typeddict-item]
        "correct_order": correct_order,
        "created_at": datetime.now(timezone.utc),
        "source": source,
        "fallback_used": fallback_used,
        "generation_reason": generation_reason,
        "learning_goal": learning_goal,
        "student_id": student_id,
    }
    save_round(round_id, "timeline", record)

    return {
        "round_id": round_id,
        "title": title,
        "round_title": title,
        "learning_goal": learning_goal,
        "grade": grade,
        "difficulty": difficulty,
        "topic": topic,
        "events": [public_event(event) for event in shuffled_events],
        "source": source,
        "fallback_used": fallback_used,
    }


def submit_timeline_round(round_id: str, ordered_event_ids: list[str]) -> dict:
    cleanup_expired_rounds()
    record = load_round(round_id)
    if not record:
        raise LookupError("时间线回合不存在或已过期，请重新开始一局。")

    correct_order = record["correct_order"]
    validate_submission(correct_order, ordered_event_ids)

    events_by_id = {event["id"]: event for event in record["events"]}
    correct_index_by_id = {event_id: index for index, event_id in enumerate(correct_order)}
    submitted_index_by_id = {event_id: index for index, event_id in enumerate(ordered_event_ids)}
    score = sum(
        1 for index, event_id in enumerate(ordered_event_ids)
        if correct_order[index] == event_id
    )

    items = []
    for event_id in ordered_event_ids:
        event = events_by_id[event_id]
        correct_index = correct_index_by_id[event_id]
        submitted_index = submitted_index_by_id[event_id]
        is_correct = correct_index == submitted_index
        items.append({
            "event_id": event_id,
            "title": event["title"],
            "display_year": event["display_year"],
            "period": event["period"],
            "is_correct_position": is_correct,
            "correct_index": correct_index,
            "submitted_index": submitted_index,
            "explanation": event["explanation"],
            "related_character": event["related_character"],
            "suggested_question": event["suggested_question"],
        })
        if not is_correct and record.get("student_id"):
            record_weakpoint(record["student_id"], event.get("topic", event["title"]), "timeline_game")

    return {
        "round_id": round_id,
        "score": score,
        "total": len(correct_order),
        "correct_order": correct_order,
        "submitted_order": ordered_event_ids,
        "items": items,
        "learning_tip": build_learning_tip(score, len(correct_order), record),
        "source": record["source"],
        "fallback_used": record["fallback_used"],
        "grade": record["grade"],
        "topic": record["topic"],
        "difficulty": record["difficulty"],
        "student_id": record.get("student_id"),
    }


