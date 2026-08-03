"""向后兼容转发层 — 将原 history_games 模块的所有导出委托给子包。

外部代码（api/routers/history.py、multiplayer_game.py 等）无需修改。
"""
from agents.history_games_pkg import *  # noqa: F401, F403
from agents.history_games_pkg import (
    GameStatus,
    TimelineDifficulty,
    HistoryGameDefinition,
    TimelineEventInternal,
    TimelineLevel,
    TimelineRoundRecord,
    CardGameRoundRecord,
    HISTORY_GAMES,
    TIMELINE_LEVELS,
    CARD_GAME_RECENT_EVENTS,
    public_event,
    public_card,
    normalize_difficulty,
    choose_level,
    validate_submission,
    build_learning_tip,
    build_card_game_learning_tip,
    build_card_game_report_tip,
    student_key,
    list_history_games,
    start_timeline_round,
    create_static_timeline_round,
    create_timeline_round_record,
    submit_timeline_round,
    start_card_game_round,
    create_static_card_game_round,
    create_card_game_round_record,
    submit_card_game_round,
    retry_card_game_round,
    build_card_game_result,
    persist_card_game_result,
    get_card_game_report,
)
