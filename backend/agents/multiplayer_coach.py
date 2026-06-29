from __future__ import annotations

from typing import Any, Literal

TimelineErrorType = Literal[
    "too_early",
    "too_late",
    "same_period_confusion",
    "topic_confusion",
    "era_mismatch",
]


def _neighbor_values(neighbors: dict[str, Any], key: str) -> set[str]:
    values: set[str] = set()
    for side in ("left", "right"):
        event = neighbors.get(side)
        if isinstance(event, dict) and event.get(key):
            values.add(str(event[key]))
    return values


def classify_timeline_error(
    card: dict[str, Any],
    correct_index: int,
    submitted_index: int,
    correct_neighbors: dict[str, Any],
    submitted_neighbors: dict[str, Any],
) -> TimelineErrorType:
    card_period = str(card.get("period") or "")
    card_topic = str(card.get("topic") or "")
    submitted_periods = _neighbor_values(submitted_neighbors, "period")
    submitted_topics = _neighbor_values(submitted_neighbors, "topic")

    if submitted_index < correct_index:
        return "too_early"
    if submitted_index > correct_index:
        return "too_late"
    if card_period and card_period in submitted_periods:
        return "same_period_confusion"
    if card_topic and submitted_topics and card_topic not in submitted_topics:
        return "topic_confusion"
    return "era_mismatch"


def generate_coach_tip(
    card: dict[str, Any],
    correct_neighbors: dict[str, Any],
    submitted_neighbors: dict[str, Any],
    error_type: str,
) -> str:
    title = str(card.get("title") or "这张牌")
    period = str(card.get("period") or "对应时期")
    topic = str(card.get("topic") or "历史专题")
    left = correct_neighbors.get("left")
    right = correct_neighbors.get("right")

    if error_type == "too_early":
        return f"《{title}》放早了。先确认它属于{period}，再找时间轴上比它更早和更晚的事件来夹住它。"
    if error_type == "too_late":
        return f"《{title}》放晚了。可以先确定它的大时期，再向左比较哪些事件应发生在它之后。"
    if error_type == "same_period_confusion":
        return f"《{title}》和相邻事件时期接近，建议比较人物、制度变化或因果关系，而不只看朝代名称。"
    if error_type == "topic_confusion":
        return f"先确认《{title}》属于{topic}，再放回同一历史脉络中比较先后。"
    if left and right:
        return f"《{title}》应放在「{left.get('title')}」和「{right.get('title')}」附近，先抓住{period}这个大范围。"
    if left:
        return f"《{title}》应在「{left.get('title')}」之后，先抓住{period}这个大范围。"
    if right:
        return f"《{title}》应在「{right.get('title')}」之前，先抓住{period}这个大范围。"
    return f"先判断《{title}》所属的{period}，再和时间轴已有事件逐个比较先后。"
