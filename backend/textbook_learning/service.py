from __future__ import annotations

import hashlib
import logging
import re
from time import perf_counter
from typing import Iterator

from llm_config import llm_fast, llm_quality
from rag.knowledge_base import MetadataFilter, MetadataHints, build_rag_inspector, search_with_scores
from session_store import load_messages, save_messages
from structured_output import StructuredOutputError, parse_json_object, repair_json_with_llm
from textbook_learning.loader import get_lesson, get_toc, list_textbooks
from textbook_learning.prompts import ACTION_QUESTIONS, ask_messages, quiz_messages, summary_messages
from textbook_learning.schema import (
    TextbookAskRequest,
    TextbookQuizQuestion,
    TextbookQuizRequest,
    TextbookQuizResponse,
    TextbookSummaryRequest,
    TextbookQuizSubmitRequest,
)
from trace_store import emit_trace_event
from utils.cost_estimator import estimate_cost_from_chars


logger = logging.getLogger(__name__)


def resolve_question(req: TextbookAskRequest) -> str:
    action_question = ACTION_QUESTIONS.get(req.action or "")
    if action_question and req.question.strip() in {"解释一下", "为什么重要", "容易怎么考", ""}:
        return action_question
    return req.question.strip() or action_question or "请解释这个知识点。"


def find_item_text(lesson, item_id: str | None) -> str | None:
    if not item_id:
        return None
    for item in lesson.items:
        if item.id == item_id:
            return f"{item.topic}：{item.text}"
    return None


def source_to_dict(doc, scored: dict | None = None) -> dict:
    metadata = getattr(doc, "metadata", {}) or {}
    final_score = float((scored or {}).get("final_score", (scored or {}).get("score", 0)) or 0)
    return {
        "rank": (scored or {}).get("rank"),
        "topic": metadata.get("topic"),
        "source": metadata.get("source"),
        "grade": metadata.get("grade"),
        "unit": metadata.get("unit"),
        "lesson": metadata.get("lesson"),
        "type": metadata.get("type"),
        "page": metadata.get("page"),
        "score": round(final_score, 3),
        "final_score": round(final_score, 3),
        "retrieval_score": _rounded((scored or {}).get("retrieval_score")),
        "keyword_score": _rounded((scored or {}).get("keyword_score")),
        "vector_rank": (scored or {}).get("vector_rank"),
        "vector_rank_score": _rounded((scored or {}).get("vector_rank_score")),
        "rerank_score": _rounded((scored or {}).get("rerank_score")),
        "source_mode": (scored or {}).get("source_mode"),
        "content": getattr(doc, "page_content", ""),
    }


def item_to_source(lesson, item) -> dict:
    return {
        "topic": item.topic,
        "source": f"{lesson.book} · {lesson.lesson_title}",
        "grade": lesson.grade,
        "unit": lesson.unit_title,
        "lesson": lesson.lesson_title,
        "type": item.type,
        "page": item.page,
        "content": item.text,
    }


def _rounded(value) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def lesson_fallback_sources(lesson, item_id: str | None = None) -> list[dict]:
    if item_id:
        for item in lesson.items:
            if item.id == item_id:
                return [item_to_source(lesson, item)]
    return [item_to_source(lesson, item) for item in lesson.items[:4]]


def build_lesson_metadata_filter(lesson) -> MetadataFilter:
    grade = lesson.grade.strip()
    grade_values = [grade]
    if grade.endswith("册"):
        grade_values.append(grade[:-1])
    return {"grade": grade_values}


def build_lesson_metadata_hints(lesson, item_text: str | None = None) -> MetadataHints:
    hints: MetadataHints = {
        "grade": lesson.grade,
        "unit": lesson.unit_title,
        "lesson": lesson.lesson_title,
        "topic": [item.topic for item in lesson.items[:12]],
        "tags": [tag for item in lesson.items[:12] for tag in item.tags],
        "entities": [entity for item in lesson.items[:12] for entity in item.entities],
        "keywords": [keyword for item in lesson.items[:12] for keyword in item.keywords],
        "event": [item.event for item in lesson.items[:12] if item.event],
        "period": [item.period for item in lesson.items[:12] if item.period],
    }
    if item_text:
        topic = item_text.split("：", 1)[0].strip()
        if topic:
            hints["topic"] = [topic, *hints["topic"]]
    return hints


def retrieve_sources(
    query: str,
    metadata_filter: MetadataFilter | None = None,
    metadata_hints: MetadataHints | None = None,
) -> tuple[list[dict], dict]:
    try:
        scored_docs = search_with_scores("history", query, k=4, metadata_filter=metadata_filter, mode="hybrid", metadata_hints=metadata_hints, fetch_k=30)
        sources = [source_to_dict(item["document"], item) for item in scored_docs]
        inspector = build_rag_inspector(
            collection="history",
            original_query=query,
            scored_docs=scored_docs,
            mode="hybrid",
            metadata_filter=metadata_filter,
            metadata_hints=metadata_hints,
            retrieval_strategy="textbook_hybrid",
            used_source_ranks={int(source.get("rank") or index + 1) for index, source in enumerate(sources[:4])},
        )
        return sources, annotate_textbook_rag_inspector(inspector)
    except Exception as exc:
        return [], annotate_textbook_rag_inspector({
            "collection": "history",
            "original_query": query,
            "retrieval_strategy": "textbook_hybrid_failed",
            "source_count": 0,
            "total_chunks_retrieved": 0,
            "top_score": 0,
            "top_mode": "",
            "chunks": [],
            "error": str(exc)[:240],
        })


def fallback_rag_inspector(query: str, sources: list[dict]) -> dict:
    return {
        "collection": "history",
        "original_query": query,
        "retrieval_strategy": "lesson_fallback",
        "source_count": len(sources),
        "total_chunks_retrieved": len(sources),
        "top_score": 0,
        "top_mode": "lesson",
        "chunks": [
            {
                "rank": index + 1,
                "topic": source.get("topic"),
                "source": source.get("source"),
                "grade": source.get("grade"),
                "unit": source.get("unit"),
                "lesson": source.get("lesson"),
                "page": source.get("page"),
                "type": source.get("type"),
                "source_mode": "lesson",
                "final_score": 0,
                "retrieval_score": 0,
                "keyword_score": 0,
                "vector_rank": None,
                "vector_rank_score": 0,
                "rerank_score": None,
                "used_in_context": True,
                "content_preview": str(source.get("content") or "")[:240],
            }
            for index, source in enumerate(sources)
        ],
    }


def annotate_textbook_rag_inspector(inspector: dict, *, generation_degraded: bool = False) -> dict:
    strategy = str(inspector.get("retrieval_strategy") or "")
    source_count = int(inspector.get("source_count") or 0)
    diagnosis_code = "retrieval_ok"
    diagnosis_summary = "已命中教材知识片段，可直接核对来源。"
    failure_stage = "none"

    if strategy == "lesson_fallback":
        diagnosis_code = "lesson_fallback_used"
        diagnosis_summary = "知识库检索未命中，已回退到当前课文内容兜底。"
        failure_stage = "retrieval"
    elif strategy == "textbook_hybrid_failed":
        diagnosis_code = "retrieval_failed"
        diagnosis_summary = "知识库检索失败，已切换到课文兜底内容。"
        failure_stage = "retrieval"
    elif source_count == 0:
        diagnosis_code = "retrieval_empty"
        diagnosis_summary = "当前没有检索到教材片段，建议缩小问题范围后重试。"
        failure_stage = "retrieval"
    elif generation_degraded:
        diagnosis_code = "generation_fallback_used"
        diagnosis_summary = "生成阶段已降级为模板化讲解，建议检查模型服务状态。"
        failure_stage = "generation"

    return {
        **inspector,
        "generation_degraded": generation_degraded,
        "failure_stage": failure_stage,
        "diagnosis_code": diagnosis_code,
        "diagnosis_summary": diagnosis_summary,
    }


def build_sources_context(sources: list[dict]) -> str:
    lines = []
    for source in sources:
        topic = source.get("topic") or "未标注主题"
        content = source.get("content") or ""
        lines.append(f"- {topic}：{content}")
    return "\n".join(lines)


def fallback_ask_response(lesson, question: str, item_text: str | None, sources: list[dict]) -> str:
    focus = item_text
    if not focus and sources:
        first = sources[0]
        focus = f"{first.get('topic') or lesson.lesson_title}：{first.get('content') or ''}"
    if not focus and lesson.items:
        first_item = lesson.items[0]
        focus = f"{first_item.topic}：{first_item.text}"

    source_lines = []
    for index, source in enumerate(sources[:3], start=1):
        source_lines.append(
            f"{index}. {source.get('topic') or lesson.lesson_title}：{source.get('content') or ''}"
        )
    source_text = "\n".join(source_lines) or "1. 当前课程学习文档暂无可用知识点。"

    if "考" in question:
        answer = (
            "这个知识点常见考法是让你说明时间、人物、原因、经过或影响，并判断它在历史发展中的作用。"
            "答题时先写清核心史实，再补一句影响或启示。"
        )
    elif "重要" in question or "为什么" in question:
        answer = (
            "它的重要性主要体现在帮助我们理解本课事件之间的因果关系，以及这一知识点对后续历史发展的影响。"
            "复习时要把它放回单元主题中记忆。"
        )
    else:
        answer = "可以把这个知识点拆成“是什么、为什么、有什么影响”三步理解，先掌握核心史实，再看它和本课其他内容的联系。"

    return (
        f"### {lesson.lesson_title}\n\n"
        f"**问题**：{question}\n\n"
        f"**核心解释**：{answer}\n\n"
        f"**当前知识点**：{focus or lesson.lesson_title}\n\n"
        f"**依据**：\n{source_text}"
    )


def stream_ask_events(req: TextbookAskRequest) -> Iterator[tuple[str, dict]]:
    lesson = get_lesson(req.book_id, req.lesson_id)
    question = resolve_question(req)
    item_text = find_item_text(lesson, req.item_id)
    query = " ".join(part for part in [question, req.selected_text, item_text, lesson.lesson_title] if part)

    retrieval_started = perf_counter()
    yield "status", {"phase": "retrieving", "message": "正在检索相关教材知识"}
    sources, rag_inspector = retrieve_sources(query, build_lesson_metadata_filter(lesson), build_lesson_metadata_hints(lesson, item_text))
    if not sources:
        sources = lesson_fallback_sources(lesson, req.item_id)
        rag_inspector = annotate_textbook_rag_inspector(fallback_rag_inspector(query, sources))
    emit_trace_event(
        agent_name="textbook_learning",
        step_name="rag_retrieval",
        event_type="retrieval",
        status="success",
        latency_ms=int((perf_counter() - retrieval_started) * 1000),
        metadata={
            "book_id": req.book_id,
            "lesson_id": req.lesson_id,
            "item_id": req.item_id,
            "query": query[:240],
            "source_count": len(sources),
            "retrieval_strategy": rag_inspector.get("retrieval_strategy"),
            "rag_inspector": rag_inspector,
        },
    )
    yield "sources", {"sources": sources, "rag_inspector": rag_inspector}
    yield "status", {"phase": "generating", "message": "正在生成学习辅助回答"}

    history = load_messages(req.session_id) if req.session_id else []
    messages = ask_messages(lesson, question, req.selected_text, item_text, build_sources_context(sources), history)
    chunks: list[str] = []
    generation_started = perf_counter()
    generation_error = None
    try:
        for chunk in llm_quality.stream(messages):
            chunks.append(chunk)
            yield "delta", {"text": chunk}
    except Exception as exc:
        generation_error = str(exc)
        chunks = []

    response = "".join(chunks).strip()
    if not response:
        response = fallback_ask_response(lesson, question, item_text, sources)
        rag_inspector = annotate_textbook_rag_inspector(rag_inspector, generation_degraded=True)
        yield "delta", {"text": response}
    emit_trace_event(
        agent_name="textbook_learning",
        step_name="response_generation",
        event_type="llm",
        status="success",
        latency_ms=int((perf_counter() - generation_started) * 1000),
        metadata={
            "book_id": req.book_id,
            "lesson_id": req.lesson_id,
            "item_id": req.item_id,
            "llm_name": getattr(llm_quality, "name", "llm_quality"),
            "configured_model": getattr(llm_quality, "model", None),
            "response_chars": len(response),
            "degraded": generation_error is not None or bool(rag_inspector.get("generation_degraded")),
            "error": generation_error,
            "rag_inspector": rag_inspector,
            **estimate_cost_from_chars(
                str(getattr(llm_quality, "model", "") or ""),
                input_chars=len(build_sources_context(sources)) + len(question),
                output_chars=len(response),
            ),
        },
    )
    final = {"response": response, "sources": sources, "rag_inspector": rag_inspector, "lesson_id": req.lesson_id, "book_id": req.book_id}
    yield "final", final
    yield "status", {"phase": "done", "message": "已完成"}

    if req.session_id and response:
        next_history = history + [{"role": "user", "content": question}, {"role": "assistant", "content": response}]
        save_messages(req.session_id, next_history[-16:])


def stream_summary_events(req: TextbookSummaryRequest) -> Iterator[tuple[str, dict]]:
    lesson = get_lesson(req.book_id, req.lesson_id)
    yield "status", {"phase": "generating", "message": "正在生成本课学习摘要"}
    chunks: list[str] = []
    for chunk in llm_fast.stream(summary_messages(lesson, req.mode)):
        chunks.append(chunk)
        yield "delta", {"text": chunk}
    response = "".join(chunks).strip()
    yield "final", {"response": response, "mode": req.mode, "lesson_id": req.lesson_id, "book_id": req.book_id}
    yield "status", {"phase": "done", "message": "已完成"}


def _safe_quiz_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "credential" in message or "api key" in message or "disabled" in message:
        return "model_unavailable"
    if "timeout" in message or "timed out" in message:
        return "model_timeout"
    return "model_output_invalid"


def _clean_quiz_text(value: object, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ，,；;。")
    if len(text) <= max_chars:
        return text
    shortened = text[:max_chars]
    boundary = max(shortened.rfind("，"), shortened.rfind("；"), shortened.rfind("。"))
    return shortened[:boundary].strip(" ，,；;。") if boundary >= max_chars // 2 else shortened.rstrip(" ，,；;。")


def _choice_claim(value: object) -> str:
    return _clean_quiz_text(value, 76)


def _normalize_choice_option(value: object) -> str:
    return re.sub(r"^[A-DＡ-Ｄ][.、．:：]\s*", "", _clean_quiz_text(value, 90), flags=re.IGNORECASE)


def _grounded_choice_options(lesson, target_item, index: int) -> tuple[list[str], str]:
    correct = _choice_claim(target_item.text)
    distractors: list[str] = []
    for item in lesson.items:
        if item.id == target_item.id or target_item.topic in item.text:
            continue
        claim = _choice_claim(item.text)
        if claim and claim != correct and claim not in distractors:
            distractors.append(claim)
        if len(distractors) >= 3:
            break

    generic = [
        "这一知识点与本课涉及的人物、政权和制度完全无关",
        "教材认为该事件没有产生任何政治、经济或社会影响",
        "这一事件发生在中国近代史时期，与本课时代背景无关",
    ]
    for claim in generic:
        if len(distractors) >= 3:
            break
        if claim != correct and claim not in distractors:
            distractors.append(claim)

    offset = hashlib.sha256(f"{target_item.id}|{index}".encode("utf-8")).digest()[0] % 4
    options = distractors[:3]
    options.insert(offset, correct)
    return options, "ABCD"[offset]


def _build_grounded_quiz(lesson, req: TextbookQuizRequest, count: int) -> list[TextbookQuizQuestion]:
    items = list(lesson.items)
    if not items:
        return []
    if req.focus_item_id:
        focused = next((item for item in items if item.id == req.focus_item_id), None)
        if focused:
            items = [focused, *(item for item in items if item.id != focused.id)]

    question_types = list(req.question_types) or ["single_choice"]
    questions: list[TextbookQuizQuestion] = []
    for index in range(count):
        item = items[index % len(items)]
        question_type = question_types[index % len(question_types)]
        source_note = f"教材同步条目「{item.topic}」指出：{_clean_quiz_text(item.text)}。"

        if question_type == "single_choice":
            options, answer = _grounded_choice_options(lesson, item, index)
            question = f"下列史实中，与「{item.topic}」直接对应的是？"
        elif question_type == "fill_blank":
            options = None
            answer = item.topic
            question = f"阅读材料并填写对应的历史主题：{_choice_claim(item.text)}。这一史实是____。"
        elif question_type == "explanation":
            options = None
            answer = _clean_quiz_text(item.text)
            question = f"结合教材，说明「{item.topic}」的主要内容及其历史作用。"
        else:
            options = None
            answer = _clean_quiz_text(item.text)
            question = f"根据教材，简述「{item.topic}」的核心史实。"

        questions.append(
            TextbookQuizQuestion(
                id=f"grounded-{item.id}-{index + 1}",
                type=question_type,
                question=question,
                options=options,
                answer=answer,
                explanation=source_note,
                source_item_ids=[item.id],
            )
        )
    return questions


def _validate_model_quiz(data: dict, lesson, req: TextbookQuizRequest, count: int) -> list[TextbookQuizQuestion]:
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or len(raw_questions) != count:
        raise ValueError("question count mismatch")

    allowed_item_ids = {item.id for item in lesson.items}
    allowed_types = set(req.question_types) or {"single_choice"}
    seen_ids: set[str] = set()
    questions: list[TextbookQuizQuestion] = []
    for index, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict):
            raise ValueError("question must be an object")
        question_id = _clean_quiz_text(item.get("id") or f"q{index}", 80)
        question_type = _clean_quiz_text(item.get("type") or "", 30)
        question = _clean_quiz_text(item.get("question"), 300)
        answer = _clean_quiz_text(item.get("answer"), 240)
        explanation = _clean_quiz_text(item.get("explanation"), 320)
        source_item_ids = [str(value) for value in item.get("source_item_ids") or []]
        if (
            not question_id
            or question_id in seen_ids
            or question_type not in allowed_types
            or not question
            or not answer
            or not explanation
            or not source_item_ids
            or not set(source_item_ids) <= allowed_item_ids
        ):
            raise ValueError("question is not grounded or is incomplete")

        options = None
        if question_type == "single_choice":
            raw_options = item.get("options")
            if not isinstance(raw_options, list) or len(raw_options) != 4 or answer[:1].upper() not in "ABCD":
                raise ValueError("single choice question is invalid")
            options = [_normalize_choice_option(value) for value in raw_options]
            if not all(options) or len(set(options)) != 4:
                raise ValueError("single choice options are invalid")

        questions.append(
            TextbookQuizQuestion(
                id=question_id,
                type=question_type,
                question=question,
                options=options,
                answer=answer,
                explanation=explanation,
                source_item_ids=source_item_ids,
            )
        )
        seen_ids.add(question_id)
    return questions


def generate_quiz(req: TextbookQuizRequest) -> TextbookQuizResponse:
    lesson = get_lesson(req.book_id, req.lesson_id)
    focus_text = find_item_text(lesson, req.focus_item_id)
    count = max(1, min(req.count, 10))
    try:
        response = llm_fast.invoke(quiz_messages(lesson, list(req.question_types), count, focus_text)).content
        try:
            data = parse_json_object(response)
        except StructuredOutputError as exc:
            repaired = repair_json_with_llm(
                llm_fast,
                response,
                expect="object",
                schema_name="TextbookQuizResponse",
                error=str(exc),
            )
            data = parse_json_object(repaired)
        questions = _validate_model_quiz(data, lesson, req, count)
        return TextbookQuizResponse(questions=questions, generation_source="llm")
    except Exception as exc:
        reason = _safe_quiz_reason(exc)
        logger.warning(
            "textbook_quiz_grounded_fallback book_id=%s lesson_id=%s count=%s reason=%s",
            req.book_id,
            req.lesson_id,
            count,
            reason,
        )
        questions = _build_grounded_quiz(lesson, req, count)
        return TextbookQuizResponse(
            questions=questions,
            generation_source="trusted_lesson",
            generation_reason=reason,
        )


def submit_quiz_answers(req: TextbookQuizSubmitRequest) -> dict:
    lesson = get_lesson(req.book_id, req.lesson_id)
    results = []
    wrong_tags: list[str] = []
    correct_tags: list[str] = []

    item_map = {item.id: item for item in lesson.items}

    for answer_item in req.answers:
        question_id = answer_item.get("question_id", "")
        user_answer = str(answer_item.get("user_answer", "")).strip()
        source_ids = answer_item.get("source_item_ids") or []
        correct_answer = ""
        is_correct = False

        # Prefer source_item_ids for exact lookup; fall back to substring scan
        matched_item = next((item_map[sid] for sid in source_ids if sid in item_map), None)
        if matched_item is None:
            matched_item = next(
                (item for item in lesson.items if item.id in question_id or item.topic in question_id),
                None,
            )
        if matched_item:
            correct_answer = matched_item.text
            is_correct = user_answer.lower() in correct_answer.lower() or len(user_answer) > 10

        results.append({
            "question_id": question_id,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
        })

        if not is_correct and user_answer and matched_item:
            wrong_tags.append(matched_item.topic)
        elif is_correct and matched_item:
            correct_tags.append(matched_item.topic)

    if req.student_id:
        from services.weakpoint_service import record_weakpoint, record_correct_evidence
        for tag in wrong_tags[:3]:
            record_weakpoint(req.student_id, tag, "textbook_guide")
        for tag in correct_tags:
            record_correct_evidence(req.student_id, tag)

    total = len(results)
    correct = sum(1 for r in results if r["is_correct"])
    return {
        "total": total,
        "correct": correct,
        "score": correct / total if total else 0,
        "results": results,
    }
