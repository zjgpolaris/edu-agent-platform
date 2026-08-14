from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from structured_output import invoke_structured


class IntentName(str, Enum):
    textbook_qa = "textbook_qa"
    quiz_generation = "quiz_generation"
    character_recommendation = "character_recommendation"
    timeline_game = "timeline_game"
    history_search = "history_search"
    review_plan = "review_plan"
    memory_delete_demo = "memory_delete_demo"
    chat = "chat"


class RoutedTask(BaseModel):
    task_id: str = Field(min_length=1, max_length=32)
    intent: IntentName
    topic: str | None = Field(default=None, max_length=120)
    count: int | None = Field(default=None, ge=1, le=10)
    question_type: Literal["choice", "short_answer", "mixed"] | None = None
    book_id: str | None = Field(default=None, max_length=160)
    lesson_id: str | None = Field(default=None, max_length=160)
    depends_on: list[str] = Field(default_factory=list, max_length=2)


class RoutingDecision(BaseModel):
    schema_version: Literal[2] = 2
    mode: Literal["rule", "semantic", "fallback", "clarification"]
    tasks: list[RoutedTask] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=240)
    missing_slots: list[str] = Field(default_factory=list, max_length=4)
    reason_code: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_clarification(self) -> "RoutingDecision":
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("clarification_question is required when needs_clarification is true")
        if any(task.intent == IntentName.memory_delete_demo for task in self.tasks) and len(self.tasks) != 1:
            raise ValueError("high-risk memory task cannot be combined")
        return self


_TRUE_VALUES = {"1", "true", "yes", "on"}
_COUNT_WORDS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_HIGH_RISK_TERMS = ("演示高风险工具", "删除演示记忆", "删除demomemory", "确认删除记忆")
_QUIZ_TERMS = ("出题", "题目", "练习题", "选择题", "简答题", "测验", "小测", "考考我", "刷题", "来几道", "来一道", "的题")
_REVIEW_TERMS = ("复习计划", "复习建议", "制定复习", "学习计划", "帮我复习", "安排复习", "安排一下复习", "怎么复习", "如何复习", "复习安排", "排接下来")
_CHARACTER_TERMS = ("推荐人物", "和谁聊", "历史人物", "人物推荐", "推荐一个人", "推荐一位", "谁适合讲")
_GAME_TERMS = ("时间线", "时间巨轮", "时间排序", "历史排序", "来一局", "玩一局", "闯关游戏")
_TEXTBOOK_REFERENCES = ("这节课", "这一课", "本课", "课文", "教材")
_TEXTBOOK_CONTEXT_ACTIONS = ("结合教材", "结合课文", "按教材", "用教材", "教材解释", "课文解释")
_FOLLOWUP_TERMS = ("它", "这个", "刚才", "上面", "再简单", "换个说法", "没懂", "还是不懂", "那它")
_HISTORY_MARKERS = (
    "历史", "战争", "朝代", "皇帝", "变法", "革命", "运动", "起义", "条约", "制度", "改革",
    "王朝", "秦始皇", "汉武帝", "唐太宗", "鸦片", "洋务", "辛亥", "五四", "甲午", "抗日",
    "三国", "秦朝", "汉朝", "唐朝", "宋朝", "元朝", "明朝", "清朝", "安史", "近代史", "古代史",
)
_EXPLAIN_TERMS = (
    "解释", "讲讲", "讲一下", "说明", "说说", "分析", "分析下", "分析一下",
    "简单的话", "简单解释", "怎么发生", "怎么起来", "为什么", "影响", "意义", "做了什么",
)
_COMPOSITION_TERMS = ("先", "再", "然后", "接着", "并且", "顺便", "之后")
_CHAT_TERMS = ("你好", "谢谢", "再见", "天气", "几点", "你是谁")


def env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def router_confidence_threshold() -> float:
    try:
        value = float(os.getenv("EDU_AGENT_ASSISTANT_ROUTER_CONFIDENCE_THRESHOLD", "0.65"))
    except ValueError:
        value = 0.65
    return min(0.95, max(0.5, value))


def _compact(message: str) -> str:
    return re.sub(r"\s+", "", message).lower()


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value.lower() in text for value in values)


def _extract_count(message: str) -> int | None:
    match = re.search(r"([1-9]|10)\s*道", message)
    if match:
        return int(match.group(1))
    match = re.search(r"([一二两三四五六七八九十])\s*道", message)
    if match:
        return _COUNT_WORDS.get(match.group(1))
    if "一道" in message:
        return 1
    if "几道" in message:
        return 3
    return None


def _question_type(message: str) -> Literal["choice", "short_answer", "mixed"] | None:
    compact = _compact(message)
    has_choice = "选择题" in compact
    has_short = "简答题" in compact or "问答题" in compact
    if has_choice and has_short:
        return "mixed"
    if has_choice:
        return "choice"
    if has_short:
        return "short_answer"
    return None


def _trusted_topic(req: dict[str, Any]) -> str | None:
    source_context = req.get("source_context") or {}
    topic = source_context.get("knowledge_point")
    if isinstance(topic, str) and topic.strip():
        return topic.strip()[:120]
    textbook = source_context.get("textbook") or {}
    lesson_title = textbook.get("lesson_title") or textbook.get("lesson")
    if isinstance(lesson_title, str) and lesson_title.strip():
        return lesson_title.strip()[:120]
    return None


def _topic_from_history(history: list[dict[str, Any]]) -> str | None:
    recent = list(reversed(history[-6:]))
    # User turns are a safer topic anchor than an assistant paraphrase. Otherwise
    # a sentence such as “英国为打开市场发动战争” can be mistaken for the entity.
    for preferred_role in ("user", "assistant"):
        for item in recent:
            if item.get("role") != preferred_role:
                continue
            content = str(item.get("content") or "")
            match = re.search(r"([\u4e00-\u9fff]{2,12}(?:战争|运动|革命|变法|改革|起义|条约|制度|王朝|朝))", content)
            if match:
                return match.group(1)[:120]
            for marker in _HISTORY_MARKERS:
                if marker in content and len(marker) >= 2:
                    return marker
            if preferred_role == "user":
                topic = _extract_short_learning_topic(content)
                if topic:
                    return topic
    return None


def _extract_short_learning_topic(text: str) -> str | None:
    compact = _compact(text)
    if not compact or _contains_any(compact, _CHAT_TERMS) or "能做什么" in compact:
        return None
    cleaned = re.sub(r"(请|帮我|能不能|可以|直接|结合教材|结合课文|教材|课文|历史|一下|吗|呢|吧)", "", text)
    cleaned = cleaned.strip(" ，。！？,.!?")
    cleaned = re.sub(
        r"(?:(?:失败|成功)的?)?(?:的)?(?:主要)?(?:原因|背景|经过|结果|影响|意义|作用|特点|贡献|目的|内容|措施|导火索)(?:是什么|有哪些|如何|怎么样|有多大)?$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"为什么(?:会)?(?:爆发|发生|失败|成功|结束|重要)?$", "", cleaned)
    for suffix in ("做了什么", "是什么", "为什么", "有什么影响", "有什么意义", "怎么评价", "怎么理解", "介绍一下", "讲讲", "解释"):
        cleaned = cleaned.replace(suffix, " ")
    candidates = [
        item.strip(" ，。！？,.!?、的")
        for item in re.split(r"[，。！？,.!?、\s]+", cleaned)
        if item.strip(" ，。！？,.!?、的")
    ]
    for candidate in candidates:
        if 2 <= len(candidate) <= 12 and re.fullmatch(r"[\u4e00-\u9fff]+", candidate):
            return candidate[:120]
    return None


def _extract_topic(message: str, req: dict[str, Any]) -> str | None:
    quoted = re.search(r"[「『\"]([^」』\"]{2,80})[」』\"]", message)
    if quoted:
        return quoted.group(1).strip()[:120]
    for prefix in (
        "我指的是", "指的是", "关于", "针对", "围绕", "分析一下", "分析下", "分析",
        "讲讲", "解释一下", "解释", "我想了解", "我想学",
    ):
        match = re.search(prefix + r"\s*([^，。！？,.!?]{2,40})", message)
        if match:
            candidate = match.group(1)
            candidate = re.split(r"(?:给我|帮我|再|然后|并且|顺便|的原因|的影响|的意义|为什么|怎么|如何|，)", candidate)[0]
            candidate = re.sub(r"(?:来|出)?(?:[一二两三四五六七八九十\d几]+)?道?(?:选择题|简答题|练习题|题目)$", "", candidate)
            candidate = candidate.strip(" ，。！？,.!?的")
            if 1 < len(candidate) <= 40:
                return candidate[:120]
    normalized_topic = _extract_short_learning_topic(message)
    if normalized_topic and _contains_any(_compact(message), _HISTORY_MARKERS):
        return normalized_topic
    for marker in sorted(_HISTORY_MARKERS, key=len, reverse=True):
        if marker in message and marker not in {"历史", "战争", "运动", "革命", "朝代", "皇帝", "制度", "改革", "王朝", "古代史", "近代史"}:
            match = re.search(rf"([\u4e00-\u9fff]{{0,8}}{re.escape(marker)})", message)
            return (match.group(1) if match else marker)[-20:]
    if _contains_any(_compact(message), _FOLLOWUP_TERMS):
        return _trusted_topic(req) or _topic_from_history(req.get("conversation_history") or [])
    return _trusted_topic(req) or _extract_short_learning_topic(message)


def _task(
    task_id: str,
    intent: IntentName,
    *,
    topic: str | None = None,
    count: int | None = None,
    question_type: Literal["choice", "short_answer", "mixed"] | None = None,
    req: dict[str, Any],
    depends_on: list[str] | None = None,
) -> RoutedTask:
    return RoutedTask(
        task_id=task_id,
        intent=intent,
        topic=topic,
        count=count,
        question_type=question_type,
        book_id=req.get("book_id"),
        lesson_id=req.get("lesson_id"),
        depends_on=depends_on or [],
    )


def _pending_clarification(history: list[dict[str, Any]]) -> tuple[IntentName, list[str]] | None:
    if not history:
        return None
    latest = history[-1]
    if latest.get("role") != "assistant":
        return None
    metadata = latest.get("metadata") or {}
    routing = metadata.get("routing") or {}
    if routing.get("completion_status") != "needs_clarification" and metadata.get("completion_status") != "needs_clarification":
        return None
    created_at = latest.get("created_at")
    if isinstance(created_at, str) and created_at:
        try:
            timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - timestamp).total_seconds() > 1800:
                return None
        except ValueError:
            return None
    pending = routing.get("pending_task") or {}
    try:
        intent = IntentName(str(pending.get("intent") or ""))
    except ValueError:
        return None
    missing = routing.get("missing_slots") or []
    return intent, [str(item) for item in missing if isinstance(item, str)]


def deterministic_route(req: dict[str, Any]) -> RoutingDecision:
    message = str(req.get("message") or "").strip()
    compact = _compact(message)
    has_lesson = bool(req.get("book_id") and req.get("lesson_id"))
    history = req.get("conversation_history") or []
    has_context = bool(history or req.get("source_context"))
    topic = _extract_topic(message, req)
    count = _extract_count(message)
    question_type = _question_type(message)

    if _contains_any(compact, _HIGH_RISK_TERMS):
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.memory_delete_demo, req=req)], confidence=0.99, reason_code="explicit_high_risk_demo")

    quiz_signal = _contains_any(compact, _QUIZ_TERMS)
    explain_signal = _contains_any(compact, _EXPLAIN_TERMS)
    composition_signal = quiz_signal and explain_signal and _contains_any(compact, _COMPOSITION_TERMS)
    if composition_signal:
        first_intent = IntentName.textbook_qa if has_lesson else IntentName.history_search
        return RoutingDecision(
            mode="rule",
            tasks=[
                _task("task_1", first_intent, topic=topic, req=req),
                _task("task_2", IntentName.quiz_generation, topic=topic, count=count or 3, question_type=question_type or "choice", req=req, depends_on=["task_1"]),
            ],
            confidence=0.94,
            reason_code="multi_intent_explain_then_quiz",
        )

    if quiz_signal:
        return RoutingDecision(
            mode="rule",
            tasks=[_task("task_1", IntentName.quiz_generation, topic=topic, count=count or 3, question_type=question_type, req=req)],
            confidence=0.95,
            reason_code="explicit_quiz_request",
        )

    if _contains_any(compact, _REVIEW_TERMS):
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.review_plan, topic=topic, req=req)], confidence=0.93, reason_code="review_plan_request")
    if _contains_any(compact, _CHARACTER_TERMS):
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.character_recommendation, topic=topic, req=req)], confidence=0.94, reason_code="character_request")
    if _contains_any(compact, _GAME_TERMS):
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.timeline_game, topic=topic, req=req)], confidence=0.94, reason_code="timeline_game_request")

    pending = _pending_clarification(history)
    is_minimal_clarification_answer = len(message) <= 40 and not explain_signal and not _contains_any(compact, _COMPOSITION_TERMS)
    if pending and is_minimal_clarification_answer and topic:
        pending_intent, _ = pending
        return RoutingDecision(
            mode="rule",
            tasks=[_task("task_1", pending_intent, topic=topic, count=count if pending_intent == IntentName.quiz_generation else None, question_type=question_type, req=req)],
            confidence=0.9,
            reason_code="pending_clarification_resolved",
        )

    textbook_reference = _contains_any(compact, _TEXTBOOK_REFERENCES)
    textbook_context_action = _contains_any(compact, _TEXTBOOK_CONTEXT_ACTIONS)
    if textbook_context_action and not topic:
        topic = _topic_from_history(history)
    if has_lesson:
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.textbook_qa, topic=topic, req=req)], confidence=0.94, reason_code="trusted_textbook_context")
    if textbook_context_action and topic:
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.history_search, topic=topic, req=req)], confidence=0.88, reason_code="textbook_reference_with_history_topic")
    if textbook_reference and not _trusted_topic(req):
        return RoutingDecision(
            mode="clarification",
            tasks=[_task("task_1", IntentName.textbook_qa, req=req)],
            confidence=0.92,
            needs_clarification=True,
            clarification_question="你指的是哪一本教材、哪一课？也可以直接告诉我课名。",
            missing_slots=["book_id", "lesson_id"],
            reason_code="missing_textbook_context",
        )

    followup = has_context and _contains_any(compact, _FOLLOWUP_TERMS)
    history_signal = _contains_any(compact, _HISTORY_MARKERS) or (explain_signal and topic is not None) or followup
    if history_signal:
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.history_search, topic=topic, req=req)], confidence=0.88 if topic else 0.75, reason_code="history_learning_request")

    if _contains_any(compact, _CHAT_TERMS) or len(compact) <= 4:
        return RoutingDecision(mode="rule", tasks=[_task("task_1", IntentName.chat, topic=topic, req=req)], confidence=0.86, reason_code="general_chat")
    return RoutingDecision(mode="fallback", tasks=[_task("task_1", IntentName.chat, topic=topic, req=req)], confidence=0.6, reason_code="no_supported_intent_match")


def _semantic_prompt(req: dict[str, Any], fallback: RoutingDecision) -> list[dict[str, str]]:
    history = req.get("conversation_history") or []
    history_text = "\n".join(
        f"{item.get('role')}: {str(item.get('content') or '')[:200]}"
        for item in history[-6:]
        if item.get("role") in {"user", "assistant"}
    )
    trusted = req.get("source_context") or {}
    return [
        {
            "role": "system",
            "content": (
                "你是教育学习助手的路由器。只输出严格 JSON，并遵守 RoutingDecision schema。"
                "intent 只能是 textbook_qa、quiz_generation、character_recommendation、timeline_game、history_search、review_plan、chat。"
                "最多三个任务。不要输出 memory_delete_demo，该意图只允许服务端规则产生。"
                "缺少执行所需的教材或主题时设置 needs_clarification=true，并只问一个最小问题。"
                "不得把天气、闲聊或非历史问题当成历史检索。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前问题：{str(req.get('message') or '')[:500]}\n"
                f"最近对话：\n{history_text}\n"
                f"可信课程上下文：{str(trusted)[:1200]}\n"
                f"规则候选：{fallback.model_dump(mode='json')}"
            ),
        },
    ]


def _sanitize_semantic(decision: RoutingDecision, req: dict[str, Any]) -> RoutingDecision:
    safe_items: list[RoutedTask] = []
    for item in decision.tasks[:3]:
        if item.intent == IntentName.memory_delete_demo:
            continue
        safe_items.append(item)
    if not safe_items:
        return deterministic_route(req)
    safe_items.sort(key=lambda item: item.intent == IntentName.timeline_game)
    tasks: list[RoutedTask] = []
    for index, item in enumerate(safe_items, start=1):
        task_id = f"task_{index}"
        tasks.append(item.model_copy(update={
            "task_id": task_id,
            "book_id": req.get("book_id"),
            "lesson_id": req.get("lesson_id"),
            "topic": (item.topic or _extract_topic(str(req.get("message") or ""), req)),
            "depends_on": [f"task_{index - 1}"] if index > 1 else [],
        }))
    return decision.model_copy(update={"mode": "semantic", "tasks": tasks})


def route_learning_request(
    req: dict[str, Any],
    *,
    llm: Any | None = None,
    semantic_enabled: bool | None = None,
    shadow_mode: bool | None = None,
    rule_decision: RoutingDecision | None = None,
) -> tuple[RoutingDecision, RoutingDecision | None]:
    """Return the active route and an optional shadow semantic decision."""
    rule = rule_decision or deterministic_route(req)
    enabled = env_enabled("EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED") if semantic_enabled is None else semantic_enabled
    shadow = env_enabled("EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE", True) if shadow_mode is None else shadow_mode
    should_use_semantic = enabled and (
        rule.mode == "fallback"
        or len(rule.tasks) > 1
        or rule.needs_clarification
        or rule.confidence < 0.85
    )
    if not should_use_semantic or llm is None:
        return rule, None
    try:
        semantic = invoke_structured(llm, _semantic_prompt(req, rule), model=RoutingDecision, fallback=None, repair=False)
        if not isinstance(semantic, RoutingDecision):
            return rule, None
        semantic = _sanitize_semantic(semantic, req)
        if semantic.confidence < router_confidence_threshold() and not semantic.needs_clarification:
            semantic = semantic.model_copy(update={
                "mode": "clarification",
                "needs_clarification": True,
                "clarification_question": "你最想先完成什么：理解知识点、制定复习计划，还是生成练习题？",
                "missing_slots": ["intent"],
                "reason_code": "low_router_confidence",
            })
        return (rule, semantic) if shadow else (semantic, None)
    except Exception:
        return rule, None


def legacy_intent_payload(decision: RoutingDecision) -> dict[str, Any]:
    primary = decision.tasks[0]
    return {
        "intent": primary.intent.value,
        "confidence": decision.confidence,
        "reason": decision.reason_code,
        "mode": decision.mode,
        "task_count": len(decision.tasks),
        "needs_clarification": decision.needs_clarification,
    }
