from __future__ import annotations

from pydantic import BaseModel, Field

from agents.history_games import start_timeline_round
from tools.base import ToolResult


class StartTimelineGameInput(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None
    student_id: str | None = None
    mode: str = Field(default="llm", pattern="^(llm|static)$")


def start_timeline_game(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, StartTimelineGameInput) else StartTimelineGameInput.model_validate(payload)
    game = start_timeline_round(req.grade, req.difficulty, req.topic, req.student_id, req.mode)
    return ToolResult(
        tool_name="start_timeline_game",
        ok=True,
        data={"game": game},
        metadata={
            "round_id": game.get("round_id"),
            "grade": game.get("grade"),
            "difficulty": game.get("difficulty"),
            "topic": game.get("topic"),
            "source": game.get("source"),
            "fallback_used": game.get("fallback_used"),
        },
    )
