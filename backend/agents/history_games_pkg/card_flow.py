"""Card Game 流程：启动轮次、提交/重试答案、报告生成。"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from random import shuffle
from typing import Any
from uuid import uuid4
from agents.card_game import generate_card_game_round, generate_retry_explanation
from agents.history_games_pkg._types import (
    TimelineDifficulty, TimelineEventInternal, CardGameRoundRecord,
)
from agents.history_games_pkg._catalog import TIMELINE_LEVELS
from agents.history_games_pkg._utils import (
    choose_level, normalize_difficulty, public_card,
    validate_submission, build_card_game_learning_tip,
    build_card_game_report_tip, student_key,
)
from game_store import (
    append_card_game_report, cleanup_expired_rounds, get_card_game_reports,
    get_wrong_records, load_round, save_round, save_wrong_records,
)
from services.weakpoint_service import record_weakpoint

def start_card_game_round(
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
        raise ValueError("不支持的卡牌游戏出题模式，请选择 llm 或 static。")

    wrong_card_ids = get_wrong_records(student_key(student_id))
    if normalized_mode == "static":
        return create_static_card_game_round(
            grade,
            normalized_difficulty,
            topic,
            student_id,
            fallback_used=False,
            generation_reason="mode=static",
        )

    try:
        generated_round = generate_card_game_round(
            levels=TIMELINE_LEVELS,  # type: ignore[arg-type]
            grade=grade,
            difficulty=normalized_difficulty,
            topic=topic,
            student_id=student_id,
            recent_store=CARD_GAME_RECENT_EVENTS,
            wrong_card_ids=wrong_card_ids,
        )
        return create_card_game_round_record(
            title=generated_round["title"],
            grade=generated_round["grade"],
            difficulty=normalized_difficulty,
            topic=generated_round["topic"],
            cards=generated_round["events"],
            source="llm",
            fallback_used=False,
            generation_reason=None,
            learning_goal=generated_round.get("learning_goal"),
            student_id=student_id,
        )
    except Exception as exc:
        logger.warning(
            "card_game_round_fallback difficulty=%s topic=%s reason=%s",
            normalized_difficulty,
            topic,
            str(exc),
        )
        return create_static_card_game_round(
            grade,
            normalized_difficulty,
            topic,
            student_id,
            fallback_used=True,
            generation_reason=str(exc),
        )


def create_static_card_game_round(
    grade: str | None,
    difficulty: TimelineDifficulty,
    topic: str | None,
    student_id: str | None,
    fallback_used: bool,
    generation_reason: str | None,
) -> dict:
    level = choose_level(grade, difficulty, topic)
    target_count = event_count_for_difficulty(difficulty)
    cards = [event.copy() for event in level["events"][:target_count]]
    return create_card_game_round_record(
        title=f"{level['title']} · 时间巨轮",
        grade=level["grade"],
        difficulty=difficulty,
        topic=level["topic"],
        cards=cards,
        source="static",
        fallback_used=fallback_used,
        generation_reason=generation_reason,
        learning_goal="根据卡牌线索判断事件先后，训练历史时间观念。",
        student_id=student_id,
    )


def create_card_game_round_record(
    *,
    title: str,
    grade: str,
    difficulty: TimelineDifficulty,
    topic: str,
    cards: list[TimelineEventInternal] | list[dict[str, Any]],
    source: Literal["llm", "static"],
    fallback_used: bool,
    generation_reason: str | None,
    learning_goal: str | None,
    student_id: str | None,
) -> dict:
    round_cards = [card.copy() for card in cards]
    correct_order = [card["id"] for card in sorted(round_cards, key=lambda item: item["year"])]
    shuffled_cards = round_cards.copy()
    shuffle(shuffled_cards)
    if [card["id"] for card in shuffled_cards] == correct_order and len(shuffled_cards) > 1:
        shuffled_cards[0], shuffled_cards[1] = shuffled_cards[1], shuffled_cards[0]

    round_id = f"card-game-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    record: CardGameRoundRecord = {
        "round_id": round_id,
        "title": title,
        "grade": grade,
        "difficulty": difficulty,
        "topic": topic,
        "cards": round_cards,  # type: ignore[typeddict-item]
        "correct_order": correct_order,
        "created_at": datetime.now(timezone.utc),
        "learning_goal": learning_goal,
        "retry_used": False,
        "source": source,
        "fallback_used": fallback_used,
        "generation_reason": generation_reason,
        "student_id": student_id,
    }
    save_round(round_id, "card_game", record)

    return {
        "round_id": round_id,
        "title": title,
        "learning_goal": learning_goal,
        "grade": grade,
        "topic": topic,
        "difficulty": difficulty,
        "cards": [public_card(card) for card in shuffled_cards],
        "slot_count": len(shuffled_cards),
        "source": source,
        "fallback_used": fallback_used,
    }


def submit_card_game_round(round_id: str, submitted_card_ids: list[str]) -> dict:
    cleanup_expired_rounds()
    record = load_round(round_id)
    if not record:
        raise LookupError("卡牌游戏回合不存在或已过期，请重新开始一局。")

    result = build_card_game_result(record, submitted_card_ids, can_retry=not record["retry_used"])
    persist_card_game_result(record, result, is_retry=False)
    return result


def retry_card_game_round(round_id: str, revised_card_ids: list[str]) -> dict:
    cleanup_expired_rounds()
    record = load_round(round_id)
    if not record:
        raise LookupError("卡牌游戏回合不存在或已过期，请重新开始一局。")
    if record["retry_used"]:
        raise ValueError("本局修正机会已经使用，请开启下一局。")

    record["retry_used"] = True
    save_round(record["round_id"], "card_game", record)
    result = build_card_game_result(record, revised_card_ids, can_retry=False)
    wrong_items = [item for item in result["items"] if not item["is_correct"]]
    retry_explanations = generate_retry_explanation(wrong_items, f"{record['title']} / {record['topic']}")
    for item in result["items"]:
        if item["card_id"] in retry_explanations:
            item["explanation"] = retry_explanations[item["card_id"]]
    persist_card_game_result(record, result, is_retry=True)
    return result


def build_card_game_result(record: CardGameRoundRecord, submitted_card_ids: list[str], can_retry: bool) -> dict:
    correct_order = record["correct_order"]
    validate_submission(correct_order, submitted_card_ids)

    cards_by_id = {card["id"]: card for card in record["cards"]}
    correct_index_by_id = {card_id: index for index, card_id in enumerate(correct_order)}
    submitted_index_by_id = {card_id: index for index, card_id in enumerate(submitted_card_ids)}
    score = sum(1 for index, card_id in enumerate(submitted_card_ids) if correct_order[index] == card_id)

    items = []
    for card_id in submitted_card_ids:
        card = cards_by_id[card_id]
        correct_index = correct_index_by_id[card_id]
        submitted_index = submitted_index_by_id[card_id]
        is_correct = correct_index == submitted_index
        items.append(
            {
                "card_id": card_id,
                "title": card["title"],
                "display_year": card["display_year"],
                "period": card["period"],
                "is_correct": is_correct,
                "correct_slot": correct_index,
                "submitted_slot": submitted_index,
                "explanation": card["explanation"],
                "follow_up_question": card["suggested_question"],
            }
        )
        if not is_correct and record.get("student_id"):
            record_weakpoint(record["student_id"], card.get("topic", card["title"]), "card_game")

    return {
        "round_id": record["round_id"],
        "score": score,
        "total": len(correct_order),
        "can_retry": can_retry,
        "items": items,
        "learning_tip": build_card_game_learning_tip(score, len(correct_order), record),
        "correct_order": correct_order,
        "submitted_order": submitted_card_ids,
        "student_id": record.get("student_id"),
        "grade": record.get("grade"),
        "topic": record.get("topic"),
        "difficulty": record.get("difficulty"),
    }


def persist_card_game_result(record: CardGameRoundRecord, result: dict, is_retry: bool) -> None:
    key = student_key(record.get("student_id"))
    wrong_ids = [item["card_id"] for item in result["items"] if not item["is_correct"]]
    if wrong_ids:
        existing = get_wrong_records(key)
        save_wrong_records(key, [*wrong_ids, *[c for c in existing if c not in wrong_ids]][:30])

    append_card_game_report(key, {
        "round_id": record["round_id"],
        "title": record["title"],
        "topic": record["topic"],
        "difficulty": record["difficulty"],
        "score": result["score"],
        "total": result["total"],
        "wrong_card_ids": wrong_ids,
        "is_retry": is_retry,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def get_card_game_report(student_id: str) -> dict:
    key = student_key(student_id)
    reports = get_card_game_reports(key)
    wrong_card_ids = get_wrong_records(key)
    total_rounds = len(reports)
    total_cards = sum(r["total"] for r in reports)
    total_score = sum(r["score"] for r in reports)
    recent_reports = reports[-8:]
    return {
        "student_id": student_id,
        "rounds_played": total_rounds,
        "total_score": total_score,
        "total_cards": total_cards,
        "accuracy": round(total_score / total_cards, 2) if total_cards else 0,
        "wrong_card_ids": wrong_card_ids,
        "recent_rounds": recent_reports,
        "review_tip": build_card_game_report_tip(total_score, total_cards, wrong_card_ids),
        "next_recommendation": "下一局会优先复现最近错过的事件卡。" if wrong_card_ids else "可以尝试更高难度或切换专题，扩大时间线覆盖面。",
    }


