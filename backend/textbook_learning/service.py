from __future__ import annotations

from typing import Iterator

from llm_config import llm_fast, llm_quality
from rag.knowledge_base import MetadataFilter, MetadataHints, search
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


def source_to_dict(doc) -> dict:
    metadata = getattr(doc, "metadata", {}) or {}
    return {
        "topic": metadata.get("topic"),
        "source": metadata.get("source"),
        "grade": metadata.get("grade"),
        "unit": metadata.get("unit"),
        "lesson": metadata.get("lesson"),
        "type": metadata.get("type"),
        "page": metadata.get("page"),
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
) -> list[dict]:
    try:
        docs = search("history", query, k=4, metadata_filter=metadata_filter, mode="hybrid", metadata_hints=metadata_hints)
        return [source_to_dict(doc) for doc in docs]
    except Exception:
        return []


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

    yield "status", {"phase": "retrieving", "message": "正在检索相关教材知识"}
    sources = retrieve_sources(query, build_lesson_metadata_filter(lesson), build_lesson_metadata_hints(lesson, item_text))
    if not sources:
        sources = lesson_fallback_sources(lesson, req.item_id)
    yield "sources", {"sources": sources}
    yield "status", {"phase": "generating", "message": "正在生成学习辅助回答"}

    history = load_messages(req.session_id) if req.session_id else []
    messages = ask_messages(lesson, question, req.selected_text, item_text, build_sources_context(sources), history)
    chunks: list[str] = []
    try:
        for chunk in llm_quality.stream(messages):
            chunks.append(chunk)
            yield "delta", {"text": chunk}
    except Exception:
        chunks = []

    response = "".join(chunks).strip()
    if not response:
        response = fallback_ask_response(lesson, question, item_text, sources)
        yield "delta", {"text": response}
    final = {"response": response, "sources": sources, "lesson_id": req.lesson_id, "book_id": req.book_id}
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


def generate_quiz(req: TextbookQuizRequest) -> TextbookQuizResponse:
    lesson = get_lesson(req.book_id, req.lesson_id)
    focus_text = find_item_text(lesson, req.focus_item_id)
    count = max(1, min(req.count, 10))
    response = llm_fast.invoke(quiz_messages(lesson, list(req.question_types), count, focus_text)).content
    try:
        data = parse_json_object(response)
    except StructuredOutputError as exc:
        try:
            data = parse_json_object(repair_json_with_llm(llm_fast, response, expect="object", schema_name="TextbookQuizResponse", error=str(exc)))
        except StructuredOutputError:
            return TextbookQuizResponse(raw_text=response)
    if not isinstance(data.get("questions"), list):
        return TextbookQuizResponse(raw_text=response)

    questions = []
    for index, item in enumerate(data["questions"], start=1):
        if not isinstance(item, dict):
            continue
        try:
            questions.append(
                TextbookQuizQuestion(
                    id=str(item.get("id") or f"q{index}"),
                    type=str(item.get("type") or "short_answer"),
                    question=str(item.get("question") or ""),
                    options=item.get("options") if isinstance(item.get("options"), list) else None,
                    answer=str(item.get("answer") or ""),
                    explanation=str(item.get("explanation") or ""),
                    source_item_ids=item.get("source_item_ids") if isinstance(item.get("source_item_ids"), list) else [],
                )
            )
        except Exception:
            continue
    return TextbookQuizResponse(questions=questions, raw_text=None if questions else response)


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
