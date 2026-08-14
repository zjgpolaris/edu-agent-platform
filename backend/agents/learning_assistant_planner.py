from __future__ import annotations

import os
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from agents.learning_assistant_router import IntentName, RoutedTask, RoutingDecision, env_enabled


PlanStepStatus = Literal["pending", "running", "waiting_confirmation", "completed", "failed", "cancelled"]


class PlanStep(BaseModel):
    step_id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=80)
    kind: Literal["tool", "generation"]
    operation: str = Field(min_length=1, max_length=80)
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=2)
    success_criteria: list[str] = Field(default_factory=list, max_length=4)
    status: PlanStepStatus = "pending"


class TaskPlan(BaseModel):
    schema_version: Literal[1] = 1
    objective: str = Field(min_length=1, max_length=240)
    steps: list[PlanStep] = Field(min_length=1, max_length=3)
    max_tool_calls: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def validate_plan(self) -> "TaskPlan":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step ids must be unique")
        allowed_dependencies: set[str] = set()
        for step in self.steps:
            if any(dep not in allowed_dependencies for dep in step.depends_on):
                raise ValueError("plan dependencies must reference earlier steps")
            allowed_dependencies.add(step.step_id)
        if sum(1 for step in self.steps if step.kind == "tool") > self.max_tool_calls:
            raise ValueError("plan exceeds max tool calls")
        return self


ALLOWED_TOOL_OPERATIONS = {
    "search_history_knowledge",
    "get_textbook_lesson",
    "generate_quiz",
    "recommend_character",
    "start_timeline_game",
    "suggest_review_plan",
    "delete_demo_memory",
}
ALLOWED_GENERATION_OPERATIONS = {
    "answer_from_sources",
    "answer_from_lesson",
    "quiz_from_sources",
    "quiz_from_lesson",
    "chat_answer",
}


def planner_enabled() -> bool:
    return env_enabled("EDU_AGENT_ASSISTANT_PLANNER_ENABLED")


def _requested_count(message: str, default: int = 3) -> int:
    match = re.search(r"([1-9]|10)\s*道", message)
    if match:
        return min(10, max(1, int(match.group(1))))
    return default


def _search_payload(task: RoutedTask, req: dict[str, Any]) -> dict[str, Any]:
    message = str(req.get("message") or "").strip()
    previous_user = next(
        (str(item.get("content") or "") for item in reversed(req.get("conversation_history") or []) if item.get("role") == "user"),
        "",
    )
    context_topic = (req.get("source_context") or {}).get("knowledge_point")
    topic = task.topic or context_topic
    query_parts: list[str] = []
    if topic and str(topic) not in message:
        query_parts.append(str(topic))
    if not topic and previous_user:
        query_parts.append(previous_user)
    query_parts.append(message)
    query = " ".join(part for part in query_parts if part).strip()[:500]
    return {"query": query or message, "grade": req.get("grade"), "topic": topic, "k": 4}


def _tool_step(step_id: str, title: str, operation: str, payload: dict[str, Any], *, depends_on: list[str] | None = None, criteria: list[str] | None = None) -> PlanStep:
    if operation not in ALLOWED_TOOL_OPERATIONS:
        raise ValueError(f"tool operation is not allowed: {operation}")
    return PlanStep(
        step_id=step_id,
        title=title,
        kind="tool",
        operation=operation,
        input=payload,
        depends_on=depends_on or [],
        success_criteria=criteria or ["tool_result_ok"],
    )


def _generation_step(step_id: str, title: str, operation: str, payload: dict[str, Any], *, depends_on: list[str] | None = None, criteria: list[str] | None = None) -> PlanStep:
    if operation not in ALLOWED_GENERATION_OPERATIONS:
        raise ValueError(f"generation operation is not allowed: {operation}")
    return PlanStep(
        step_id=step_id,
        title=title,
        kind="generation",
        operation=operation,
        input=payload,
        depends_on=depends_on or [],
        success_criteria=criteria or ["non_empty_output"],
    )


def _single_task_steps(task: RoutedTask, req: dict[str, Any]) -> list[PlanStep]:
    message = str(req.get("message") or "").strip()
    intent = task.intent
    if intent == IntentName.history_search:
        return [
            _tool_step("step_1", "查找可信史料", "search_history_knowledge", _search_payload(task, req), criteria=["tool_result_ok", "source_count_gte_1"]),
            _generation_step("step_2", "生成史料解释", "answer_from_sources", {"message": message, "topic": task.topic}, depends_on=["step_1"]),
        ]
    if intent == IntentName.textbook_qa:
        if req.get("book_id") and req.get("lesson_id"):
            return [
                _tool_step("step_1", "读取教材课文", "get_textbook_lesson", {"book_id": req["book_id"], "lesson_id": req["lesson_id"]}, criteria=["tool_result_ok", "lesson_present"]),
                _generation_step("step_2", "生成教材回答", "answer_from_lesson", {"message": message, "topic": task.topic}, depends_on=["step_1"]),
            ]
        if task.topic:
            return [
                _tool_step("step_1", "查找相关课程史料", "search_history_knowledge", _search_payload(task, req), criteria=["tool_result_ok", "source_count_gte_1"]),
                _generation_step("step_2", "生成课程回答", "answer_from_sources", {"message": message, "topic": task.topic}, depends_on=["step_1"]),
            ]
        return [_generation_step("step_1", "澄清教材范围", "chat_answer", {"message": message})]
    if intent == IntentName.quiz_generation:
        count = task.count or _requested_count(message)
        if req.get("book_id") and req.get("lesson_id"):
            question_types = ["single_choice"] if task.question_type == "choice" else ["short_answer"] if task.question_type == "short_answer" else ["single_choice", "short_answer"]
            return [_tool_step("step_1", "生成教材练习", "generate_quiz", {"book_id": req["book_id"], "lesson_id": req["lesson_id"], "count": count, "question_types": question_types}, criteria=["tool_result_ok", "question_count_matches"])]
        return [
            _tool_step("step_1", "查找出题依据", "search_history_knowledge", _search_payload(task, req), criteria=["tool_result_ok", "source_count_gte_1"]),
            _generation_step("step_2", f"生成 {count} 道练习", "quiz_from_sources", {"message": message, "topic": task.topic, "count": count, "question_type": task.question_type or "mixed"}, depends_on=["step_1"], criteria=["question_count_matches"]),
        ]
    if intent == IntentName.review_plan:
        return [_tool_step("step_1", "生成复习计划", "suggest_review_plan", {"student_id": req.get("student_id") or "anonymous", "limit": 5}, criteria=["tool_result_ok", "recommended_action_present"])]
    if intent == IntentName.character_recommendation:
        return [_tool_step("step_1", "推荐历史人物", "recommend_character", {"message": message, "grade": req.get("grade"), "limit": 3})]
    if intent == IntentName.timeline_game:
        return [_tool_step("step_1", "创建时间线游戏", "start_timeline_game", {"grade": req.get("grade"), "difficulty": "easy", "topic": task.topic or message, "student_id": req.get("student_id"), "mode": "llm"})]
    if intent == IntentName.memory_delete_demo:
        return [_tool_step("step_1", "删除演示记忆", "delete_demo_memory", {"student_id": req.get("student_id") or "demo-student", "memory_id": "demo_wrong_memory_001", "reason": "演示 high-risk human confirmation"})]
    return [_generation_step("step_1", "生成学习回答", "chat_answer", {"message": message, "topic": task.topic})]


def _composition_steps(tasks: list[RoutedTask], req: dict[str, Any]) -> list[PlanStep] | None:
    if (
        len(tasks) != 2
        or tasks[0].intent not in {IntentName.history_search, IntentName.textbook_qa}
        or tasks[1].intent != IntentName.quiz_generation
        or tasks[1].depends_on != [tasks[0].task_id]
    ):
        return None
    explain_task = tasks[0]
    quiz_task = tasks[1]
    message = str(req.get("message") or "").strip()
    count = quiz_task.count or _requested_count(message)
    if req.get("book_id") and req.get("lesson_id"):
        return [
            _tool_step("step_1", "读取教材课文", "get_textbook_lesson", {"book_id": req["book_id"], "lesson_id": req["lesson_id"]}, criteria=["tool_result_ok", "lesson_present"]),
            _generation_step("step_2", "生成简明解释", "answer_from_lesson", {"message": message, "topic": explain_task.topic}, depends_on=["step_1"]),
            _generation_step("step_3", f"生成 {count} 道练习", "quiz_from_lesson", {"message": message, "topic": quiz_task.topic, "count": count, "question_type": quiz_task.question_type or "choice"}, depends_on=["step_1", "step_2"], criteria=["question_count_matches"]),
        ]
    return [
        _tool_step("step_1", "查找可信史料", "search_history_knowledge", _search_payload(explain_task, req), criteria=["tool_result_ok", "source_count_gte_1"]),
        _generation_step("step_2", "生成简明解释", "answer_from_sources", {"message": message, "topic": explain_task.topic}, depends_on=["step_1"]),
        _generation_step("step_3", f"生成 {count} 道练习", "quiz_from_sources", {"message": message, "topic": quiz_task.topic, "count": count, "question_type": quiz_task.question_type or "choice"}, depends_on=["step_1", "step_2"], criteria=["question_count_matches"]),
    ]


def build_task_plan(route: RoutingDecision, req: dict[str, Any], *, enable_composition: bool | None = None) -> TaskPlan:
    enabled = planner_enabled() if enable_composition is None else enable_composition
    active_tasks = route.tasks if enabled else route.tasks[:1]
    steps = _composition_steps(active_tasks, req) if enabled and len(active_tasks) > 1 else None
    if steps is None:
        steps = _single_task_steps(active_tasks[0], req)
    objective = str(req.get("message") or "").strip()[:240] or active_tasks[0].intent.value
    return TaskPlan(objective=objective, steps=steps[:3], max_tool_calls=3)


def public_plan(plan: TaskPlan) -> dict[str, Any]:
    return {
        "schema_version": plan.schema_version,
        "objective": plan.objective,
        "steps": [
            {
                "step_id": step.step_id,
                "title": step.title,
                "kind": step.kind,
                "operation": step.operation,
                "depends_on": step.depends_on,
                "status": step.status,
            }
            for step in plan.steps
        ],
        "max_tool_calls": plan.max_tool_calls,
    }
