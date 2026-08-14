from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ReviewedRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    source_context: dict[str, Any] = Field(default_factory=dict)


class ReviewedExpected(BaseModel):
    primary_intent: str = Field(min_length=1, max_length=80)
    intents: list[str] = Field(min_length=1, max_length=4)
    slots: dict[str, Any] = Field(default_factory=dict)
    needs_clarification: bool = False
    allowed_operations: list[str] = Field(default_factory=list)
    forbidden_operations: list[str] = Field(default_factory=list)


class ReviewLabel(BaseModel):
    reviewer_count: int = Field(ge=2, le=20)
    adjudicated: bool
    notes: str = Field(default="", max_length=300)


class ReviewedRoutingCase(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    source: Literal["human_authored", "production_anonymized", "expert_rewrite"]
    split: Literal["dev", "test"]
    locale: Literal["zh-CN"] = "zh-CN"
    request: ReviewedRequest
    expected: ReviewedExpected
    challenge_tags: list[str] = Field(min_length=1, max_length=12)
    label: ReviewLabel

    @field_validator("challenge_tags")
    @classmethod
    def unique_tags(cls, tags: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in tags if tag.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("challenge_tags must be unique")
        return normalized
