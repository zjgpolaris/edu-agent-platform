"""history_games 子包入口 — 重新导出所有公共符号，外部代码无需修改。"""
from agents.history_games_pkg._types import (
    GameStatus,
    TimelineDifficulty,
    HistoryGameDefinition,
    TimelineEventInternal,
    TimelineLevel,
    TimelineRoundRecord,
    CardGameRoundRecord,
)
from agents.history_games_pkg._catalog import (
    HISTORY_GAMES,
    TIMELINE_LEVELS,
    CARD_GAME_RECENT_EVENTS,
)
from agents.history_games_pkg._utils import (
    public_event,
    public_card,
    normalize_difficulty,
    choose_level,
    validate_submission,
    build_learning_tip,
    build_card_game_learning_tip,
    build_card_game_report_tip,
    student_key,
)
from agents.history_games_pkg.timeline_flow import (
    list_history_games,
    start_timeline_round,
    create_static_timeline_round,
    create_timeline_round_record,
    submit_timeline_round,
)
from agents.history_games_pkg.card_flow import (
    start_card_game_round,
    create_static_card_game_round,
    create_card_game_round_record,
    submit_card_game_round,
    retry_card_game_round,
    build_card_game_result,
    persist_card_game_result,
    get_card_game_report,
)

__all__ = [
    "GameStatus", "TimelineDifficulty", "HistoryGameDefinition",
    "TimelineEventInternal", "TimelineLevel", "TimelineRoundRecord",
    "CardGameRoundRecord", "HISTORY_GAMES", "TIMELINE_LEVELS",
    "CARD_GAME_RECENT_EVENTS", "public_event", "public_card",
    "normalize_difficulty", "choose_level", "validate_submission",
    "build_learning_tip", "build_card_game_learning_tip",
    "build_card_game_report_tip", "student_key", "list_history_games",
    "start_timeline_round", "create_static_timeline_round",
    "create_timeline_round_record", "submit_timeline_round",
    "start_card_game_round", "create_static_card_game_round",
    "create_card_game_round_record", "submit_card_game_round",
    "retry_card_game_round", "build_card_game_result",
    "persist_card_game_result", "get_card_game_report",
]
