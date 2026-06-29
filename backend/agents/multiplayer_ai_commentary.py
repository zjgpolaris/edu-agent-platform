from __future__ import annotations

import logging
from typing import Any

from agents.timeline_question_generator import clean_string
from structured_output import parse_json_object
from llm_config import llm_fast

logger = logging.getLogger(__name__)


def _event_label(event: dict[str, Any] | None) -> str:
    if not event:
        return "时间轴边界"
    return f"{event.get('title', '这一事件')}（{event.get('period', event.get('display_year', ''))}）"


def build_fallback_ai_reason(
    persona: dict[str, Any] | None,
    card: dict[str, Any],
    timeline_neighbors: dict[str, Any],
    correct: bool,
) -> str:
    name = clean_string((persona or {}).get("name"), 12) or clean_string((persona or {}).get("display_name"), 12) or "我"
    title = clean_string(card.get("title"), 30) or "这张牌"
    period = clean_string(card.get("period"), 20) or "这个时期"
    left = timeline_neighbors.get("left")
    right = timeline_neighbors.get("right")

    if correct:
        if left and right:
            return f"{name}：我先判断《{title}》属于{period}，再把它放在{_event_label(left)}和{_event_label(right)}之间。"
        if left:
            return f"{name}：我先判断《{title}》属于{period}，它应在{_event_label(left)}之后。"
        if right:
            return f"{name}：我先判断《{title}》属于{period}，它应在{_event_label(right)}之前。"
        return f"{name}：我先看《{title}》的时期，再把它放到时间轴上。"

    return f"{name}：我对《{title}》的先后有点拿不准，先按{period}的大致位置试试看。"


def generate_ai_play_reason(
    persona: dict[str, Any] | None,
    card: dict[str, Any],
    timeline_neighbors: dict[str, Any],
    correct: bool,
    use_llm: bool = True,
) -> str:
    fallback = build_fallback_ai_reason(persona, card, timeline_neighbors, correct)
    if not use_llm:
        return fallback

    persona_text = {
        "name": (persona or {}).get("name"),
        "persona": (persona or {}).get("persona"),
        "strength": (persona or {}).get("strength"),
        "weakness": (persona or {}).get("weakness"),
        "style": (persona or {}).get("style"),
    }
    messages = [
        {
            "role": "system",
            "content": "你是初中历史时间轴游戏里的 AI 同学。只基于给定卡牌和相邻事件生成一句出牌思考，必须返回严格 JSON，不要输出解释文字。",
        },
        {
            "role": "user",
            "content": f"""
AI 同学人设：{persona_text}
本次出牌卡牌：{{"title": "{card.get('title')}", "period": "{card.get('period')}", "topic": "{card.get('topic')}", "display_year": "{card.get('display_year')}"}}
插入位置相邻事件：{timeline_neighbors}
这次位置是否正确：{correct}

请生成一句第一人称思考，要求：
1. 以 AI 同学名字开头，例如“小明：”。
2. 口吻像同学在解释自己的判断。
3. 不超过 80 个汉字。
4. 不要编造未给出的历史事实。

返回 JSON：
{{"reason": "..."}}
""".strip(),
        },
    ]

    try:
        response = llm_fast.invoke(messages)
        payload = parse_json_object(response.content)
        reason = clean_string(payload.get("reason"), 100)
        if not reason:
            return fallback
        return reason
    except Exception as exc:
        logger.warning("failed to generate multiplayer AI reason: %s", exc)
        return fallback
