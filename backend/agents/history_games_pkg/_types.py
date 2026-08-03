"""TypedDict 定义，供各子模块共享。"""
from __future__ import annotations
from datetime import datetime
from typing import Literal, TypedDict

GameStatus = Literal["available", "planned"]
TimelineDifficulty = Literal["easy", "normal", "hard"]


class HistoryGameDefinition(TypedDict):
    id: str
    title: str
    subtitle: str
    description: str
    teaching_goals: list[str]
    status: GameStatus
    estimated_minutes: int


class TimelineEventInternal(TypedDict):
    id: str
    title: str
    year: int
    display_year: str
    period: str
    summary: str
    topic: str
    explanation: str
    related_character: str | None
    suggested_question: str | None


class TimelineLevel(TypedDict):
    id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    events: list[TimelineEventInternal]


class TimelineRoundRecord(TypedDict):
    round_id: str
    level_id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    events: list[TimelineEventInternal]
    correct_order: list[str]
    created_at: datetime
    source: Literal["llm", "static"]
    fallback_used: bool
    generation_reason: str | None
    learning_goal: str | None
    student_id: str | None


class CardGameRoundRecord(TypedDict):
    round_id: str
    title: str
    grade: str
    difficulty: TimelineDifficulty
    topic: str
    cards: list[TimelineEventInternal]
    correct_order: list[str]
    created_at: datetime
    learning_goal: str | None
    retry_used: bool
    source: Literal["llm", "static"]
    fallback_used: bool
    generation_reason: str | None
    student_id: str | None
