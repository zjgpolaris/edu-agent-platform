from __future__ import annotations

from time import perf_counter
from typing import Any, Iterator, Literal, TypedDict
from uuid import uuid4

from llm_config import llm_fast
from utils.cost_estimator import estimate_cost_from_chars
from security.prompt_injection import build_untrusted_context_block, check_user_input
from tracing import current_trace_id, set_trace_id
from trace_store import emit_trace_event
from student_profile import LearningEvent, get_student_profile, suggest_review_plan, try_record_learning_event
from tools.base import ToolExecutionContext
from user_memory import get_used_memory_entries
from tools.registry import run_tool

LearningIntent = Literal[
    "textbook_qa",
    "quiz_generation",
    "character_recommendation",
    "timeline_game",
    "history_search",
    "review_plan",
    "memory_delete_demo",
    "chat",
]


class LearningAssistantRequestData(TypedDict, total=False):
    message: str
    session_id: str | None
    student_id: str | None
    grade: str | None
    book_id: str | None
    lesson_id: str | None
    stream: bool
    actor_id: str | None
    actor_role: str | None
    confirmed_tool_name: str | None
    confirmation_token: str | None
    confirmation_decision: str | None


def detect_learning_intent(req: LearningAssistantRequestData) -> dict[str, Any]:
    message = (req.get("message") or "").strip()
    compact = message.replace(" ", "")
    has_lesson = bool(req.get("book_id") and req.get("lesson_id"))

    if any(token in compact for token in ["演示高风险工具", "删除演示记忆", "删除demomemory", "确认删除记忆"]):
        return {"intent": "memory_delete_demo", "confidence": 0.96, "reason": "命中高风险工具确认演示关键词"}
    if any(token in compact for token in ["出题", "练习", "测验", "小测", "考考我", "刷题", "复习知识点"]):
        return {"intent": "quiz_generation", "confidence": 0.92, "reason": "命中练习/测验关键词"}
    if any(token in compact for token in ["复习计划", "复习建议", "制定复习", "学习计划", "帮我复习"]):
        return {"intent": "review_plan", "confidence": 0.90, "reason": "命中复习计划关键词"}
    if any(token in compact for token in ["推荐人物", "和谁聊", "历史人物", "人物推荐"]):
        return {"intent": "character_recommendation", "confidence": 0.9, "reason": "命中历史人物推荐关键词"}
    if any(token in compact for token in ["时间线", "排序", "时间巨轮", "来一局", "游戏", "闯关"]):
        return {"intent": "timeline_game", "confidence": 0.88, "reason": "命中历史游戏关键词"}
    if has_lesson:
        return {"intent": "textbook_qa", "confidence": 0.82, "reason": "请求包含教材和课文上下文"}
    if any(token in compact for token in ["历史", "战争", "朝代", "皇帝", "变法", "革命", "为什么", "影响", "意义"]):
        return {"intent": "history_search", "confidence": 0.76, "reason": "命中历史问答关键词"}
    return {"intent": "chat", "confidence": 0.55, "reason": "未命中特定工具意图"}


def _infer_topic(message: str) -> str | None:
    for suffix in ["时间线游戏", "时间线", "游戏", "排序", "来一局"]:
        message = message.replace(suffix, " ")
    topic = " ".join(message.split()).strip(" ，。！？,.!?、")
    return topic or None


def _runtime_step(
    step_id: str,
    step_name: str,
    event_type: str,
    status: str,
    *,
    sequence: int,
    started_at: float | None = None,
    metadata: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    latency_ms = round((perf_counter() - started_at) * 1000, 2) if started_at is not None else None
    # Also emit to trace_store for persistent querying
    emit_trace_event(
        agent_name="learning_assistant",
        step_name=step_name,
        event_type=event_type,
        status=status,
        latency_ms=latency_ms,
        metadata=metadata,
    )
    return "runtime_step", {
        "trace_id": current_trace_id(),
        "agent_name": "learning_assistant",
        "step_id": step_id,
        "step_name": step_name,
        "sequence": sequence,
        "event_type": event_type,
        "status": status,
        "latency_ms": latency_ms,
        "metadata": metadata or {},
        "error": error,
    }


def _tool_context(req: LearningAssistantRequestData, tool_name: str | None) -> ToolExecutionContext:
    return ToolExecutionContext(
        actor_id=req.get("actor_id"),
        role=req.get("actor_role") or "anonymous",
        student_id=req.get("student_id"),
        confirmed=req.get("confirmation_decision") == "confirmed" and req.get("confirmed_tool_name") == tool_name,
        confirmation_token=req.get("confirmation_token"),
        request_source="learning_assistant",
    )


def _tool_summary(result: Any) -> dict[str, Any]:
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    data = payload.get("data") or {}
    metadata = payload.get("metadata") or {}
    summary: dict[str, Any] = {"tool_name": payload.get("tool_name"), "ok": payload.get("ok"), "metadata": metadata}
    result_summary = "工具执行完成" if payload.get("ok") else "工具未执行成功"
    if payload.get("error"):
        summary["error"] = payload["error"]
        result_summary = payload["error"].get("message") or result_summary
    if "sources" in data:
        sources = data.get("sources") or []
        summary["source_count"] = len(sources)
        summary["data"] = {"sources": sources[:4]}
        result_summary = f"返回 {len(sources)} 条史料片段"
    if "recommendations" in data:
        count = len(data.get("recommendations") or [])
        summary["recommendation_count"] = count
        result_summary = f"推荐 {count} 位历史人物"
    if "quiz" in data:
        count = len((data.get("quiz") or {}).get("questions") or [])
        summary["question_count"] = count
        result_summary = f"生成 {count} 道练习题"
    if "game" in data:
        game = data.get("game") or {}
        summary["round_id"] = game.get("round_id")
        summary["title"] = game.get("title") or game.get("round_title")
        result_summary = f"创建时间线游戏 {game.get('round_id') or game.get('title') or ''}".strip()
    if "lesson" in data:
        lesson = data.get("lesson") or {}
        count = len(lesson.get("items") or [])
        summary["lesson_title"] = lesson.get("lesson_title")
        summary["item_count"] = count
        result_summary = f"读取课文《{lesson.get('lesson_title') or '未命名课文'}》的 {count} 个知识点"
    if data.get("deleted"):
        result_summary = "删除 demo 范围内的学习记忆"
    for key in ["risk_level", "side_effect", "required_role", "requires_confirmation", "confirmation_token", "confirmation_expires_in_seconds", "duration_ms"]:
        if key in metadata:
            summary[key] = metadata[key]
    summary["result_summary"] = result_summary
    return summary


def _llm_runtime_metadata(*, generation_mode: str, response_chars: int) -> dict[str, Any]:
    model = getattr(llm_fast, "model", None)
    return {
        "llm_name": getattr(llm_fast, "name", "llm_fast"),
        "configured_model": model,
        "fallback_models": getattr(llm_fast, "fallback_models", []),
        "generation_mode": generation_mode,
        "response_chars": response_chars,
        **estimate_cost_from_chars(str(model or ""), output_chars=response_chars),
    }


def _fallback_history_answer(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "我暂时没有检索到足够的史料依据。你可以换一个更具体的历史事件、人物或时期来问。"
    first = sources[0]
    topic = first.get("topic") or "这个问题"
    snippet = first.get("snippet") or first.get("content") or ""
    return f"可以先从“{topic}”理解：{snippet}"


def _generate_quiz_from_sources(message: str, sources: list[dict[str, Any]], count: int = 3) -> list[dict[str, Any]]:
    import json as _json
    context = build_untrusted_context_block(sources[:4], title="史料")
    prompt = [
        {"role": "system", "content": (
            "你是初中历史教师。根据史料出练习题，以 JSON 数组返回，每项格式：\n"
            "{\"id\": \"q1\", \"question\": \"题干\", \"answer\": \"参考答案\", \"options\": null}\n"
            "选择题时 options 为 [\"A...\",\"B...\",\"C...\",\"D...\"]，answer 为正确选项字母。\n"
            "只输出 JSON 数组，不要其他文字。"
        )},
        {"role": "user", "content": f"根据以下史料，围绕\"{message}\"出 {count} 道题：\n{context}"},
    ]
    try:
        raw = llm_fast.invoke(prompt).content.strip()
        # strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return _json.loads(raw.strip())
    except Exception:
        return []


def _explain_topic(topic: str, sources: list[dict[str, Any]]) -> str:
    """Plain-text concept explanation for the review flow (no markdown, no embedded questions)."""
    context = build_untrusted_context_block(sources[:3], title="史料")
    prompt = [
        {"role": "system", "content": "你是初中历史教师。用2-3句清晰文字解释知识点，不使用任何Markdown符号，不出练习题，不加粗。"},
        {"role": "user", "content": f"请简要解释知识点「{topic}」。\n\n{context}"},
    ]
    try:
        return llm_fast.invoke(prompt).content.strip()
    except Exception:
        return ""


def _generate_history_answer(message: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return _fallback_history_answer(sources)
    context = build_untrusted_context_block(sources[:4], title="史料")
    prompt = [
        {"role": "system", "content": "你是初中历史学习助手。请基于给定史料回答，语言清楚、适合学生复习；不要编造未在材料中出现的细节。"},
        {"role": "user", "content": f"问题：{message}\n\n史料：\n{context}\n\n请用 2-4 句话回答，并点出一个可继续追问的方向。"},
    ]
    try:
        return llm_fast.invoke(prompt).content.strip()
    except Exception:
        return _fallback_history_answer(sources)


def _final_for_intent(intent: LearningIntent, message: str, tool_results: list[dict[str, Any]]) -> tuple[str, list[str]]:
    first = tool_results[0] if tool_results else None
    data = (first or {}).get("data") or {}
    if first and not first.get("ok"):
        error = first.get("error") or {}
        if error.get("code") == "confirmation_required":
            return error.get("message") or "这个工具需要你确认后才会执行。", ["确认执行高风险工具", "取消这次操作", "换成普通历史问答"]
        return error.get("message") or "这个工具暂时执行失败，你可以换个说法再试。", ["换个问题再试", "改成普通历史问答", "回到教材目录"]

    if intent == "quiz_generation":
        quiz = data.get("quiz") or {}
        questions = quiz.get("questions") or []
        if questions:
            return f"我已为你生成 {len(questions)} 道练习题。", ["再来 3 道选择题", "解释第 1 题", "换成简答题"]
        sources = data.get("sources") or []
        if sources:
            import re
            m = re.search(r"(\d+)\s*道", message)
            count = int(m.group(1)) if m else 1
            generated = _generate_quiz_from_sources(message, sources, count)
            if generated:
                import re as _re
                tag_m = _re.search(r"「(.+?)」", message)
                weakpoint_tag = tag_m.group(1) if tag_m else None
                metadata = {"question_count": len(generated)}
                if weakpoint_tag:
                    metadata["weakpoint_tag"] = weakpoint_tag
                trace_id = current_trace_id()
                if trace_id:
                    metadata["trace_id"] = trace_id
                tool_results.append({
                    "tool_name": "generate_quiz",
                    "ok": True,
                    "data": {"quiz": {"questions": generated}},
                    "metadata": metadata,
                })
                prefix = ""
                if weakpoint_tag and any(w in message for w in ["解释", "讲解", "先说"]):
                    prefix = _explain_topic(weakpoint_tag, sources) + "\n\n"
                return f"{prefix}已为你生成 {len(generated)} 道练习题，答对即可从错题本移除。", ["再来一道", "换成选择题", "我答对了，下一个知识点"]
        return "请先在左侧选择教材和课文，我可以为你生成针对性练习题。", ["选择教材后再试", "换成历史问答"]
    if intent == "character_recommendation":
        recommendations = data.get("recommendations") or []
        names = "、".join(item.get("name", "") for item in recommendations[:3] if item.get("name"))
        return f"我推荐你先和{names or '这些历史人物'}聊一聊。", ["开始和第一位人物对话", "换一个角度推荐", "只推荐教材覆盖高的人物"]
    if intent == "timeline_game":
        game = data.get("game") or {}
        title = game.get("title") or game.get("round_title") or "历史时间线游戏"
        return f"已创建《{title}》，你可以开始按时间顺序修复历史线索。", ["开始游戏", "换成困难难度", "围绕同一专题再来一局"]
    if intent == "textbook_qa":
        lesson = data.get("lesson") or {}
        lesson_title = lesson.get("lesson_title") or "这课内容"
        items = lesson.get("items") or []
        highlights = "；".join(f"{item.get('topic')}：{item.get('text')}" for item in items[:3])
        if highlights:
            return f"围绕《{lesson_title}》，可以先抓住这些要点：{highlights}", ["生成练习题", "总结本课", "推荐相关历史人物"]
        return f"我已读取《{lesson_title}》，你可以继续问这课的重点、影响或易错点。", ["生成练习题", "总结本课", "解释重点"]
    if intent == "history_search":
        return _generate_history_answer(message, data.get("sources") or []), ["生成练习题", "推荐相关历史人物", "换一个角度解释"]
    if intent == "memory_delete_demo":
        if data.get("deleted"):
            return "已完成高风险工具确认演示：只删除了 demo 范围内的学习记忆，没有影响真实学生画像。", ["再演示一次高风险工具", "查看工具轨迹", "换成普通历史问答"]
        return "这个演示工具用于展示高风险确认流程。", ["演示高风险工具，删除演示记忆", "换成普通历史问答"]
    if intent == "review_plan":
        actions = data.get("recommended_actions") or []
        if actions:
            plan_text = "；".join(actions[:3])
            return f"根据你的学习记录，建议：{plan_text}", ["生成针对性练习题", "推荐相关历史人物", "查看薄弱知识点"]
        return "暂时没有足够的学习记录来制定复习计划，先做几道练习题或和历史人物聊聊吧。", ["来一道练习题", "推荐一个历史人物"]
    return "我可以帮你查历史知识、生成练习题、推荐历史人物，或启动时间线游戏。", ["鸦片战争为什么重要？", "推荐一个历史人物", "来一局时间线游戏"]


def _record_assistant_event(
    req: LearningAssistantRequestData,
    *,
    event_type: str,
    intent: str,
    topic: str | None,
    tool_name: str | None = None,
    ok: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    student_id = req.get("student_id")
    if not student_id:
        return
    payload = {"intent": intent, **(metadata or {})}
    if tool_name:
        payload["tool_name"] = tool_name
    try_record_learning_event(
        LearningEvent(
            student_id=student_id,
            session_id=req.get("session_id"),
            feature="learning_assistant",
            event_type=event_type,
            grade=req.get("grade"),
            topic=topic,
            book_id=req.get("book_id"),
            lesson_id=req.get("lesson_id"),
            success=ok,
            metadata=payload,
        )
    )


def _personalize_suggestions(student_id: str | None, suggestions: list[str]) -> tuple[list[str], dict[str, Any] | None]:
    if not student_id:
        return suggestions, None
    try:
        profile = get_student_profile(student_id)
        plan = suggest_review_plan(student_id, limit=3)
    except Exception:
        return suggestions, None
    personalized = list(suggestions)
    for action in plan.get("recommended_actions") or []:
        if action not in personalized:
            personalized.insert(0, action)
    used_memory = get_used_memory_entries(student_id, limit=6)
    if not used_memory:
        if profile.weak_topics:
            used_memory.append({"memory_id": "profile.weak_topics", "type": "weak_point", "content": profile.weak_topics[:3], "reason": "用于优先生成复习建议。"})
        if plan.get("recent_topics"):
            used_memory.append({"memory_id": "profile.recent_topics", "type": "recent_activity", "content": plan["recent_topics"][:3], "reason": "用于推荐可继续追问的历史主题。"})
        if profile.character_interests:
            used_memory.append({"memory_id": "profile.character_interests", "type": "interest", "content": profile.character_interests[:3], "reason": "用于个性化历史人物对话建议。"})
    return personalized[:5], {"profile": profile.model_dump(), "review_plan": plan, "used_memory": used_memory}


def build_tool_call(intent: LearningIntent, req: LearningAssistantRequestData) -> tuple[str | None, dict[str, Any]]:
    message = (req.get("message") or "").strip()
    grade = req.get("grade")
    if intent == "review_plan":
        return "suggest_review_plan", {"student_id": req.get("student_id") or "anonymous", "limit": 5}
    if intent == "quiz_generation" and req.get("book_id") and req.get("lesson_id"):
        return "generate_quiz", {"book_id": req["book_id"], "lesson_id": req["lesson_id"], "count": 3}
    if intent == "character_recommendation":
        return "recommend_character", {"message": message, "grade": grade, "limit": 3}
    if intent == "timeline_game":
        return "start_timeline_game", {"grade": grade, "difficulty": "easy", "topic": _infer_topic(message), "student_id": req.get("student_id"), "mode": "llm"}
    if intent == "memory_delete_demo":
        return "delete_demo_memory", {
            "student_id": req.get("student_id") or "demo-student",
            "memory_id": "demo_wrong_memory_001",
            "reason": "演示 high-risk human confirmation",
        }
    if intent == "textbook_qa" and req.get("book_id") and req.get("lesson_id"):
        return "get_textbook_lesson", {"book_id": req["book_id"], "lesson_id": req["lesson_id"]}
    if intent in {"history_search", "quiz_generation", "textbook_qa"}:
        return "search_history_knowledge", {"query": message, "grade": grade, "topic": _infer_topic(message), "k": 4}
    return None, {}


def stream_learning_assistant_events(req: LearningAssistantRequestData) -> Iterator[tuple[str, dict[str, Any]]]:
    # Ensure trace_id is set for this call; generate a fresh one if the caller (e.g. eval) didn't provide one.
    set_trace_id(req.get("trace_id") or uuid4().hex)
    message = (req.get("message") or "").strip()
    receive_started = perf_counter()
    check_user_input(message)
    yield _runtime_step("receive_query", "Receive User Query", "request", "success", sequence=1, started_at=receive_started, metadata={"message_chars": len(message)})

    intent_started = perf_counter()
    intent_payload = detect_learning_intent(req)
    intent = intent_payload["intent"]
    topic = _infer_topic(message) if intent not in {"quiz_generation", "character_recommendation", "timeline_game", "memory_delete_demo"} else None
    _record_assistant_event(req, event_type="intent_detected", intent=intent, topic=topic, ok=True, metadata={"reason": intent_payload.get("reason")})
    yield _runtime_step("intent_detection", "Intent Detection", "intent", "success", sequence=2, started_at=intent_started, metadata=intent_payload)
    yield "intent", intent_payload

    tool_name, payload = build_tool_call(intent, req)
    tool_results: list[dict[str, Any]] = []
    if tool_name:
        input_summary = {key: value for key, value in payload.items() if key not in {"content", "text"}}
        tool_selection_metadata = {"tool_name": tool_name, "input_summary": input_summary}
        yield _runtime_step("tool_selection", "Tool Selection", "tool_selection", "success", sequence=3, metadata=tool_selection_metadata)
        yield "tool_start", {"tool_name": tool_name}
        tool_started = perf_counter()
        result = run_tool(tool_name, payload, context=_tool_context(req, tool_name))
        result_payload = result.model_dump()
        tool_results.append(result_payload)
        metadata: dict[str, Any] = {}
        data = result_payload.get("data") or {}
        if "recommendations" in data:
            metadata["characters"] = [item.get("name") for item in data.get("recommendations") or [] if item.get("name")]
        _record_assistant_event(req, event_type="tool_result", intent=intent, topic=topic, tool_name=tool_name, ok=result.ok, metadata=metadata)
        tool_summary = _tool_summary(result)
        error = result_payload.get("error") or {}
        runtime_error = {"code": error.get("code"), "message": error.get("message"), "retryable": error.get("retryable")} if error else None
        policy_status = "success"
        if error.get("code") == "confirmation_required":
            policy_status = "waiting_confirmation"
        elif error.get("code") in {"role_denied", "invalid_confirmation"}:
            policy_status = "failed"
        policy_metadata = {
            **tool_summary,
            "input_summary": input_summary,
            "error_code": error.get("code"),
            "confirmed": req.get("confirmation_decision") == "confirmed" and req.get("confirmed_tool_name") == tool_name,
        }
        yield _runtime_step(
            "tool_policy_check",
            "Tool Policy Check",
            "tool_governance",
            policy_status,
            sequence=4,
            started_at=tool_started,
            metadata=policy_metadata,
            error=runtime_error,
        )
        tool_status = "success" if result.ok else "waiting_confirmation" if error.get("code") == "confirmation_required" else "failed"
        yield _runtime_step(
            "tool_execution",
            "Tool Execution",
            "tool_result",
            tool_status,
            sequence=5,
            started_at=tool_started,
            metadata={**tool_summary, "input_summary": input_summary, "error_code": error.get("code")},
            error=runtime_error,
        )
        yield "tool_result", tool_summary

    answer_started = perf_counter()
    response, suggestions = _final_for_intent(intent, message, tool_results)
    answer_metadata = {
        "intent": intent,
        "used_tool_count": len(tool_results),
        **_llm_runtime_metadata(generation_mode="template_or_llm", response_chars=len(response)),
    }
    yield _runtime_step("answer_synthesis", "Answer Synthesis", "llm_or_template", "success", sequence=6, started_at=answer_started, metadata=answer_metadata)

    memory_started = perf_counter()
    suggestions, profile_context = _personalize_suggestions(req.get("student_id"), suggestions)
    _record_assistant_event(req, event_type="completed", intent=intent, topic=topic, ok=True, metadata={"tool_count": len(tool_results)})
    yield _runtime_step("memory_update", "Memory Update", "memory", "success", sequence=7, started_at=memory_started, metadata={"student_id": req.get("student_id"), "profile_context_loaded": bool(profile_context), "used_memory_count": len((profile_context or {}).get("used_memory") or []), "wrote_event": bool(req.get("student_id"))})
    trace_id = current_trace_id()
    if response:
        yield "delta", {"text": response}
    yield "final", {"response": response, "intent": intent, "tool_results": tool_results, "profile_context": profile_context, "trace_id": trace_id}
    yield "suggestions", {"suggestions": suggestions, "trace_id": trace_id}
