"""历史时空地图 Agent — 地理事件解说 + map_actions 控制"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator

from llm_config import llm_fast as llm, llm_quality as llm_opus
from rag.knowledge_base import search_with_scores
from structured_output import StructuredOutputError, parse_json_object
from tracing import truncate_text


logger = logging.getLogger(__name__)


def _resolve_geo_events_path() -> Path:
    """定位 geo_events.json，兼容本地仓库与容器布局。

    本地仓库：agent 在 <repo>/backend/agents/，数据在 <repo>/knowledge_base/history。
    线上容器：backend 被 `COPY backend/ .` 平铺到 /app，parents 上溯会落到根 /，
    数据实际在 /app/knowledge_base/history（见 backend/Dockerfile）。
    也允许用 GEO_EVENTS_PATH 环境变量显式覆盖。
    """
    env_path = os.environ.get("GEO_EVENTS_PATH")
    if env_path:
        return Path(env_path)
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "knowledge_base" / "history" / "geo_events.json",
        here.parent.parent / "knowledge_base" / "history" / "geo_events.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


_GEO_EVENTS_PATH = _resolve_geo_events_path()
_geo_events_cache: list[dict] | None = None


def load_geo_events() -> list[dict]:
    global _geo_events_cache
    if _geo_events_cache is None:
        try:
            _geo_events_cache = json.loads(_GEO_EVENTS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 数据文件缺失/损坏时降级为空，地图显示无事件，避免接口 500 连带 502。
            _geo_events_cache = []
    return _geo_events_cache


def get_events_by_dynasty(dynasty: str | None = None, year_start: int | None = None, year_end: int | None = None) -> list[dict]:
    events = load_geo_events()
    if dynasty:
        events = [e for e in events if e.get("dynasty") == dynasty]
    if year_start is not None:
        events = [e for e in events if e.get("year_start", 0) >= year_start]
    if year_end is not None:
        events = [e for e in events if e.get("year_start", 0) <= year_end]
    return events


def _retrieve_context(event: dict, user_query: str) -> list[str]:
    keywords = event.get("corpus_refs", [])
    query = " ".join(keywords) + (" " + user_query if user_query else "")
    try:
        scored = search_with_scores("history", query, k=4, mode="hybrid", fetch_k=20)
        return [truncate_text(item["document"].page_content, max_chars=400) for item in scored]
    except Exception:
        return []


def _fallback_narration(event: dict[str, Any], year: str) -> str:
    """Build a useful, catalog-grounded narration when the LLM is unavailable."""
    character = str(event.get("character") or "").strip()
    location = str(event.get("location_name") or "这一地点").strip()
    summary = str(event.get("summary") or f"这里发生了{event.get('title', '这一历史事件')}。功过影响还需结合史料判断。").strip()
    opening = f"{year}，我是{character}，此刻身处{location}。" if character else f"让我们回到{year}的{location}。"
    closing = "还可以沿着时间线继续查看同一时期的相关事件。"
    return f"{opening}{summary}{closing}"[:150]


_NARRATE_PROMPT = """你是中国历史教学助手。请根据以下史料，用生动的第一人称（以历史人物{character}的视角，若无人物则用旁白者视角）讲述"{title}"这一历史事件。

要求：
1. 语言适合初中生，生动有趣，不超过150字
2. 结合具体地点"{location_name}"和时间"{year}"
3. 结尾推荐1-2个相关历史事件供继续探索

史料：
{facts}

只输出讲述内容，不要JSON格式。"""

_MAP_ACTIONS_PROMPT = """根据以下历史事件信息，生成推荐的地图操作和关联事件列表。
事件：{title}（{dynasty}，{year}，{location_name}）
所有事件列表（仅供参考，从中选择关联项）：
{all_events}

输出JSON格式（不要其他内容）：
{{
  "related_event_ids": ["最多3个关联事件的id"],
  "actions": [
    {{"action": "fly_to", "lat": {lat}, "lng": {lng}, "zoom": 6}}
  ]
}}"""


def stream_map_narrate(event_id: str, user_query: str = "") -> Iterator[dict[str, Any]]:
    events = load_geo_events()
    event = next((e for e in events if e["id"] == event_id), None)
    if not event:
        yield {"event": "error", "data": {"message": f"事件 {event_id} 不存在"}}
        return

    facts = _retrieve_context(event, user_query)
    yield {"event": "sources", "data": {"facts_count": len(facts)}}

    year_str = f"公元前{abs(event['year_start'])}年" if event["year_start"] < 0 else f"公元{event['year_start']}年"
    narrate_prompt = _NARRATE_PROMPT.format(
        character=event.get("character") or "旁白者",
        title=event["title"],
        location_name=event["location_name"],
        year=year_str,
        facts="\n".join(facts) if facts else "（无史料）",
    )

    full_text = []
    generation_error = None
    fallback_used = False
    try:
        for chunk in llm.stream([{"role": "user", "content": narrate_prompt}]):
            full_text.append(chunk)
            yield {"event": "delta", "data": {"text": chunk}}
    except Exception as exc:
        generation_error = exc.__class__.__name__
        logger.warning("history_map_narration_degraded event_id=%s reason=%s", event_id, generation_error)

    if not full_text:
        fallback = _fallback_narration(event, year_str)
        full_text.append(fallback)
        fallback_used = True
        yield {"event": "delta", "data": {"text": fallback}}

    yield {
        "event": "final",
        "data": {
            "response": "".join(full_text),
            "event": event,
            "generation_mode": "fallback" if fallback_used else "llm_partial" if generation_error else "llm",
            "degraded": generation_error is not None,
        },
    }

    # 生成 map_actions
    all_events_brief = [{"id": e["id"], "title": e["title"], "dynasty": e["dynasty"]} for e in events]
    actions_prompt = _MAP_ACTIONS_PROMPT.format(
        title=event["title"],
        dynasty=event["dynasty"],
        year=year_str,
        location_name=event["location_name"],
        lat=event["lat"],
        lng=event["lng"],
        all_events=json.dumps(all_events_brief, ensure_ascii=False),
    )
    try:
        resp = llm.invoke([{"role": "user", "content": actions_prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)
        actions_data = parse_json_object(content)
    except (StructuredOutputError, Exception):
        actions_data = {"related_event_ids": [], "actions": [{"action": "fly_to", "lat": event["lat"], "lng": event["lng"], "zoom": 6}]}

    yield {"event": "map_actions", "data": actions_data}


_CHAT_INTENT_PROMPT = """你是历史时空地图的意图识别助手。分析用户问题，提取意图信息。

可用朝代：{dynasties}
可用事件类型：battle(战役)、politics(政治)、culture(文化)、construction(建设)、diplomacy(外交)

用户问题：{query}

输出JSON格式（不要其他内容）：
{{
  "intent": "navigate|ask|recommend",
  "dynasty": "提取的朝代名，如无则为null",
  "event_type": "提取的事件类型，如无则为null",
  "keywords": ["提取的关键词列表"],
  "response": "用古风语气回复用户，不超过50字"
}}"""


def handle_chat_query(query: str) -> dict[str, Any]:
    events = load_geo_events()
    dynasties = list(set(e.get("dynasty") for e in events))

    intent_prompt = _CHAT_INTENT_PROMPT.format(
        dynasties="、".join(dynasties),
        query=query,
    )

    try:
        resp = llm.invoke([{"role": "user", "content": intent_prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)
        intent_data = parse_json_object(content)
    except (StructuredOutputError, Exception):
        intent_data = {"intent": "ask", "dynasty": None, "event_type": None, "keywords": [], "response": "史官未能理解阁下之意"}

    intent = intent_data.get("intent", "ask")
    dynasty = intent_data.get("dynasty")
    event_type = intent_data.get("event_type")

    map_actions = {}

    # 导航意图：切换朝代或筛选事件类型
    if intent == "navigate" and dynasty:
        map_actions["dynasty"] = dynasty
        if event_type:
            filtered = [e for e in events if e.get("dynasty") == dynasty and e.get("type") == event_type]
            if filtered:
                map_actions["event_id"] = filtered[0]["id"]
                map_actions["fly_to"] = {"lat": filtered[0]["lat"], "lng": filtered[0]["lng"], "zoom": 6}

    return {
        "response": intent_data.get("response", "史官已收到阁下之问"),
        "intent": intent,
        "map_actions": map_actions if map_actions else None,
    }
