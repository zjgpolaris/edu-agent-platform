from __future__ import annotations

import re
from time import perf_counter
from typing import Any, Iterator, Literal, TypedDict
from uuid import uuid4

from agents.learning_assistant_planner import PlanStep, build_task_plan, public_plan
from agents.learning_assistant_rollout import build_rollout_decision
from agents.answer_verifier import canonical_source_id, citation_supports_claim, verify_answer_evidence
from agents.learning_assistant_router import IntentName, RoutingDecision, deterministic_route, legacy_intent_payload, route_learning_request
from agents.learning_assistant_runtime import stream_task_plan
from llm_config import llm_fast
from rag.history_query import aspect_query_label
from utils.cost_estimator import estimate_cost_from_chars
from security.prompt_injection import build_untrusted_context_block, check_user_input
from tracing import current_trace_id, set_trace_id
from trace_store import emit_trace_event
from student_profile import LearningEvent, get_student_profile, suggest_review_plan, try_record_learning_event
from tools.base import ToolExecutionContext
from user_memory import get_used_memory_entries
from tools.registry import issue_runtime_confirmation_token, run_tool

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
    conversation_history: list[dict[str, Any]]
    source_context: dict[str, Any]
    source_feature: str | None
    source_session_id: str | None
    trace_id: str | None
    idempotency_key: str | None


def detect_learning_intent(req: LearningAssistantRequestData) -> dict[str, Any]:
    # Compatibility facade for existing callers and evals. It intentionally uses
    # the deterministic half of the v2 router so a component test never incurs an
    # external model call.
    decision, _ = route_learning_request(dict(req), semantic_enabled=False)
    return legacy_intent_payload(decision)


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


def _tool_context(req: LearningAssistantRequestData, tool_name: str | None, step_id: str | None = None) -> ToolExecutionContext:
    runtime_contracts = req.get("_runtime_step_contracts") or {}
    contract = runtime_contracts.get(step_id or "") if isinstance(runtime_contracts, dict) else None
    runtime_run_id = req.get("_runtime_run_id")
    return ToolExecutionContext(
        actor_id=req.get("actor_id"),
        role=req.get("actor_role") or "anonymous",
        student_id=req.get("student_id"),
        confirmed=req.get("confirmation_decision") == "confirmed" and req.get("confirmed_tool_name") == tool_name,
        confirmation_token=req.get("confirmation_token"),
        request_source="learning_assistant",
        run_id=runtime_run_id,
        step_id=step_id if runtime_run_id else None,
        run_revision=req.get("_runtime_run_revision") if runtime_run_id else None,
        idempotency_key=(contract or {}).get("idempotency_key") if runtime_run_id and isinstance(contract, dict) else None,
        capability_operation=(contract or {}).get("operation") if runtime_run_id and isinstance(contract, dict) else None,
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
        retrieval_status = str(data.get("retrieval_status") or metadata.get("retrieval_status") or "")
        summary["data"] = {
            "sources": sources[:4],
            "retrieval_status": retrieval_status or None,
            "evidence_sufficiency": data.get("evidence_sufficiency"),
        }
        if retrieval_status == "sufficient":
            result_summary = f"找到 {len(sources)} 条依据"
        elif retrieval_status == "partial":
            result_summary = "找到部分相关依据"
        elif retrieval_status == "none":
            result_summary = "未找到足够依据"
        else:
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


def _source_fact(source: dict[str, Any], focus_topic: str | None) -> str:
    raw = str(source.get("snippet") or source.get("claim") or source.get("content") or "")
    cleaned = re.sub(r"\s+", "", raw).replace("[truncated40chars]", "")
    sentences = [part.strip(" ，。！？；") for part in re.split(r"[。！？；]", cleaned) if part.strip(" ，。！？；")]
    if focus_topic:
        focused = [sentence for sentence in sentences if focus_topic in sentence]
        if focused:
            return focused[0][:160]
    return (sentences[0] if sentences else cleaned)[:160]


def _source_label(source: dict[str, Any]) -> str:
    parts = [str(source.get("source") or "").strip(), str(source.get("lesson") or "").strip()]
    if source.get("page") not in (None, ""):
        parts.append(f"第{source['page']}页")
    return "，".join(part for part in parts if part)


_ANSWER_ASPECTS = ("原因", "背景", "经过", "结果", "影响", "意义", "作用", "特点", "贡献", "目的", "内容", "措施", "导火索")


def _fallback_history_answer(
    sources: list[dict[str, Any]],
    focus_topic: str | None = None,
    question: str = "",
    retrieval_status: str = "sufficient",
    aspect: str = "fact",
) -> str:
    if not sources:
        topic_text = f"“{focus_topic}”" if focus_topic else "这个问题"
        return f"当前教材知识库没有检索到足够依据来回答{topic_text}。你可以补充教材课次，或换一个更具体的历史事件、人物或时期来问。"
    topic = focus_topic or sources[0].get("topic") or "这个问题"
    collection_members = list(dict.fromkeys(
        str(member).strip()
        for source in sources
        for member in (source.get("collection_members") or [])
        if str(member).strip()
    ))
    if collection_members:
        labels = list(dict.fromkeys(
            label for source in sources if (label := _source_label(source))
        ))[:3]
        answer = f"根据当前教材知识库，明确提到的中国古代以少胜多战役包括：{'、'.join(collection_members)}。"
        if labels:
            answer += f"依据：{'；'.join(labels)}。"
        return answer
    source_facts = [(source, _source_fact(source, focus_topic)) for source in sources[:4]]
    source_facts = [(source, fact) for source, fact in source_facts if fact]
    answer_bearing_facts = [(source, fact) for source, fact in source_facts if source.get("answer_bearing") is True]
    if answer_bearing_facts:
        source_facts = answer_bearing_facts
    aspects = [aspect for aspect in _ANSWER_ASPECTS if aspect in question]
    focused_facts = [(source, fact) for source, fact in source_facts if any(aspect in fact for aspect in aspects)]
    if focused_facts:
        source_facts = focused_facts
    facts = list(dict.fromkeys(fact for _, fact in source_facts))[:3]
    labels = list(dict.fromkeys(label for source, _ in source_facts if (label := _source_label(source))))[:2]
    fact_text = "；".join(facts)
    only_curated = all(source.get("source_tier") == "L3_CURATED_REFERENCE" for source, _ in source_facts)
    prefix = "补充资料显示" if only_curated else "根据当前教材中能检索到的内容"
    answer = f"{prefix}，关于{topic}可以确认：{fact_text}。"
    if retrieval_status == "partial":
        aspect_text = aspect_query_label(aspect) or "当前问题"
        answer += f"但现有材料没有直接、完整地回答“{aspect_text}”，因此这里只能作为相关依据，不能当作完整结论。"
    if labels:
        answer += f"依据：{'；'.join(labels)}。"
    return answer


def _fallback_quiz_from_sources(message: str, sources: list[dict[str, Any]], count: int = 3, question_type: str = "mixed") -> list[dict[str, Any]]:
    import re

    count = max(1, min(int(count or 1), 10))
    topic_match = re.search(r"[「『\"]([^」』\"]+)[」』\"]", message)
    topic = topic_match.group(1) if topic_match else str((sources[0] if sources else {}).get("topic") or message).strip(" ，。！？")[:40]
    snippets = [str(item.get("snippet") or item.get("content") or "").strip() for item in sources if str(item.get("snippet") or item.get("content") or "").strip()]
    basis = snippets[0][:180] if snippets else f"{topic}的核心史实、原因和影响"
    source_item_ids = [canonical_source_id(sources[0])] if sources else []
    questions: list[dict[str, Any]] = []
    for index in range(count):
        use_choice = question_type == "choice" or (question_type == "mixed" and index % 2 == 0)
        if use_choice:
            questions.append({
                "id": f"q{index + 1}",
                "question": f"关于“{topic}”，下列哪一项最符合史料？",
                "options": [f"A. {basis}", "B. 与该主题无关的说法", "C. 把不同历史时期混为一谈", "D. 完全否定其历史影响"],
                "answer": "A",
                "explanation": f"史料依据：{basis}",
                "source_item_ids": source_item_ids,
            })
        else:
            questions.append({
                "id": f"q{index + 1}",
                "question": f"请结合史料概括“{topic}”的一个关键事实或影响。",
                "options": None,
                "answer": basis,
                "explanation": f"回答应围绕：{basis}",
                "source_item_ids": source_item_ids,
            })
    return questions


def _generate_quiz_from_sources(message: str, sources: list[dict[str, Any]], count: int = 3, question_type: str = "mixed") -> tuple[list[dict[str, Any]], str]:
    import json as _json  # noqa: F401 kept for other local uses
    from structured_output import StructuredOutputError, invoke_structured
    annotated_sources = [{**source, "source_id": canonical_source_id(source)} for source in sources[:4]]
    valid_source_ids = {item["source_id"] for item in annotated_sources}
    context = build_untrusted_context_block(annotated_sources, title="史料")
    prompt = [
        {"role": "system", "content": (
            "你是初中历史教师。根据史料出练习题，以 JSON 数组返回，每项格式：\n"
            "{\"id\": \"q1\", \"question\": \"题干\", \"answer\": \"参考答案\", \"options\": null, \"source_item_ids\": [\"source_id\"]}\n"
            "选择题时 options 为 [\"A...\",\"B...\",\"C...\",\"D...\"]，answer 为正确选项字母。\n"
            "每道题必须引用至少一个输入史料中的 source_id，不得编造 source_id。\n"
            "只输出 JSON 数组，不要其他文字。"
        )},
        {"role": "user", "content": f"根据以下史料，围绕\"{message}\"出 {count} 道题：\n{context}"},
    ]
    try:
        generated = invoke_structured(llm_fast, prompt, expect="list", fallback=[])
        if isinstance(generated, list) and len(generated) >= count:
            normalized: list[dict[str, Any]] = []
            for item in generated[:count]:
                if not isinstance(item, dict):
                    normalized = []
                    break
                raw_ids = item.get("source_item_ids") or item.get("source_ids") or []
                source_ids = [str(value).strip() for value in raw_ids if str(value).strip()]
                if not source_ids or any(source_id not in valid_source_ids for source_id in source_ids):
                    normalized = []
                    break
                normalized.append({**item, "source_item_ids": list(dict.fromkeys(source_ids))})
            if len(normalized) == count:
                return normalized, "llm"
    except StructuredOutputError:
        pass
    return _fallback_quiz_from_sources(message, annotated_sources, count, question_type), "fallback"


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


def _history_text(history: list[dict[str, Any]], *, limit: int = 6) -> str:
    return "\n".join(f"{item.get('role')}: {str(item.get('content') or '')[:300]}" for item in history[-limit:] if item.get("role") in {"user", "assistant"})


def _source_context_text(context: dict[str, Any]) -> str:
    if not context:
        return ""
    teaching = context.get("teaching") or {}
    return (
        f"当前知识点：{context.get('knowledge_point') or ''}\n"
        f"难度：{context.get('difficulty') or ''}\n"
        f"当前讲解：{teaching.get('explanation') or ''}\n"
        f"当前题干：{context.get('question') or ''}"
    ).strip()


def _generate_history_answer(
    message: str,
    sources: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
    source_context: dict[str, Any] | None = None,
    focus_topic: str | None = None,
    retrieval_status: str = "sufficient",
    aspect: str = "fact",
) -> tuple[str, str]:
    if not sources:
        return _fallback_history_answer([], focus_topic, message, retrieval_status, aspect), "fallback"
    if retrieval_status != "sufficient":
        return _fallback_history_answer(sources, focus_topic, message, retrieval_status, aspect), "fallback"
    answer_sources = [source for source in sources if source.get("answer_bearing") is True] or sources
    context = build_untrusted_context_block(answer_sources[:4], title="史料")
    conversation = _history_text(history or [])
    course_context = _source_context_text(source_context or {})
    prompt = [
        {"role": "system", "content": "你是初中历史学习助手。请基于给定史料直接回答问题，语言清楚、适合学生复习；只使用与当前主题相关的材料，不要编造未在材料中出现的细节。必须优先且主要回答当前问题要求的维度，例如原因、经过、结果、影响或意义；除非理解结论必不可少，不要补写其他维度的背景和过程。回答人物问题时，先说明人物本人的贡献；后人继承其思想或风格只能表述为影响，不能写成人物本人的行为。"},
        {"role": "user", "content": f"课程上下文：\n{course_context}\n\n最近对话：\n{conversation}\n\n当前主题：{focus_topic or ''}\n当前问题：{message}\n\n史料：\n{context}\n\n请用 2-3 句话直接回答，不要复述整段史料，并在末尾简要注明教材课次或页码。"},
    ]
    try:
        response = llm_fast.invoke(prompt).content.strip()
        if response:
            return response, "llm"
    except Exception:
        pass
    return _fallback_history_answer(sources, focus_topic, message, retrieval_status, aspect), "fallback"


def _generate_chat_answer(message: str, history: list[dict[str, Any]], source_context: dict[str, Any]) -> tuple[str, str]:
    conversation = _history_text(history)
    course_context = _source_context_text(source_context)
    prompt = [
        {"role": "system", "content": (
            "你是面向初中生的学习助手。直接回答当前学习问题，并结合最近对话解决“它、这个、刚才”等指代。"
            "如果信息不足，要明确说不知道并建议学生把问题说具体；不要只介绍你能做什么。回答控制在2-5句。"
        )},
        {"role": "user", "content": f"可信课程上下文：\n{course_context}\n\n最近对话：\n{conversation}\n\n当前问题：{message}"},
    ]
    try:
        response = llm_fast.invoke(prompt).content.strip()
        if response:
            return response, "llm"
    except Exception:
        pass
    topic = source_context.get("knowledge_point")
    if topic:
        return f"你问的是当前知识点「{topic}」。可以结合刚才的讲解继续理解：{(source_context.get('teaching') or {}).get('explanation') or '先抓住核心史实、原因和影响。'}", "fallback"
    if history:
        return "你是在继续追问刚才的内容。请把想进一步理解的人物、事件或观点说得更具体一些，我会接着解释。", "fallback"
    return f"关于“{message}”，请补充对应的历史人物、事件或教材章节，我会结合史料具体回答。", "fallback"


def _final_for_intent(intent: LearningIntent, message: str, tool_results: list[dict[str, Any]], *, history: list[dict[str, Any]] | None = None, source_context: dict[str, Any] | None = None) -> tuple[str, list[str], str]:
    first = tool_results[0] if tool_results else None
    data = (first or {}).get("data") or {}
    if first and not first.get("ok"):
        error = first.get("error") or {}
        if error.get("code") == "confirmation_required":
            return error.get("message") or "这个工具需要你确认后才会执行。", ["确认执行高风险工具", "取消这次操作", "换成普通历史问答"], "template"
        return error.get("message") or "这个工具暂时执行失败，你可以换个说法再试。", ["换个问题再试", "改成普通历史问答", "回到教材目录"], "template"

    if intent == "quiz_generation":
        quiz = data.get("quiz") or {}
        questions = quiz.get("questions") or []
        if questions:
            return f"我已为你生成 {len(questions)} 道练习题。", ["再来 3 道选择题", "解释第 1 题", "换成简答题"], "template"
        sources = data.get("sources") or []
        if sources:
            import re
            m = re.search(r"(\d+)\s*道", message)
            count = int(m.group(1)) if m else 1
            generated, quiz_mode = _generate_quiz_from_sources(message, sources, count)
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
                return f"{prefix}已为你生成 {len(generated)} 道练习题，答对即可从错题本移除。", ["再来一道", "换成选择题", "我答对了，下一个知识点"], quiz_mode
        return "请先在左侧选择教材和课文，我可以为你生成针对性练习题。", ["选择教材后再试", "换成历史问答"], "template"
    if intent == "character_recommendation":
        recommendations = data.get("recommendations") or []
        names = "、".join(item.get("name", "") for item in recommendations[:3] if item.get("name"))
        return f"我推荐你先和{names or '这些历史人物'}聊一聊。", ["开始和第一位人物对话", "换一个角度推荐", "只推荐教材覆盖高的人物"], "template"
    if intent == "timeline_game":
        game = data.get("game") or {}
        title = game.get("title") or game.get("round_title") or "历史时间线游戏"
        return f"已创建《{title}》，你可以开始按时间顺序修复历史线索。", ["开始游戏", "换成困难难度", "围绕同一专题再来一局"], "template"
    if intent == "textbook_qa":
        lesson = data.get("lesson") or {}
        lesson_title = lesson.get("lesson_title") or "这课内容"
        items = lesson.get("items") or []
        highlights = "；".join(f"{item.get('topic')}：{item.get('text')}" for item in items[:3])
        if highlights:
            return f"围绕《{lesson_title}》，可以先抓住这些要点：{highlights}", ["生成练习题", "总结本课", "推荐相关历史人物"], "template"
        return f"我已读取《{lesson_title}》，你可以继续问这课的重点、影响或易错点。", ["生成练习题", "总结本课", "解释重点"], "template"
    if intent == "history_search":
        response, generation_mode = _generate_history_answer(message, data.get("sources") or [], history, source_context)
        return response, ["生成练习题", "换一个角度解释", "再简单一点"], generation_mode
    if intent == "memory_delete_demo":
        if data.get("deleted"):
            return "已完成高风险工具确认演示：只删除了 demo 范围内的学习记忆，没有影响真实学生画像。", ["再演示一次高风险工具", "查看工具轨迹", "换成普通历史问答"], "template"
        return "这个演示工具用于展示高风险确认流程。", ["演示高风险工具，删除演示记忆", "换成普通历史问答"], "template"
    if intent == "review_plan":
        actions = (data.get("review_plan") or data).get("recommended_actions") or []
        if actions:
            plan_text = "；".join(actions[:3])
            return f"根据你的学习记录，建议：{plan_text}", ["生成针对性练习题", "推荐相关历史人物", "查看薄弱知识点"], "template"
        return "暂时没有足够的学习记录来制定复习计划，先做几道练习题或和历史人物聊聊吧。", ["来一道练习题", "推荐一个历史人物"], "template"
    response, generation_mode = _generate_chat_answer(message, history or [], source_context or {})
    return response, ["换个简单的说法", "结合教材解释", "围绕这个知识点出一道题"], generation_mode


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


def _personalize_suggestions(
    student_id: str | None,
    suggestions: list[str],
    *,
    include_review_actions: bool = True,
) -> tuple[list[str], dict[str, Any] | None]:
    if not student_id:
        return suggestions, None
    try:
        profile = get_student_profile(student_id)
        plan = suggest_review_plan(student_id, limit=3)
    except Exception:
        return suggestions, None
    personalized = list(suggestions)
    if include_review_actions:
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
        context_topic = (req.get("source_context") or {}).get("knowledge_point")
        previous_user = next((str(item.get("content") or "") for item in reversed(req.get("conversation_history") or []) if item.get("role") == "user"), "")
        query = " ".join(part for part in [str(context_topic or ""), previous_user, message] if part).strip()[:500]
        return "search_history_knowledge", {"query": query or message, "grade": grade, "topic": context_topic or _infer_topic(message), "k": 4}
    return None, {}


def _dependency_data(outputs: dict[str, dict[str, Any]], key: str) -> Any:
    for output in outputs.values():
        payload = output.get("payload") or {}
        data = payload.get("data") or {}
        if key in data:
            return data.get(key)
    return None


def _source_excerpt(source: dict[str, Any]) -> str:
    return str(source.get("snippet") or source.get("content") or source.get("text") or "").strip()[:500]


def _evidence_claim(
    operation: str,
    claim_id: str,
    text: str,
    sources: list[dict[str, Any]],
    *,
    source_ids: list[str] | None = None,
) -> dict[str, Any]:
    selected = set(source_ids) if source_ids is not None else None
    candidates = [
        {"source_id": canonical_source_id(source), "quote": _source_excerpt(source)}
        for source in sources
        if _source_excerpt(source) and (selected is None or canonical_source_id(source) in selected)
    ]
    citations = [item for item in candidates if citation_supports_claim(text, item["quote"])] or candidates
    return {
        "claim_id": claim_id,
        "operation": operation,
        "text": text[:2000],
        "critical": bool(re.search(r"(?<!\d)\d{3,4}\s*年", text)),
        "citations": citations,
    }


def _lesson_sources(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    title = str(lesson.get("lesson_title") or lesson.get("title") or "本课")
    return [
        {
            "topic": str(item.get("topic") or title),
            "snippet": str(item.get("text") or item.get("content") or ""),
            "source": title,
            "source_id": item.get("source_id") or item.get("id"),
        }
        for item in (lesson.get("items") or [])[:5]
        if str(item.get("text") or item.get("content") or "").strip()
    ]


def _run_generation_operation(
    operation: str,
    step: PlanStep,
    outputs: dict[str, dict[str, Any]],
    *,
    req: LearningAssistantRequestData,
    history: list[dict[str, Any]],
    source_context: dict[str, Any],
) -> dict[str, Any]:
    message = str(step.input.get("message") or req.get("message") or "").strip()
    if operation == "answer_from_sources":
        sources = _dependency_data(outputs, "sources") or []
        retrieval_status = str(_dependency_data(outputs, "retrieval_status") or "none")
        history_query = _dependency_data(outputs, "history_query") or {}
        aspect = str(history_query.get("aspect") or "fact") if isinstance(history_query, dict) else "fact"
        reason_codes = (history_query.get("reason_codes") or []) if isinstance(history_query, dict) else []
        collection_topic = history_query.get("retrieval_query") if "collection_query" in reason_codes else None
        focus_topic = str(
            collection_topic
            or (history_query.get("entity") if isinstance(history_query, dict) else None)
            or step.input.get("topic")
            or ""
        ).strip() or None
        answer_sources = [source for source in sources if source.get("answer_bearing") is True] or sources
        response, mode = _generate_history_answer(
            message,
            answer_sources,
            history,
            source_context,
            focus_topic,
            retrieval_status,
            aspect,
        )
        is_collection_query = "collection_query" in reason_codes
        if retrieval_status == "none":
            evidence_claims = []
        elif is_collection_query:
            evidence_claims = []
            for index, source in enumerate(answer_sources[:4], start=1):
                claim_text = _source_fact(source, None)
                if claim_text:
                    evidence_claims.append(
                        _evidence_claim(
                            operation,
                            f"{step.step_id}_answer_{index}",
                            claim_text,
                            [source],
                        )
                    )
        else:
            evidence_claims = [_evidence_claim(operation, f"{step.step_id}_answer", response, answer_sources[:4])]
        return {
            "ok": bool(response),
            "response": response,
            "data": {"sources": answer_sources[:4], "retrieval_status": retrieval_status, "history_query": history_query},
            "evidence_claims": evidence_claims,
            "generation_mode": mode,
            "result_summary": "已生成基于史料的解释" if retrieval_status == "sufficient" else "已按证据边界生成受限回答",
        }
    if operation == "answer_from_lesson":
        lesson = _dependency_data(outputs, "lesson") or {}
        title = str(lesson.get("lesson_title") or lesson.get("title") or "本课")
        items = lesson.get("items") or []
        highlights = "；".join(
            f"{item.get('topic') or '要点'}：{item.get('text') or item.get('content') or ''}"
            for item in items[:3]
            if item.get("text") or item.get("content")
        )
        response = f"围绕《{title}》，可以先抓住这些要点：{highlights}" if highlights else f"我已读取《{title}》，请告诉我你最想理解的部分。"
        lesson_sources = _lesson_sources(lesson)
        evidence_claims = [_evidence_claim(operation, f"{step.step_id}_answer", response, lesson_sources)]
        return {"ok": True, "response": response, "data": {"lesson": lesson}, "evidence_claims": evidence_claims, "generation_mode": "template", "result_summary": f"已生成《{title}》的教材回答"}
    if operation in {"quiz_from_sources", "quiz_from_lesson"}:
        sources = _dependency_data(outputs, "sources") or []
        if operation == "quiz_from_lesson":
            sources = _lesson_sources(_dependency_data(outputs, "lesson") or {})
        count = int(step.input.get("count") or 3)
        question_type = str(step.input.get("question_type") or "mixed")
        questions, mode = _generate_quiz_from_sources(message, sources, count, question_type)
        quiz = {"questions": questions}
        evidence_claims = [
            _evidence_claim(
                operation,
                f"{step.step_id}_{question.get('id') or index}",
                " ".join(str(question.get(key) or "") for key in ("question", "answer", "explanation")),
                sources,
                source_ids=[str(value) for value in (question.get("source_item_ids") or [])],
            )
            for index, question in enumerate(questions, start=1)
            if isinstance(question, dict)
        ]
        synthetic = {
            "tool_name": "generate_quiz",
            "ok": bool(questions),
            "data": {"quiz": quiz},
            "metadata": {"question_count": len(questions), "generated_from": "lesson" if operation == "quiz_from_lesson" else "sources", "generation_mode": mode},
        }
        return {
            "ok": len(questions) >= count,
            "response": f"已为你生成 {len(questions)} 道练习题。" if questions else "练习题暂时没有生成成功。",
            "data": {"quiz": quiz},
            "evidence_claims": evidence_claims,
            "generation_mode": mode,
            "synthetic_tool_result": synthetic,
            "result_summary": f"生成 {len(questions)} 道练习题",
        }
    if operation == "chat_answer":
        response, mode = _generate_chat_answer(message, history, source_context)
        return {"ok": bool(response), "response": response, "data": {}, "generation_mode": mode, "result_summary": "已生成学习回答"}
    raise ValueError(f"unsupported generation operation: {operation}")


def _suggestions_for_route(route: RoutingDecision) -> list[str]:
    intents = {task.intent for task in route.tasks}
    if IntentName.quiz_generation in intents:
        return ["再来 3 道选择题", "解释第 1 题", "换成简答题"]
    primary = route.tasks[0].intent
    if primary == IntentName.history_search:
        topic = route.tasks[0].topic or "这个知识点"
        return [f"用一句话总结{topic}", f"解释{topic}的原因和影响", f"围绕{topic}生成3道练习题"]
    if primary == IntentName.textbook_qa:
        return ["生成练习题", "总结本课", "解释重点"]
    if primary == IntentName.review_plan:
        return ["生成针对性练习题", "推荐相关历史人物", "查看薄弱知识点"]
    if primary == IntentName.character_recommendation:
        return ["开始和第一位人物对话", "换一个角度推荐", "只推荐教材覆盖高的人物"]
    if primary == IntentName.timeline_game:
        return ["开始游戏", "换成困难难度", "围绕同一专题再来一局"]
    return ["换个简单的说法", "结合教材解释", "围绕这个知识点出一道题"]


def _final_from_execution(
    route: RoutingDecision,
    execution: dict[str, Any],
    *,
    message: str,
    history: list[dict[str, Any]],
    source_context: dict[str, Any],
) -> tuple[str, list[str], str, list[dict[str, Any]]]:
    primary = route.tasks[0].intent.value
    tool_results = list(execution.get("tool_results") or [])
    generations = list(execution.get("generation_results") or [])
    for item in generations:
        synthetic = item.get("synthetic_tool_result")
        if isinstance(synthetic, dict):
            tool_results.append(synthetic)

    responses = [str(item.get("response") or "").strip() for item in generations if str(item.get("response") or "").strip()]
    modes = [str(item.get("generation_mode") or "") for item in generations]
    completion_status = execution.get("completion_status")
    if responses:
        response = "\n\n".join(dict.fromkeys(responses))
        if completion_status == "partial":
            response += "\n\n部分后续任务没有完成，你仍可以保留上面的已验证结果。"
        generation_mode = "llm" if "llm" in modes else "fallback" if "fallback" in modes else "template"
        return response, _suggestions_for_route(route), generation_mode, tool_results

    response, suggestions, generation_mode = _final_for_intent(primary, message, tool_results, history=history, source_context=source_context)
    if completion_status == "failed" and not response:
        response = "这次任务没有产生可安全交付的结果。你可以补充更具体的知识点后再试。"
    return response, suggestions, generation_mode, tool_results


def _stream_learning_assistant_events_legacy(req: LearningAssistantRequestData) -> Iterator[tuple[str, dict[str, Any]]]:
    # Ensure trace_id is set for this call; generate a fresh one if the caller (e.g. eval) didn't provide one.
    request_trace_id = req.get("trace_id") or uuid4().hex
    req["trace_id"] = request_trace_id
    set_trace_id(request_trace_id)
    message = (req.get("message") or "").strip()
    receive_started = perf_counter()
    check_user_input(message)
    yield _runtime_step("receive_query", "Receive User Query", "request", "success", sequence=1, started_at=receive_started, metadata={"message_chars": len(message)})
    history = req.get("conversation_history") or []
    source_context = req.get("source_context") or {}
    yield _runtime_step("load_context", "Load Conversation Context", "context", "success", sequence=2, metadata={"history_message_count": len(history), "source_feature": req.get("source_feature"), "source_session_id": req.get("source_session_id"), "knowledge_point": source_context.get("knowledge_point")})
    _record_assistant_event(req, event_type="followup_asked" if history else "question_asked", intent="pending", topic=source_context.get("knowledge_point"), ok=True, metadata={"source_feature": req.get("source_feature")})
    if req.get("source_feature") == "auto_tutor" and req.get("student_id"):
        try_record_learning_event(LearningEvent(
            student_id=req["student_id"],
            session_id=req.get("source_session_id"),
            feature="auto_tutor",
            event_type="autotutor_question_asked",
            grade=req.get("grade"),
            topic=source_context.get("knowledge_point"),
            success=True,
            metadata={"assistant_session_id": req.get("session_id")},
        ))

    intent_started = perf_counter()
    baseline_route = deterministic_route(dict(req))
    high_risk = any(task.intent == IntentName.memory_delete_demo for task in baseline_route.tasks)
    rollout = build_rollout_decision(
        dict(req),
        high_risk=high_risk,
        composition_candidate=len(baseline_route.tasks) > 1,
    )
    rollout_payload = rollout.model_dump(mode="json")
    emit_trace_event(
        agent_name="learning_assistant",
        step_name="Rollout Decision",
        event_type="rollout_decision",
        status="success",
        metadata=rollout_payload,
    )
    route, shadow_route = route_learning_request(
        dict(req),
        llm=llm_fast,
        semantic_enabled=rollout.route_mode != "control",
        shadow_mode=rollout.route_mode == "shadow",
        rule_decision=baseline_route,
    )
    intent_payload = legacy_intent_payload(route)
    intent = intent_payload["intent"]
    topic = route.tasks[0].topic
    route_payload = route.model_dump(mode="json")
    route_payload["contract_version"] = 3
    route_payload["rollout"] = rollout_payload
    agreement: bool | None = None
    if shadow_route is not None:
        route_payload["shadow"] = shadow_route.model_dump(mode="json")
        agreement = [task.intent for task in route.tasks] == [task.intent for task in shadow_route.tasks]
        route_payload["agreement"] = agreement
        emit_trace_event(
            agent_name="learning_assistant",
            step_name="Routing Comparison",
            event_type="routing_comparison",
            status="success",
            metadata={
                "config_version": rollout.config_version,
                "active_mode": route.mode,
                "active_intents": [task.intent.value for task in route.tasks],
                "shadow_mode": shadow_route.mode,
                "shadow_intents": [task.intent.value for task in shadow_route.tasks],
                "agreement": agreement,
                "confidence_rule": route.confidence,
                "confidence_semantic": shadow_route.confidence,
                "label_status": "unlabeled",
            },
        )
    _record_assistant_event(req, event_type="intent_detected", intent=intent, topic=topic, ok=True, metadata={"reason": intent_payload.get("reason"), "routing_mode": route.mode, "task_count": len(route.tasks), "needs_clarification": route.needs_clarification, "rollout": rollout_payload, "shadow_agreement": agreement})
    yield _runtime_step("intent_detection", "Semantic Routing", "routing", "success", sequence=3, started_at=intent_started, metadata={"mode": route.mode, "confidence": route.confidence, "reason_code": route.reason_code, "task_count": len(route.tasks), "needs_clarification": route.needs_clarification, "route_mode": rollout.route_mode, "config_version": rollout.config_version})
    yield "route", route_payload
    yield "intent", intent_payload

    if route.needs_clarification:
        response = route.clarification_question or "请再补充一点你想学习的范围。"
        clarification = {"question": response, "missing_slots": route.missing_slots, "reason_code": route.reason_code}
        _record_assistant_event(req, event_type="clarification_requested", intent=intent, topic=topic, ok=True, metadata={"missing_slots": route.missing_slots, "reason_code": route.reason_code})
        yield "clarification", clarification
        yield _runtime_step("clarification", "Clarification", "clarification", "success", sequence=4, metadata=clarification)
        trace_id = current_trace_id()
        if response:
            yield "delta", {"text": response}
        yield "final", {
            "session_id": req.get("session_id"), "response": response, "intent": intent, "tool_results": [], "profile_context": None,
            "generation_mode": "template", "completion_status": "needs_clarification", "routing": {"schema_version": 2, "mode": route.mode, "task_count": len(route.tasks), "reason_code": route.reason_code, "missing_slots": route.missing_slots, "completion_status": "needs_clarification", "pending_task": route.tasks[0].model_dump(mode="json")},
            "plan_summary": {"completed_steps": 0, "total_steps": 0, "partial_reason": route.reason_code},
            "rollout_summary": rollout_payload,
            "verification_summary": {"schema_version": 1, "required": False, "status": "not_required", "completion_allowed": False, "reason_codes": ["needs_clarification"]},
            "context_usage": {"history_messages": len(history), "source_feature": req.get("source_feature"), "source_session_id": req.get("source_session_id")}, "trace_id": trace_id,
        }
        yield "suggestions", {"suggestions": ["添加教材上下文", "直接告诉我课名", "换一个问题"], "trace_id": trace_id}
        return

    plan_started = perf_counter()
    composition_enabled = rollout.planner_mode == "composition_active"
    plan = build_task_plan(route, dict(req), enable_composition=composition_enabled)
    plan_payload = public_plan(plan)
    yield "runtime_plan", {"legacy_plan": plan.model_dump(mode="json")}
    yield _runtime_step("plan_build", "Plan Build", "plan", "success", sequence=4, started_at=plan_started, metadata={"step_count": len(plan.steps), "tool_step_count": sum(1 for step in plan.steps if step.kind == "tool"), "generation_step_count": sum(1 for step in plan.steps if step.kind == "generation"), "composition_enabled": composition_enabled})
    if composition_enabled:
        yield "plan", plan_payload

    first_tool_step = next((step for step in plan.steps if step.kind == "tool"), None)
    if first_tool_step is not None:
        input_summary = {key: value for key, value in first_tool_step.input.items() if key not in {"content", "text"}}
        yield _runtime_step("tool_selection", "Tool Selection", "tool_selection", "success", sequence=4, metadata={"tool_name": first_tool_step.operation, "input_summary": input_summary, "plan_step_id": first_tool_step.step_id})

    execution: dict[str, Any] = {}
    runtime = stream_task_plan(
        plan,
        run_tool=lambda name, payload, step: run_tool(name, payload, context=_tool_context(req, name, step.step_id)),
        summarize_tool=_tool_summary,
        run_generation=lambda operation, step, outputs: _run_generation_operation(operation, step, outputs, req=req, history=history, source_context=source_context),
    )
    for event, data in runtime:
        if event == "execution_complete":
            execution = data
            continue
        if event == "plan_step" and not composition_enabled:
            continue
        yield event, data

    for tool_result in execution.get("tool_results") or []:
        tool_name = str(tool_result.get("tool_name") or "")
        data = tool_result.get("data") or {}
        tool_metadata = tool_result.get("metadata") or {}
        metadata: dict[str, Any] = {}
        if "recommendations" in data:
            metadata["characters"] = [item.get("name") for item in data.get("recommendations") or [] if item.get("name")]
        error = tool_result.get("error") or {}
        if error:
            metadata["error_code"] = error.get("code")
        if tool_name == "search_history_knowledge":
            metadata.update({
                key: tool_metadata.get(key)
                for key in (
                    "retrieval_status", "source_count", "answer_bearing_source_count", "entity", "aspect",
                    "fusion", "rerank_status", "query_confidence",
                )
                if tool_metadata.get(key) is not None
            })
        _record_assistant_event(req, event_type="tool_result", intent=intent, topic=topic, tool_name=tool_name, ok=tool_result.get("ok"), metadata=metadata)

    answer_started = perf_counter()
    response, suggestions, generation_mode, tool_results = _final_from_execution(route, execution, message=message, history=history, source_context=source_context)
    routed_intents = [task.intent.value for task in route.tasks]
    yield "verification_start", {"trace_id": current_trace_id(), "required": any(name in {"history_search", "textbook_qa", "quiz_generation"} for name in routed_intents)}
    verification = verify_answer_evidence(intents=routed_intents, execution=execution)
    verification_payload = verification.model_dump(mode="json")
    completion_status = str(execution.get("completion_status") or "failed")
    if verification.required and not verification.completion_allowed:
        if completion_status == "completed":
            completion_status = "partial"
        execution["completion_status"] = completion_status
        execution["partial_reason"] = verification.reason_codes[0] if verification.reason_codes else "evidence_verification_failed"
        retrieval_statuses = [
            str((item.get("data") or {}).get("retrieval_status"))
            for item in execution.get("tool_results") or []
            if isinstance(item, dict) and (item.get("data") or {}).get("retrieval_status")
        ]
        if response and completion_status == "partial" and not any(status in {"partial", "none"} for status in retrieval_statuses):
            response += "\n\n这部分回答缺少足够的可核验来源，因此暂按部分完成处理。"
    verification_passed = verification.status in {"verified", "not_required"} and bool(response) and completion_status != "failed"
    yield "verification_result", {"trace_id": current_trace_id(), **verification_payload}
    yield _runtime_step(
        "evidence_verify",
        "Evidence Verify",
        "verification",
        "success" if verification_passed else "failed",
        sequence=6,
        metadata={
            "required": verification.required,
            "verification_status": verification.status,
            "source_count": verification.source_count,
            "citation_count": verification.citation_count,
            "unsupported_claim_count": verification.unsupported_claim_count,
            "reason_codes": verification.reason_codes,
            "completion_status": completion_status,
        },
    )
    answer_metadata = {
        "intent": intent,
        "used_tool_count": int(execution.get("used_tool_count") or 0),
        "completion_status": completion_status,
        "completed_steps": execution.get("completed_steps"),
        "total_steps": execution.get("total_steps"),
        **_llm_runtime_metadata(generation_mode=generation_mode, response_chars=len(response)),
    }
    yield _runtime_step("answer_synthesis", "Answer Synthesis", "llm" if generation_mode == "llm" else "generation", "success", sequence=7, started_at=answer_started, metadata=answer_metadata)

    memory_started = perf_counter()
    keep_current_topic = route.tasks[0].intent in {IntentName.history_search, IntentName.textbook_qa}
    suggestions, profile_context = _personalize_suggestions(
        req.get("student_id"),
        suggestions,
        include_review_actions=not keep_current_topic,
    )
    _record_assistant_event(req, event_type="answer_completed", intent=intent, topic=topic, ok=completion_status in {"completed", "partial", "waiting_confirmation"}, metadata={"tool_count": int(execution.get("used_tool_count") or 0), "generation_mode": generation_mode, "fallback_used": generation_mode == "fallback", "history_messages": len(history), "source_feature": req.get("source_feature"), "routing_mode": route.mode, "task_count": len(route.tasks), "completion_status": completion_status, "completed_steps": execution.get("completed_steps"), "total_steps": execution.get("total_steps"), "partial_reason": execution.get("partial_reason"), "clarification_resolved": route.reason_code == "pending_clarification_resolved", "rollout": rollout_payload, "verification_status": verification.status, "verification_source_count": verification.source_count, "unsupported_claim_count": verification.unsupported_claim_count})
    yield _runtime_step("memory_update", "Persist Interaction", "memory", "success", sequence=8, started_at=memory_started, metadata={"student_id": req.get("student_id"), "session_id": req.get("session_id"), "profile_context_loaded": bool(profile_context), "used_memory_count": len((profile_context or {}).get("used_memory") or []), "wrote_event": bool(req.get("student_id"))})
    trace_id = current_trace_id()
    if response:
        yield "delta", {"text": response}
    yield "final", {
        "session_id": req.get("session_id"), "response": response, "intent": intent, "tool_results": tool_results, "profile_context": profile_context,
        "generation_mode": generation_mode, "completion_status": completion_status,
        "routing": {"schema_version": 2, "mode": route.mode, "task_count": len(route.tasks), "reason_code": route.reason_code},
        "plan_summary": {"completed_steps": execution.get("completed_steps"), "total_steps": execution.get("total_steps"), "partial_reason": execution.get("partial_reason"), "failed_step": execution.get("failed_step")},
        "rollout_summary": rollout_payload,
        "verification_summary": verification_payload,
        "context_usage": {"history_messages": len(history), "source_feature": req.get("source_feature"), "source_session_id": req.get("source_session_id")}, "trace_id": trace_id,
    }
    yield "suggestions", {"suggestions": suggestions, "trace_id": trace_id}


def stream_learning_assistant_events(req: LearningAssistantRequestData) -> Iterator[tuple[str, dict[str, Any]]]:
    """Single execution source with optional Runtime v2 milestone persistence."""
    from agent_runtime.context import RuntimeV2Settings

    settings = RuntimeV2Settings.from_env()
    subject = str(req.get("actor_id") or req.get("student_id") or req.get("session_id") or req.get("trace_id") or uuid4().hex)
    active, bucket = settings.rollout_decision("learning_assistant", subject)
    if not active or not settings.observable_ready:
        for event, data in _stream_learning_assistant_events_legacy(req):
            if event != "runtime_plan":
                yield event, data
        return

    from agents.learning_assistant_runtime import map_task_plan_to_agent_plan
    from agent_runtime.artifact_store import create_artifact, list_run_artifacts
    from agent_runtime.event_store import get_run
    from agent_runtime.lifecycle import RuntimeRunController
    from agent_runtime.completion import CompletionEvaluator
    from agent_runtime.models import AgentBudget, AgentContext, default_data_scope

    requested_run_id = f"run_{uuid4().hex}"
    run_id = requested_run_id
    trace_id = str(req.get("trace_id") or uuid4().hex)
    actor_role = str(req.get("actor_role") or "anonymous")
    if actor_role not in {"anonymous", "student", "teacher", "admin"}:
        actor_role = "anonymous"
    context = AgentContext(
        run_id=run_id,
        agent_type="learning_assistant",
        actor_id=req.get("actor_id"),
        actor_role=actor_role,
        student_id=req.get("student_id"),
        session_id=req.get("session_id"),
        source_feature=req.get("source_feature"),
        source_session_id=req.get("source_session_id"),
        trace_id=trace_id,
        data_scope=default_data_scope(),
        durability_mode="observable",
        config_version=settings.config_version,
        rollout_bucket=bucket,
    )
    controller, run = RuntimeRunController.create(
        context,
        objective="学习助手受控问答",
        budget=AgentBudget(max_steps=3, max_tool_calls=3, max_llm_calls=3),
        policy_caller="learning_assistant",
        idempotency_key=req.get("idempotency_key"),
        runtime_mode="shadow" if settings.shadow_mode else "active",
    )
    run_id = str(run["run_id"])
    trace_id = str(run["trace_id"])
    yield "run_started", {
        "schema_version": 2,
        "run_id": run_id,
        "run_revision": run["revision"],
        "event_cursor": run["last_event_sequence"],
        "trace_id": trace_id,
    }
    if run_id != requested_run_id or run["status"] != "received":
        if run["status"] in {"completed", "partial", "failed", "cancelled"}:
            artifacts = list_run_artifacts(run_id, actor_id=req.get("actor_id"), actor_role=actor_role)
            final_artifact = next((item for item in reversed(artifacts) if item.get("artifact_type") == "final_output"), None)
            if final_artifact:
                final_data = dict((final_artifact.get("content") or {}).get("final") or {})
                final_data.update(
                    run_id=run_id,
                    run_revision=run["revision"],
                    event_cursor=run["last_event_sequence"],
                    idempotent_replay=True,
                )
                yield "final", final_data
            else:
                yield "final", {
                    "run_id": run_id,
                    "run_revision": run["revision"],
                    "event_cursor": run["last_event_sequence"],
                    "completion_status": run["status"],
                    "output_expired": True,
                    "idempotent_replay": True,
                }
        else:
            yield "runtime_status", {
                "run_id": run_id,
                "run_revision": run["revision"],
                "event_cursor": run["last_event_sequence"],
                "status": run["status"],
                "idempotent_replay": True,
            }
        return
    runtime_legacy_plan = None
    runtime_confirmation: dict[str, str] | None = None
    try:
        for event, data in _stream_learning_assistant_events_legacy(req):
            if event == "route":
                persisted = controller.route({"mode": data.get("mode"), "reason_code": data.get("reason_code"), "task_count": len(data.get("tasks") or [])})
                data = {**data, "run_id": run_id, "run_revision": get_run(run_id)["revision"], "event_cursor": persisted.sequence}
            elif event == "runtime_plan":
                from agents.learning_assistant_planner import TaskPlan

                legacy_plan = TaskPlan.model_validate(data["legacy_plan"])
                runtime_legacy_plan = legacy_plan
                plan = map_task_plan_to_agent_plan(legacy_plan, run_id=run_id)
                req["_runtime_run_id"] = run_id
                req["_runtime_step_contracts"] = {
                    step.step_id: {"idempotency_key": step.idempotency_key, "operation": step.operation}
                    for step in plan.steps
                }
                controller.admit_plan(plan)
                controller.start_step(plan.steps[0].step_id, plan.steps[0].operation)
                req["_runtime_run_revision"] = get_run(run_id)["revision"]
                continue
            elif event == "clarification":
                persisted = controller.wait_for_input({"missing_slots": data.get("missing_slots") or [], "reason_code": data.get("reason_code")})
                data = {**data, "run_id": run_id, "run_revision": get_run(run_id)["revision"], "event_cursor": persisted.sequence}
            elif event in {"tool_start", "tool_result", "repair_attempt", "verification_result"}:
                current = get_run(run_id)
                if current["status"] == "waiting_confirmation" and event == "verification_result":
                    data = {**data, "run_id": run_id, "run_revision": current["revision"], "event_cursor": current["last_event_sequence"]}
                    yield event, data
                    continue
                event_type = {"tool_start": "tool_started", "repair_attempt": "repair_attempted"}.get(event, event)
                waiting_for_confirmation = (
                    event == "tool_result"
                    and isinstance(data.get("error"), dict)
                    and data["error"].get("code") == "confirmation_required"
                )
                if waiting_for_confirmation:
                    step_id = str(data.get("step_id") or "")
                    legacy_step = next(
                        (step for step in (runtime_legacy_plan.steps if runtime_legacy_plan else []) if step.step_id == step_id),
                        None,
                    )
                    if legacy_step is None or str(legacy_step.operation) != str(data.get("tool_name") or ""):
                        raise ValueError("confirmation step does not match persisted plan")
                    waiting_revision = int(current["revision"]) + 2
                    token = issue_runtime_confirmation_token(
                        str(legacy_step.operation),
                        dict(legacy_step.input),
                        ToolExecutionContext(
                            actor_id=req.get("actor_id"),
                            role=actor_role,
                            student_id=req.get("student_id"),
                            request_source="learning_assistant_runtime_v2",
                            run_id=run_id,
                            step_id=step_id,
                            run_revision=waiting_revision,
                        ),
                    )
                    metadata = {**(data.get("metadata") or {}), "confirmation_token": token}
                    data = {**data, "metadata": metadata, "confirmation_token": token}
                    runtime_confirmation = {"tool_name": str(legacy_step.operation), "step_id": step_id, "token": token}
                persisted = controller.event(event_type, public_payload=data)
                if event == "tool_start":
                    req["_runtime_run_revision"] = get_run(run_id)["revision"]
                if waiting_for_confirmation:
                    waiting = controller.wait_for_confirmation(
                        {"step_id": runtime_confirmation["step_id"], "tool_name": runtime_confirmation["tool_name"]},
                        step_id=runtime_confirmation["step_id"],
                    )
                    data = {**data, "run_id": run_id, "run_revision": get_run(run_id)["revision"], "event_cursor": waiting.sequence}
                else:
                    data = {**data, "run_id": run_id, "run_revision": get_run(run_id)["revision"], "event_cursor": persisted.sequence}
            elif event == "final":
                completion_status = str(data.get("completion_status") or "failed")
                if completion_status == "needs_clarification":
                    current = get_run(run_id)
                    data = {**data, "run_id": run_id, "run_revision": current["revision"], "event_cursor": current["last_event_sequence"]}
                    yield event, data
                    continue
                current = get_run(run_id)
                completed_steps = int((data.get("plan_summary") or {}).get("completed_steps") or 0)
                total_steps = int((data.get("plan_summary") or {}).get("total_steps") or 0)
                verification = data.get("verification_summary") or {}
                verification_status = str(verification.get("status") or "not_required")
                if verification_status not in {"verified", "partial", "failed", "not_required"}:
                    verification_status = "failed"
                if completion_status in {"completed", "partial"}:
                    controller.event("verification_result", public_payload={"status": verification_status}, next_status="verifying")
                    current = get_run(run_id)
                decision_status = completion_status if completion_status in {"completed", "partial", "waiting_confirmation", "failed", "cancelled"} else "failed"
                if decision_status == "waiting_confirmation" and runtime_confirmation:
                    patched_results = []
                    for item in data.get("tool_results") or []:
                        if str(item.get("tool_name") or "") == runtime_confirmation["tool_name"]:
                            metadata = {**(item.get("metadata") or {}), "confirmation_token": runtime_confirmation["token"]}
                            item = {**item, "metadata": metadata}
                        patched_results.append(item)
                    data = {**data, "tool_results": patched_results}
                deliverable_refs: list[str] = []
                if decision_status in {"completed", "partial", "failed", "cancelled"}:
                    artifact = create_artifact(
                        run_id,
                        owner_actor_id=req.get("actor_id"),
                        student_id=req.get("student_id"),
                        artifact_type="final_output",
                        sensitivity="student_content" if req.get("student_id") else "normal",
                        content={"final": data},
                    )
                    deliverable_refs.append(artifact["artifact_id"])
                decision = CompletionEvaluator().from_outcome(
                    status=decision_status,
                    completion_allowed=decision_status == "completed" and bool(verification.get("completion_allowed", True)),
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                    verification_status=verification_status,
                    reason_codes=list(verification.get("reason_codes") or ([str((data.get("plan_summary") or {}).get("partial_reason"))] if decision_status != "completed" else ["completion_criteria_satisfied"])),
                    deliverable_refs=deliverable_refs,
                )
                if decision_status == "waiting_confirmation" and current["status"] == "waiting_confirmation":
                    data = {**data, "run_id": run_id, "run_revision": current["revision"], "event_cursor": current["last_event_sequence"]}
                else:
                    terminal_event = "run_completed" if decision_status in {"completed", "partial"} else ("waiting_confirmation" if decision_status == "waiting_confirmation" else "run_failed")
                    persisted = controller.event(
                        terminal_event,
                        public_payload={"completion": decision.model_dump()},
                        next_status=decision_status,
                        completion=decision if decision_status in {"completed", "partial", "failed", "cancelled"} else None,
                    )
                    current = get_run(run_id)
                    data = {**data, "run_id": run_id, "run_revision": current["revision"], "event_cursor": persisted.sequence}
            yield event, data
    except Exception as exc:
        current = get_run(run_id)
        if current["status"] not in {"completed", "partial", "failed", "cancelled", "waiting_input", "waiting_confirmation"}:
            state = current["state"]
            total_steps = len(((state.get("plan") or {}).get("steps") or []))
            decision = CompletionEvaluator().from_outcome(
                status="failed",
                completed_steps=0,
                total_steps=total_steps,
                verification_status="failed",
                reason_codes=["runtime_wrapper_exception"],
            )
            controller.event(
                "run_failed",
                public_payload={"error": {"code": "runtime_wrapper_exception", "message": str(exc)[:240]}},
                next_status="failed",
                completion=decision,
            )
        raise
