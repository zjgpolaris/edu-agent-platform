"""Smoke: persistent sessions, follow-up context, recovery and owner isolation."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-learning-assistant-multiturn.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTH_REQUIRED"] = "true"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from agents import learning_assistant as la
from agents.learning_assistant_planner import build_task_plan
from agents.learning_assistant_router import deterministic_route
from api.routers.learning import (
    LearningAssistantContextUpdateRequest,
    LearningAssistantFeedbackRequest,
    LearningAssistantRequest,
    LearningAssistantSessionUpdateRequest,
    LearningAssistantTextbookContext,
    learning_assistant_chat,
    learning_assistant_feedback,
    learning_assistant_get_session,
    learning_assistant_list_sessions,
    learning_assistant_update_context,
    learning_assistant_update_session,
)
from security.auth import Actor
from services.learning_assistant_session_service import append_message, create_session, get_latest_session, list_messages
from student_profile import list_learning_events
from tools.base import ToolResult
from textbook_learning.loader import get_toc, list_textbooks


def main() -> None:
    student_id = "multiturn-student"
    session = create_session(student_id)
    append_message(session["session_id"], "user", "鸦片战争为什么爆发？")
    assistant_message = append_message(
        session["session_id"],
        "assistant",
        "英国为打开中国市场发动战争。",
        intent="history_search",
        tool_results=[{
            "tool_name": "search_history_knowledge",
            "ok": True,
            "data": {"sources": [{
                "topic": "鸦片战争",
                "snippet": "战后中国社会性质发生变化。",
                "source": "《中国历史八年级上册》",
                "lesson": "第1课 鸦片战争",
                "page": 7,
                "score": 12.34567,
                "unsafe_internal": "must-not-persist",
            }]},
            "metadata": {"source_count": 1, "query": "must-not-persist"},
        }],
    )
    history = list_messages(session["session_id"])
    assert len(history) == 2
    persisted_tool = assistant_message["tool_results"][0]
    persisted_source = persisted_tool["data"]["sources"][0]
    assert persisted_source["topic"] == "鸦片战争", persisted_tool
    assert persisted_source["snippet"] == "战后中国社会性质发生变化。", persisted_tool
    assert persisted_source["page"] == "7" and persisted_source["score"] == 12.346, persisted_tool
    assert "unsafe_internal" not in persisted_source and "query" not in persisted_tool["metadata"], persisted_tool
    assert get_latest_session(student_id)["session_id"] == session["session_id"]
    restored_tool = get_latest_session(student_id)["messages"][-1]["tool_results"][0]
    assert restored_tool["data"]["sources"][0]["topic"] == "鸦片战争", restored_tool

    captured: dict = {}
    original_tool = la.run_tool
    original_invoke = la.llm_fast.invoke
    la.run_tool = lambda name, payload, context=None: (captured.update(payload=payload) or ToolResult(
        tool_name=name,
        ok=True,
        data={"sources": [{"topic": "鸦片战争", "snippet": "战后中国社会性质发生变化。"}]},
    ))

    class _Response:
        content = "这里的“它”指鸦片战争；战后中国开始沦为半殖民地半封建社会。"

    la.llm_fast.invoke = lambda messages: _Response()
    try:
        events = list(la.stream_learning_assistant_events({
            "message": "它有什么影响？",
            "student_id": student_id,
            "session_id": session["session_id"],
            "conversation_history": history,
            "actor_role": "student",
        }))
    finally:
        la.run_tool = original_tool
        la.llm_fast.invoke = original_invoke

    intent = next(data for event, data in events if event == "intent")
    final = next(data for event, data in events if event == "final")
    assert intent["intent"] == "history_search", intent
    assert "鸦片战争" in captured["payload"]["query"], captured
    assert "半殖民地" in final["response"], final
    assert final["context_usage"]["history_messages"] == 2

    su_shi_history = [{"role": "user", "content": "苏轼做了什么"}]
    su_shi_route = deterministic_route({"message": "结合教材解释", "conversation_history": su_shi_history})
    assert su_shi_route.tasks[0].intent.value == "history_search", su_shi_route
    assert su_shi_route.tasks[0].topic == "苏轼", su_shi_route
    assert su_shi_route.needs_clarification is False
    su_shi_plan = build_task_plan(su_shi_route, {"message": "结合教材解释", "conversation_history": su_shi_history}, enable_composition=False)
    assert su_shi_plan.steps[0].operation == "search_history_knowledge", su_shi_plan
    assert "苏轼" in su_shi_plan.steps[0].input["query"], su_shi_plan

    direct_person_route = deterministic_route({"message": "苏轼做了什么"})
    assert direct_person_route.tasks[0].intent.value == "history_search", direct_person_route
    assert direct_person_route.tasks[0].topic == "苏轼", direct_person_route

    for question, expected_topic in {
        "分析下官渡之战": "官渡之战",
        "分析一下官渡之战的意义": "官渡之战",
    }.items():
        analysis_route = deterministic_route({"message": question})
        assert analysis_route.tasks[0].intent.value == "history_search", analysis_route
        assert analysis_route.tasks[0].topic == expected_topic, analysis_route
        assert analysis_route.needs_clarification is False, analysis_route

    normalized_topics = {
        "赤壁之战的影响是什么": "赤壁之战",
        "商鞅变法的主要原因有哪些": "商鞅变法",
        "洋务运动失败原因": "洋务运动",
        "鸦片战争的导火索是什么？": "鸦片战争",
    }
    for question, expected_topic in normalized_topics.items():
        normalized_route = deterministic_route({"message": question})
        assert normalized_route.tasks[0].intent.value == "history_search", normalized_route
        assert normalized_route.tasks[0].topic == expected_topic, normalized_route
        assert all(expected_topic in item for item in la._suggestions_for_route(normalized_route)), normalized_route

    clarification_history = [{
        "role": "assistant",
        "content": "你指的是哪一课？",
        "metadata": {
            "completion_status": "needs_clarification",
            "routing": {
                "completion_status": "needs_clarification",
                "pending_task": {"intent": "textbook_qa"},
                "missing_slots": ["book_id", "lesson_id"],
            },
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }]
    resolved_route = deterministic_route({"message": "我指的是洋务运动", "conversation_history": clarification_history})
    assert resolved_route.tasks[0].intent.value == "textbook_qa", resolved_route
    assert resolved_route.tasks[0].topic == "洋务运动", resolved_route
    assert resolved_route.needs_clarification is False
    resolved_plan = build_task_plan(resolved_route, {"message": "我指的是洋务运动", "conversation_history": clarification_history}, enable_composition=False)
    assert [step.operation for step in resolved_plan.steps] == ["search_history_knowledge", "answer_from_sources"], resolved_plan

    expired_history = [{**clarification_history[0], "created_at": (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()}]
    expired_route = deterministic_route({"message": "我指的是洋务运动", "conversation_history": expired_history})
    assert expired_route.tasks[0].intent.value == "history_search", expired_route
    switched_route = deterministic_route({"message": "改讲辛亥革命为什么成功", "conversation_history": clarification_history})
    assert switched_route.tasks[0].intent.value == "history_search", switched_route
    assert switched_route.reason_code != "pending_clarification_resolved", switched_route

    feedback = asyncio.run(learning_assistant_feedback(
        session["session_id"],
        assistant_message["message_id"],
        LearningAssistantFeedbackRequest(feedback="unresolved"),
        Actor(actor_id=student_id, role="student"),
    ))
    assert feedback["changed"] is True
    assert "更简单" in feedback["followup_prompt"]
    stored = next(item for item in list_messages(session["session_id"]) if item["message_id"] == assistant_message["message_id"])
    assert stored["metadata"]["feedback"] == "unresolved"
    repeated = asyncio.run(learning_assistant_feedback(
        session["session_id"],
        assistant_message["message_id"],
        LearningAssistantFeedbackRequest(feedback="unresolved"),
        Actor(actor_id=student_id, role="student"),
    ))
    assert repeated["changed"] is False
    feedback_events = list_learning_events(student_id=student_id, feature="learning_assistant", event_type="answer_feedback")
    assert len(feedback_events) == 1
    assert feedback_events[0]["metadata"]["feedback"] == "unresolved"

    original_stream = la.stream_learning_assistant_events
    la.stream_learning_assistant_events = lambda request: iter([
        ("final", {
            "response": "换成生活中的例子：市场就像一扇被强行推开的门。",
            "intent": "chat",
            "tool_results": [],
            "routing": {"schema_version": 2, "mode": "rule", "task_count": 1, "reason_code": "general_chat"},
            "plan_summary": {"completed_steps": 1, "total_steps": 1},
            "completion_status": "completed",
        }),
    ])
    try:
        api_result = asyncio.run(learning_assistant_chat(
            LearningAssistantRequest(session_id=session["session_id"], message="换个例子", stream=False),
            Actor(actor_id=student_id, role="student"),
        ))
    finally:
        la.stream_learning_assistant_events = original_stream
    persisted_id = api_result["final"].get("message_id")
    assert persisted_id and any(item["message_id"] == persisted_id for item in list_messages(session["session_id"])), api_result
    persisted_message = next(item for item in list_messages(session["session_id"]) if item["message_id"] == persisted_id)
    assert persisted_message["metadata"]["routing"]["schema_version"] == 2
    assert persisted_message["metadata"]["plan_summary"]["completed_steps"] == 1
    assert persisted_message["metadata"]["completion_status"] == "completed"

    before_regenerate = list_messages(session["session_id"])
    la.stream_learning_assistant_events = lambda request: iter([
        ("final", {"response": "重新生成：市场像一扇被强行推开的门。", "intent": "chat", "tool_results": []}),
    ])
    try:
        regenerated = asyncio.run(learning_assistant_chat(
            LearningAssistantRequest(
                session_id=session["session_id"],
                message="该字段会由后端可信历史覆盖",
                regenerate_message_id=persisted_id,
                stream=False,
            ),
            Actor(actor_id=student_id, role="student"),
        ))
    finally:
        la.stream_learning_assistant_events = original_stream
    after_regenerate = list_messages(session["session_id"])
    assert len(after_regenerate) == len(before_regenerate)
    assert regenerated["final"]["response"].startswith("重新生成")
    assert after_regenerate[-2]["content"] == "换个例子"

    ready_book = next(item for item in list_textbooks() if item.status == "ready")
    ready_lesson = get_toc(ready_book.id).units[0].lessons[0]
    context_result = asyncio.run(learning_assistant_update_context(
        session["session_id"],
        LearningAssistantContextUpdateRequest(textbook=LearningAssistantTextbookContext(book_id=ready_book.id, lesson_id=ready_lesson.id)),
        Actor(actor_id=student_id, role="student"),
    ))
    assert context_result["context"]["textbook"]["lesson_id"] == ready_lesson.id
    restored_session = asyncio.run(learning_assistant_get_session(session["session_id"], Actor(actor_id=student_id, role="student")))
    assert restored_session["context"]["textbook"]["book"] == ready_book.book

    renamed = asyncio.run(learning_assistant_update_session(
        session["session_id"],
        LearningAssistantSessionUpdateRequest(title="鸦片战争复习"),
        Actor(actor_id=student_id, role="student"),
    ))
    assert renamed["title"] == "鸦片战争复习"
    listed = asyncio.run(learning_assistant_list_sessions(student_id, "all", 50, Actor(actor_id=student_id, role="student")))
    assert any(item["session_id"] == session["session_id"] and item["message_count"] >= 4 for item in listed["sessions"])

    archived = asyncio.run(learning_assistant_update_session(
        session["session_id"],
        LearningAssistantSessionUpdateRequest(status="archived"),
        Actor(actor_id=student_id, role="student"),
    ))
    assert archived["status"] == "archived"
    active_only = asyncio.run(learning_assistant_list_sessions(student_id, "active", 50, Actor(actor_id=student_id, role="student")))
    assert all(item["session_id"] != session["session_id"] for item in active_only["sessions"])
    asyncio.run(learning_assistant_update_session(
        session["session_id"],
        LearningAssistantSessionUpdateRequest(status="active"),
        Actor(actor_id=student_id, role="student"),
    ))

    detached = asyncio.run(learning_assistant_update_context(
        session["session_id"],
        LearningAssistantContextUpdateRequest(textbook=None),
        Actor(actor_id=student_id, role="student"),
    ))
    assert "textbook" not in detached["context"]

    for operation in (
        lambda: asyncio.run(learning_assistant_list_sessions(student_id, "all", 50, Actor(actor_id="other-student", role="student"))),
        lambda: asyncio.run(learning_assistant_update_session(
            session["session_id"],
            LearningAssistantSessionUpdateRequest(title="越权修改"),
            Actor(actor_id="other-student", role="student"),
        )),
        lambda: asyncio.run(learning_assistant_update_context(
            session["session_id"],
            LearningAssistantContextUpdateRequest(textbook=LearningAssistantTextbookContext(book_id=ready_book.id, lesson_id=ready_lesson.id)),
            Actor(actor_id="other-student", role="student"),
        )),
    ):
        try:
            operation()
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("cross-student session management was not rejected")

    try:
        asyncio.run(learning_assistant_feedback(
            session["session_id"],
            assistant_message["message_id"],
            LearningAssistantFeedbackRequest(feedback="resolved"),
            Actor(actor_id="other-student", role="student"),
        ))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-student feedback was not rejected")

    request = LearningAssistantRequest(session_id=session["session_id"], student_id=None, message="继续解释", stream=False)
    try:
        asyncio.run(learning_assistant_chat(request, Actor(actor_id="other-student", role="student")))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-student session access was not rejected")

    new_session = create_session(student_id)
    assert list_messages(new_session["session_id"]) == []
    print("learning_assistant_multiturn_smoke=PASS")


if __name__ == "__main__":
    main()
