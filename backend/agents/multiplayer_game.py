from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from services.weakpoint_service import record_weakpoint
from typing import Any, Literal, TypedDict
from uuid import uuid4

from agents.history_games import TIMELINE_LEVELS, TimelineEventInternal, normalize_difficulty
from agents.multiplayer_ai_commentary import generate_ai_play_reason
from agents.multiplayer_card_generator import generate_multiplayer_card_pool
from agents.multiplayer_coach import classify_timeline_error, generate_coach_tip
from agents.timeline_question_generator import flatten_static_levels, get_recent_event_ids, matches_topic, update_recent_event_ids

logger = logging.getLogger(__name__)

ACTIVE_MULTIPLAYER_ROUNDS: dict[str, MultiplayerGameState] = {}
MULTIPLAYER_RECENT_EVENTS: dict[str, list[str]] = {}
ROUND_TTL = timedelta(hours=2)
AI_ERROR_RATES: dict[str, float] = {"easy": 0.30, "medium": 0.15, "hard": 0.05}


class AiPersona(TypedDict):
    name: str
    persona: str
    strength: str
    weakness: str
    style: str


AI_PERSONAS: list[AiPersona] = [
    {
        "name": "小明",
        "persona": "记忆力强，喜欢先抓朝代和大时期。",
        "strength": "秦汉史",
        "weakness": "史前文明",
        "style": "先判断朝代，再比较事件先后",
    },
    {
        "name": "小红",
        "persona": "善于联想人物故事，但偶尔会被相近事件干扰。",
        "strength": "人物与制度变革",
        "weakness": "近现代条约时间",
        "style": "用人物和因果关系定位事件",
    },
    {
        "name": "小刚",
        "persona": "出牌很果断，喜欢从战争和政权更替入手。",
        "strength": "战争与政权更替",
        "weakness": "文化科技事件",
        "style": "先看历史阶段，再找关键转折点",
    },
    {
        "name": "小丽",
        "persona": "思路细致，喜欢把事件放回专题脉络。",
        "strength": "中国近代史",
        "weakness": "世界古代史",
        "style": "按专题线索串联时间顺序",
    },
    {
        "name": "小强",
        "persona": "喜欢挑战难题，但遇到同一年代事件会犹豫。",
        "strength": "世界史",
        "weakness": "同一时期事件排序",
        "style": "先比较地区，再判断先后影响",
    },
]


class PlayerState(TypedDict):
    player_id: str
    player_type: Literal["human", "ai"]
    display_name: str
    persona: AiPersona | None
    hand: list[str]
    finished: bool
    correct_plays: int
    wrong_plays: int


class MultiplayerGameState(TypedDict):
    round_id: str
    all_cards: dict[str, TimelineEventInternal]
    correct_rank: dict[str, int]
    deck: list[str]
    timeline: list[str]
    players: list[PlayerState]
    current_player_index: int
    winner_player_id: str | None
    ai_difficulty: str
    source: Literal["llm", "static"]
    fallback_used: bool
    generation_reason: str | None
    learning_goal: str | None
    created_at: datetime


def start_multiplayer_round(
    grade: str | None = None,
    difficulty: str = "easy",
    topic: str | None = None,
    student_id: str | None = None,
    ai_count: int = 2,
    ai_difficulty: str = "medium",
    mode: str = "llm",
) -> dict:
    _cleanup_expired()
    normalized = normalize_difficulty(difficulty)
    normalized_mode = (mode or "llm").strip().lower()
    if normalized_mode not in {"llm", "static"}:
        raise ValueError("不支持的多人游戏出题模式，请选择 llm 或 static。")
    ai_count = max(1, min(ai_count, 5))
    total_players = ai_count + 1
    hand_size = 5
    min_required_cards = 1 + total_players * hand_size
    target_cards = _multiplayer_target_card_count(total_players)

    source: Literal["llm", "static"]
    fallback_used = False
    generation_reason: str | None = None
    learning_goal: str | None = None

    if normalized_mode == "llm":
        logger.info(
            "multiplayer_round_dynamic_start difficulty=%s topic=%s grade=%s ai_count=%s total_players=%s min_required_cards=%s target_cards=%s",
            normalized,
            topic,
            grade,
            ai_count,
            total_players,
            min_required_cards,
            target_cards,
        )
        try:
            generated = _generate_dynamic_cards_with_retry(
                grade=grade,
                difficulty=normalized,
                topic=topic,
                student_id=student_id,
                total_players=total_players,
                min_required_cards=min_required_cards,
                target_cards=target_cards,
            )
            cards = generated["cards"]
            source = "llm"
            learning_goal = generated.get("learning_goal")
        except Exception as exc:
            logger.warning(
                "multiplayer_card_pool_fallback difficulty=%s topic=%s ai_count=%s reason=%s",
                normalized,
                topic,
                ai_count,
                exc,
            )
            cards = _select_cards(
                grade,
                normalized,
                topic,
                min_count=min_required_cards,
                student_id=student_id,
                target_count=target_cards,
            )
            source = "static"
            fallback_used = True
            generation_reason = str(exc)
    else:
        cards = _select_cards(
            grade,
            normalized,
            topic,
            min_count=min_required_cards,
            student_id=student_id,
            target_count=target_cards,
        )
        source = "static"
        generation_reason = "mode=static"

    if len(cards) < min_required_cards:
        raise ValueError(f"当前范围至少需要 {min_required_cards} 张卡牌，无法按规则每人发 5 张。")

    all_cards: dict[str, Any] = {c["id"]: c for c in cards}
    sorted_ids = [c["id"] for c in sorted(cards, key=lambda x: x["year"])]
    correct_rank: dict[str, int] = {cid: all_cards[cid]["year"] for cid in sorted_ids}

    shuffled_ids = sorted_ids.copy()
    random.shuffle(shuffled_ids)

    anchor_id = shuffled_ids[0]
    remaining = shuffled_ids[1:]

    players: list[PlayerState] = []
    human_hand = remaining[:hand_size]
    remaining = remaining[hand_size:]
    players.append({
        "player_id": student_id or "student",
        "player_type": "human",
        "display_name": "你",
        "persona": None,
        "hand": human_hand,
        "finished": False,
        "correct_plays": 0,
        "wrong_plays": 0,
    })

    for i in range(ai_count):
        persona = AI_PERSONAS[i % len(AI_PERSONAS)]
        ai_hand = remaining[:hand_size]
        remaining = remaining[hand_size:]
        players.append({
            "player_id": f"ai-{i}",
            "player_type": "ai",
            "display_name": f"AI {persona['name']}",
            "persona": persona,
            "hand": ai_hand,
            "finished": False,
            "correct_plays": 0,
            "wrong_plays": 0,
        })

    deck = remaining
    first_player_index = random.randrange(len(players))

    round_id = f"mp-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}"
    state: MultiplayerGameState = {
        "round_id": round_id,
        "all_cards": all_cards,
        "correct_rank": correct_rank,
        "deck": deck,
        "timeline": [anchor_id],
        "players": players,
        "current_player_index": first_player_index,
        "winner_player_id": None,
        "ai_difficulty": ai_difficulty,
        "source": source,
        "fallback_used": fallback_used,
        "generation_reason": generation_reason,
        "learning_goal": learning_goal,
        "created_at": datetime.now(timezone.utc),
    }
    ACTIVE_MULTIPLAYER_ROUNDS[round_id] = state
    logger.info(
        "multiplayer_round_started round_id=%s source=%s fallback_used=%s generation_reason=%s player_count=%s hand_size=%s deck_count=%s timeline_count=%s",
        round_id,
        source,
        fallback_used,
        generation_reason,
        len(players),
        hand_size,
        len(deck),
        len(state["timeline"]),
    )
    return _public_state(state, players[0]["player_id"])


def play_human_turn(round_id: str, player_id: str, card_id: str, insert_index: int) -> dict:
    state = _get_state(round_id)
    player = state["players"][state["current_player_index"]]

    if player["player_id"] != player_id:
        raise ValueError("现在不是你的回合。")
    if player["player_type"] != "human":
        raise ValueError("该玩家不是学生。")
    if card_id not in player["hand"]:
        raise ValueError("该卡牌不在手牌中。")
    if insert_index < 0 or insert_index > len(state["timeline"]):
        raise ValueError("插入位置无效。")

    correct_index = _find_correct_insert(state, card_id)
    submitted_neighbors = _neighbors_for_insert(state, insert_index)
    correct_neighbors = _neighbors_for_insert(state, correct_index)
    will_be_correct = _is_correct_insert(state, card_id, insert_index)
    card = state["all_cards"][card_id]
    error_type = None
    coach_tip = None

    if not will_be_correct:
        error_type = classify_timeline_error(
            card,
            correct_index,
            insert_index,
            correct_neighbors,
            submitted_neighbors,
        )
        coach_tip = generate_coach_tip(card, correct_neighbors, submitted_neighbors, error_type)

    correct, penalty_card = _apply_play(state, player, card_id, insert_index)

    if not correct:
        try:
            record_weakpoint(player_id, card["title"], "multiplayer_game")
        except Exception:
            pass

    feedback = {
        "card_title": card["title"],
        "display_year": card["display_year"],
        "explanation": card.get("explanation", ""),
        "suggested_question": card.get("suggested_question"),
        "error_type": error_type,
        "coach_tip": coach_tip,
    }

    return {
        "correct": correct,
        "feedback": feedback,
        "error_type": error_type,
        "coach_tip": coach_tip,
        "penalty_card": _public_card(state["all_cards"][penalty_card], state["correct_rank"]) if penalty_card else None,
        "game_state": _public_state(state, player_id),
    }


def play_ai_turn(round_id: str) -> dict:
    state = _get_state(round_id)
    player = state["players"][state["current_player_index"]]

    if player["player_type"] != "ai":
        raise ValueError("当前回合不是 AI 玩家。")
    if not player["hand"]:
        _advance_turn(state)
        return {
            "ai_player_id": player["player_id"],
            "ai_display_name": player["display_name"],
            "ai_persona": player.get("persona"),
            "ai_reason": "",
            "card_played": None,
            "correct": False,
            "game_state": _public_state(state, _human_id(state)),
        }

    card_id = random.choice(player["hand"])
    error_rate = AI_ERROR_RATES.get(state["ai_difficulty"], 0.15)

    if random.random() < error_rate:
        wrong_indices = [
            i for i in range(len(state["timeline"]) + 1)
            if not _is_correct_insert(state, card_id, i)
        ]
        insert_index = random.choice(wrong_indices) if wrong_indices else 0
    else:
        insert_index = _find_correct_insert(state, card_id)

    correct = _is_correct_insert(state, card_id, insert_index)
    timeline_neighbors = _neighbors_for_insert(state, insert_index)
    card = state["all_cards"][card_id]
    ai_reason = generate_ai_play_reason(player.get("persona"), card, timeline_neighbors, correct)

    correct, _ = _apply_play(state, player, card_id, insert_index)

    return {
        "ai_player_id": player["player_id"],
        "ai_display_name": player["display_name"],
        "ai_persona": player.get("persona"),
        "ai_reason": ai_reason,
        "card_played": {"id": card_id, "title": card["title"], "display_year": card["display_year"]},
        "correct": correct,
        "game_state": _public_state(state, _human_id(state)),
    }


# --- internal helpers ---

def _get_state(round_id: str) -> MultiplayerGameState:
    _cleanup_expired()
    state = ACTIVE_MULTIPLAYER_ROUNDS.get(round_id)
    if not state:
        raise LookupError("多人游戏回合不存在或已过期，请重新开始。")
    return state


def _apply_play(
    state: MultiplayerGameState,
    player: PlayerState,
    card_id: str,
    insert_index: int,
) -> tuple[bool, str | None]:
    if insert_index < 0 or insert_index > len(state["timeline"]):
        raise ValueError("插入位置无效。")

    correct = _is_correct_insert(state, card_id, insert_index)
    penalty_card: str | None = None

    if correct:
        player["hand"].remove(card_id)
        state["timeline"].insert(insert_index, card_id)
        player["correct_plays"] += 1
        if not player["hand"]:
            player["finished"] = True
            if state["winner_player_id"] is None:
                state["winner_player_id"] = player["player_id"]
    else:
        player["hand"].remove(card_id)
        state["deck"].append(card_id)
        player["wrong_plays"] += 1
        if state["deck"]:
            penalty_card = state["deck"].pop(0)
            player["hand"].append(penalty_card)

    _advance_turn(state)
    return correct, penalty_card


def _is_correct_insert(state: MultiplayerGameState, card_id: str, insert_index: int) -> bool:
    timeline = state["timeline"]
    rank = state["correct_rank"]
    card_rank = rank[card_id]
    left_rank = rank[timeline[insert_index - 1]] if insert_index > 0 else float("-inf")
    right_rank = rank[timeline[insert_index]] if insert_index < len(timeline) else float("inf")
    return left_rank <= card_rank <= right_rank


def _find_correct_insert(state: MultiplayerGameState, card_id: str) -> int:
    for i in range(len(state["timeline"]) + 1):
        if _is_correct_insert(state, card_id, i):
            return i
    return 0


def _advance_turn(state: MultiplayerGameState) -> None:
    n = len(state["players"])
    for _ in range(n):
        state["current_player_index"] = (state["current_player_index"] + 1) % n
        if not state["players"][state["current_player_index"]]["finished"]:
            return


def _human_id(state: MultiplayerGameState) -> str:
    for p in state["players"]:
        if p["player_type"] == "human":
            return p["player_id"]
    return "student"


def _generate_dynamic_cards_with_retry(
    *,
    grade: str | None,
    difficulty: str,
    topic: str | None,
    student_id: str | None,
    total_players: int,
    min_required_cards: int,
    target_cards: int,
) -> dict[str, Any]:
    attempts = [target_cards, min_required_cards]
    last_error: Exception | None = None
    for count in dict.fromkeys(attempts):
        try:
            logger.info(
                "multiplayer_dynamic_card_pool_attempt difficulty=%s topic=%s target_count=%s min_required_cards=%s",
                difficulty,
                topic,
                count,
                min_required_cards,
            )
            generated = generate_multiplayer_card_pool(
                grade=grade,
                difficulty=difficulty,
                topic=topic,
                student_id=student_id,
                recent_store=MULTIPLAYER_RECENT_EVENTS,
                target_count=count,
            )
            logger.info(
                "multiplayer_dynamic_card_pool_attempt_success difficulty=%s topic=%s target_count=%s selected_count=%s",
                difficulty,
                topic,
                count,
                len(generated.get("cards", [])),
            )
            return generated
        except Exception as exc:
            last_error = exc
            logger.warning(
                "multiplayer_dynamic_card_pool_retry_failed difficulty=%s topic=%s target_count=%s reason=%s",
                difficulty,
                topic,
                count,
                exc,
            )
    if last_error:
        raise last_error
    raise ValueError("动态卡池生成失败。")


def _multiplayer_target_card_count(total_players: int) -> int:
    desired_hand_size = 5
    deck_buffer = max(2, total_players)
    return min(24, 1 + total_players * desired_hand_size + deck_buffer)


def _public_card(card: Any, correct_rank: dict[str, int]) -> dict:
    return {
        "id": card["id"],
        "title": card["title"],
        "period": card["period"],
        "summary": card.get("summary", card.get("clue", "")),
        "topic": card["topic"],
        "display_year": card["display_year"],
        "year_rank": correct_rank.get(card["id"], 0),
    }


def _neighbor_card(card: Any) -> dict[str, Any]:
    return {
        "id": card["id"],
        "title": card["title"],
        "period": card["period"],
        "topic": card["topic"],
        "display_year": card["display_year"],
    }


def _neighbors_for_insert(state: MultiplayerGameState, insert_index: int) -> dict[str, Any]:
    timeline = state["timeline"]
    all_cards = state["all_cards"]
    left = all_cards[timeline[insert_index - 1]] if insert_index > 0 else None
    right = all_cards[timeline[insert_index]] if insert_index < len(timeline) else None
    return {
        "left": _neighbor_card(left) if left else None,
        "right": _neighbor_card(right) if right else None,
    }


def _public_state(state: MultiplayerGameState, for_player_id: str) -> dict:
    all_cards = state["all_cards"]
    rank = state["correct_rank"]

    timeline_cards = [_public_card(all_cards[cid], rank) for cid in state["timeline"]]

    players_out = []
    for p in state["players"]:
        entry: dict[str, Any] = {
            "player_id": p["player_id"],
            "player_type": p["player_type"],
            "display_name": p["display_name"],
            "finished": p["finished"],
            "correct_plays": p["correct_plays"],
            "wrong_plays": p["wrong_plays"],
        }
        if p["player_type"] == "ai":
            entry["persona"] = p.get("persona")
        if p["player_id"] == for_player_id:
            entry["hand"] = [_public_card(all_cards[cid], rank) for cid in p["hand"]]
        else:
            entry["hand_count"] = len(p["hand"])
        players_out.append(entry)

    return {
        "round_id": state["round_id"],
        "timeline": timeline_cards,
        "players": players_out,
        "current_player_index": state["current_player_index"],
        "deck_count": len(state["deck"]),
        "winner_player_id": state["winner_player_id"],
        "source": state["source"],
        "fallback_used": state["fallback_used"],
        "generation_reason": state.get("generation_reason"),
        "learning_goal": state.get("learning_goal"),
    }


def _select_cards(
    grade: str | None,
    difficulty: str,
    topic: str | None,
    min_count: int = 5,
    student_id: str | None = None,
    target_count: int | None = None,
) -> list[dict[str, Any]]:
    candidates = flatten_static_levels(TIMELINE_LEVELS)  # type: ignore[arg-type]
    filtered = candidates

    if topic:
        filtered = [candidate for candidate in filtered if matches_topic(candidate, topic)]

    if grade:
        grade_matches = [candidate for candidate in filtered if grade in candidate["grade"]]
        if grade_matches:
            filtered = grade_matches

    difficulty_matches = [candidate for candidate in filtered if candidate["base_difficulty"] == difficulty]
    if len(difficulty_matches) >= min_count:
        filtered = difficulty_matches

    if len(filtered) < min_count:
        scope = f"{topic or '当前范围'} / {difficulty}"
        raise ValueError(f"{scope} 可用卡牌不足，请切换专题或补充题库。")

    count = min(target_count or len(filtered), len(filtered))
    recent_ids = set(get_recent_event_ids(MULTIPLAYER_RECENT_EVENTS, student_id, topic, difficulty))
    fresh_cards = [card for card in filtered if card["id"] not in recent_ids]
    selection_pool = fresh_cards if len(fresh_cards) >= min_count else filtered
    selected = random.sample(selection_pool, count) if len(selection_pool) > count else selection_pool.copy()
    if len(selected) < min_count:
        selected_ids = {card["id"] for card in selected}
        remainder = [card for card in filtered if card["id"] not in selected_ids]
        random.shuffle(remainder)
        selected.extend(remainder[: min_count - len(selected)])

    update_recent_event_ids(MULTIPLAYER_RECENT_EVENTS, student_id, topic, difficulty, [card["id"] for card in selected])

    return [
        {
            "id": card["id"],
            "title": card["title"],
            "year": card["year"],
            "display_year": card["display_year"],
            "period": card["period"],
            "summary": card["summary"],
            "topic": card["topic"],
            "explanation": card["explanation"],
            "related_character": card["related_character"],
            "suggested_question": card["suggested_question"],
        }
        for card in selected
    ]


def _cleanup_expired() -> None:
    now = datetime.now(timezone.utc)
    expired = [rid for rid, s in ACTIVE_MULTIPLAYER_ROUNDS.items() if now - s["created_at"] > ROUND_TTL]
    for rid in expired:
        ACTIVE_MULTIPLAYER_ROUNDS.pop(rid, None)
