from __future__ import annotations

from pydantic import BaseModel, Field

from agents.character_recommender import recommend_characters
from tools.base import ToolResult


class RecommendCharacterInput(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    grade: str | None = None
    limit: int = Field(default=3, ge=2, le=4)


def recommend_character(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, RecommendCharacterInput) else RecommendCharacterInput.model_validate(payload)
    recommendations = recommend_characters(req.message, req.grade, req.limit)
    return ToolResult(
        tool_name="recommend_character",
        ok=True,
        data={"recommendations": recommendations},
        metadata={"grade": req.grade, "recommendation_count": len(recommendations)},
    )
