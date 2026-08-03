"""共享辅助函数：数据序列化、难度规范化、关卡选择、校验和学习提示。"""
from __future__ import annotations
from random import choice
from agents.history_games_pkg._types import (
    TimelineDifficulty, TimelineEventInternal,
    TimelineLevel, TimelineRoundRecord, CardGameRoundRecord,
)
from agents.history_games_pkg._catalog import TIMELINE_LEVELS

def public_event(event: TimelineEventInternal) -> dict:
    return {
        "id": event["id"],
        "title": event["title"],
        "period": event["period"],
        "summary": event["summary"],
        "topic": event["topic"],
    }


def public_card(card: TimelineEventInternal) -> dict:
    return {
        "id": card["id"],
        "card_type": "event",
        "title": card["title"],
        "period": card["period"],
        "clue": card["summary"],
        "topic": card["topic"],
    }


def normalize_difficulty(difficulty: str) -> TimelineDifficulty:
    aliases = {"standard": "normal", "challenge": "hard"}
    normalized = aliases.get((difficulty or "easy").strip().lower(), (difficulty or "easy").strip().lower())
    if normalized in {"easy", "normal", "hard"}:
        return normalized  # type: ignore[return-value]
    raise ValueError("不支持的时间线难度，请选择 easy、normal、hard、standard 或 challenge。")


def choose_level(
    grade: str | None,
    difficulty: TimelineDifficulty,
    topic: str | None,
) -> TimelineLevel:
    candidates = TIMELINE_LEVELS
    if topic:
        topic_matches = [level for level in candidates if topic in level["topic"] or level["topic"] in topic]
        if topic_matches:
            candidates = topic_matches
    if grade:
        grade_matches = [level for level in candidates if grade in level["grade"]]
        if grade_matches:
            candidates = grade_matches
    difficulty_matches = [level for level in candidates if level["difficulty"] == difficulty]
    if difficulty_matches:
        candidates = difficulty_matches
    return choice(candidates)


def validate_submission(correct_order: list[str], ordered_event_ids: list[str]) -> None:
    if len(ordered_event_ids) != len(correct_order):
        raise ValueError("提交的事件数量不完整，请确认所有事件都已排序。")
    if len(set(ordered_event_ids)) != len(ordered_event_ids):
        raise ValueError("提交中存在重复事件，请重新调整顺序。")
    if set(ordered_event_ids) != set(correct_order):
        raise ValueError("提交中包含不属于本局的事件，请重新开始一局。")


def build_learning_tip(score: int, total: int, record: TimelineRoundRecord) -> str:
    if score == total:
        return f"你已经掌握了《{record['title']}》的先后顺序，可以继续思考这些事件之间的因果联系。"
    if score >= total * 0.6:
        return "大部分顺序已经接近正确，建议重点复盘标红事件所处的朝代、时期和前后背景。"
    return "建议先抓住朝代或时期的大框架，再比较具体事件的先后；先判断属于古代、近代还是世界近代史，再细排事件。"


def build_card_game_learning_tip(score: int, total: int, record: CardGameRoundRecord) -> str:
    if score == total:
        return f"时间巨轮已经完全校准。你可以继续追问《{record['title']}》中这些事件之间的因果联系。"
    if score >= total * 0.6:
        return "大部分卡牌已经接近正确，修正时优先比较标红卡牌与相邻事件的时期和背景。"
    return "建议先把卡牌分成古代、近代或世界史的大框架，再用人物、制度变化和事件影响判断先后。"


def build_card_game_report_tip(total_score: int, total_cards: int, wrong_card_ids: list[str]) -> str:
    if total_cards == 0:
        return "还没有完成过时间巨轮挑战，先开始一局建立个人复盘记录。"
    if total_score == total_cards:
        return "最近的卡牌排序全部正确，可以切换专题或挑战更高难度。"
    if wrong_card_ids:
        return "复盘时重点关注错题卡所处的大时期，再比较它和相邻事件的因果关系。"
    return "继续保持，把每局讲解中的关键词整理成自己的时间轴。"


def student_key(student_id: str | None) -> str:
    return (student_id or "anonymous").strip() or "anonymous"



