"""学习助手 + AutoTutor 路由"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from security.auth import Actor, assert_student_access, require_auth
from security.audit_log import record_audit_event
from security.rate_limit import check_rate_limit
from tools.registry import list_tools
from tracing import current_trace_id, trace_context
from ._shared import sse_frame, enforce_guardrails, record_event_if_student, trace_meta

router = APIRouter(tags=["learning"])


class LearningAssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_id: str | None = None
    student_id: str | None = None
    grade: str | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    stream: bool = True
    confirmed_tool_name: str | None = None
    confirmation_token: str | None = None
    confirmation_decision: str | None = None
    regenerate_message_id: str | None = Field(default=None, max_length=128)
    reuse_last_user: bool = False
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


class LearningAssistantSessionCreateRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    source_feature: str = Field(default="standalone", pattern="^(standalone|auto_tutor|textbook)$")
    source_session_id: str | None = Field(default=None, max_length=128)


class LearningAssistantFeedbackRequest(BaseModel):
    feedback: str = Field(pattern="^(resolved|unresolved)$")


class LearningAssistantSessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class LearningAssistantTextbookContext(BaseModel):
    book_id: str = Field(min_length=1, max_length=160)
    lesson_id: str = Field(min_length=1, max_length=160)


class LearningAssistantContextUpdateRequest(BaseModel):
    textbook: LearningAssistantTextbookContext | None = None


class ToolConfirmationCancelRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    confirmation_token: str | None = None
    student_id: str | None = None


class AutoTutorStartRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    grade: str | None = None
    focus_tags: list[str] | None = None
    focus_reason: str | None = Field(default=None, max_length=200)
    lesson_id: str | None = Field(default=None, max_length=160)
    max_minutes: int | None = Field(default=None, ge=5, le=45)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


def _persistable_tool_results(items: list[dict] | None) -> list[dict]:
    """Strip ephemeral confirmation credentials before message persistence."""
    persisted: list[dict] = []
    for item in items or []:
        clean = dict(item)
        clean.pop("confirmation_token", None)
        metadata = dict(clean.get("metadata") or {})
        metadata.pop("confirmation_token", None)
        clean["metadata"] = metadata
        persisted.append(clean)
    return persisted


class AutoTutorAnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=8)
    student_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


@router.get("/api/learning/assistant/tools")
async def learning_assistant_tools(actor: Actor = Depends(require_auth)):
    return {"schema_version": 1, "tools": list_tools()}


@router.post("/api/learning/assistant/sessions")
async def learning_assistant_create_session(req: LearningAssistantSessionCreateRequest, actor: Actor = Depends(require_auth)):
    from services.learning_assistant_session_service import create_session, get_active_source_session
    assert_student_access(actor, req.student_id)
    context = {}
    if req.source_feature == "auto_tutor":
        if not req.source_session_id:
            raise HTTPException(status_code=400, detail="AutoTutor 来源必须提供 source_session_id")
        from agents.auto_tutor import get_learning_assistant_handoff
        try:
            handoff = await run_in_threadpool(get_learning_assistant_handoff, req.source_session_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="AutoTutor 辅导会话不存在")
        assert_student_access(actor, handoff.student_id)
        if handoff.student_id != req.student_id:
            raise HTTPException(status_code=403, detail="无权使用该辅导会话")
        context = handoff.context.model_dump(mode="json")
        existing = await run_in_threadpool(get_active_source_session, req.student_id, req.source_feature, req.source_session_id)
        if existing:
            record_event_if_student(
                req.student_id,
                session_id=existing["session_id"],
                feature="learning_assistant",
                event_type="session_resumed",
                metadata={"source_feature": req.source_feature, "source_session_id": req.source_session_id},
            )
            return existing
    session = await run_in_threadpool(
        create_session,
        req.student_id,
        source_feature=req.source_feature,
        source_session_id=req.source_session_id,
        context=context,
    )
    record_event_if_student(
        req.student_id,
        session_id=session["session_id"],
        feature="learning_assistant",
        event_type="session_created",
        metadata={"source_feature": req.source_feature},
    )
    record_audit_event(actor_id=actor.actor_id, action="learning_assistant.session_created", resource_type="student", resource_id=req.student_id, metadata={"session_id": session["session_id"], "source_feature": req.source_feature})
    return session


@router.get("/api/learning/assistant/sessions/{session_id}")
async def learning_assistant_get_session(session_id: str, actor: Actor = Depends(require_auth)):
    from services.learning_assistant_session_service import get_session, list_messages
    try:
        session = await run_in_threadpool(get_session, session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="随问会话不存在")
    assert_student_access(actor, str(session["student_id"]))
    session["messages"] = await run_in_threadpool(list_messages, session_id)
    return session


@router.patch("/api/learning/assistant/sessions/{session_id}")
async def learning_assistant_update_session(
    session_id: str,
    req: LearningAssistantSessionUpdateRequest,
    actor: Actor = Depends(require_auth),
):
    from services.learning_assistant_session_service import get_session, update_session
    try:
        session = await run_in_threadpool(get_session, session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="随问会话不存在")
    assert_student_access(actor, str(session["student_id"]))
    if req.title is None and req.status is None:
        raise HTTPException(status_code=400, detail="没有需要更新的会话字段")
    try:
        updated = await run_in_threadpool(update_session, session_id, title=req.title, status=req.status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    record_audit_event(
        actor_id=actor.actor_id,
        action="learning_assistant.session_updated",
        resource_type="student",
        resource_id=str(session["student_id"]),
        metadata={"session_id": session_id, "title_changed": req.title is not None, "status": req.status},
    )
    return updated


@router.patch("/api/learning/assistant/sessions/{session_id}/context")
async def learning_assistant_update_context(
    session_id: str,
    req: LearningAssistantContextUpdateRequest,
    actor: Actor = Depends(require_auth),
):
    from services.learning_assistant_session_service import get_session, update_textbook_context
    from textbook_learning.loader import get_lesson
    try:
        session = await run_in_threadpool(get_session, session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="随问会话不存在")
    student_id = str(session["student_id"])
    assert_student_access(actor, student_id)
    textbook = None
    if req.textbook is not None:
        try:
            lesson = await run_in_threadpool(get_lesson, req.textbook.book_id, req.textbook.lesson_id)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        textbook = {
            "book_id": lesson.book_id,
            "lesson_id": lesson.lesson_id,
            "grade": lesson.grade,
            "book": lesson.book,
            "lesson_title": lesson.lesson_title,
        }
    try:
        updated = await run_in_threadpool(update_textbook_context, session_id, textbook)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    event_type = "assistant_context_attached" if textbook else "assistant_context_detached"
    record_event_if_student(
        student_id,
        session_id=session_id,
        feature="learning_assistant",
        event_type=event_type,
        book_id=(textbook or {}).get("book_id"),
        lesson_id=(textbook or {}).get("lesson_id"),
        metadata={"source": "manual"},
    )
    record_audit_event(
        actor_id=actor.actor_id,
        action=f"learning_assistant.{event_type}",
        resource_type="student",
        resource_id=student_id,
        metadata={"session_id": session_id, "book_id": (textbook or {}).get("book_id"), "lesson_id": (textbook or {}).get("lesson_id")},
    )
    return updated


@router.get("/api/learning/assistant/students/{student_id}/latest-session")
async def learning_assistant_get_latest_session(student_id: str, actor: Actor = Depends(require_auth)):
    from services.learning_assistant_session_service import get_latest_session
    assert_student_access(actor, student_id)
    try:
        session = await run_in_threadpool(get_latest_session, student_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="暂无随问会话")
    if session.get("messages"):
        record_event_if_student(
            student_id,
            session_id=session["session_id"],
            feature="learning_assistant",
            event_type="session_resumed",
            metadata={"message_count": len(session["messages"])},
        )
    return session


@router.get("/api/learning/assistant/students/{student_id}/sessions")
async def learning_assistant_list_sessions(
    student_id: str,
    status: str = "all",
    limit: int = 50,
    actor: Actor = Depends(require_auth),
):
    from services.learning_assistant_session_service import list_sessions
    assert_student_access(actor, student_id)
    if status not in {"all", "active", "archived"}:
        raise HTTPException(status_code=400, detail="无效的会话状态")
    sessions = await run_in_threadpool(list_sessions, student_id, status=None if status == "all" else status, limit=limit)
    return {"sessions": sessions}


@router.post("/api/learning/assistant/sessions/{session_id}/return-to-source")
async def learning_assistant_return_to_source(session_id: str, actor: Actor = Depends(require_auth)):
    from services.learning_assistant_session_service import get_session
    try:
        session = await run_in_threadpool(get_session, session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="随问会话不存在")
    assert_student_access(actor, str(session["student_id"]))
    if session.get("source_feature") != "auto_tutor" or not session.get("source_session_id"):
        raise HTTPException(status_code=409, detail="当前随问会话没有可返回的自主辅导")
    record_event_if_student(
        str(session["student_id"]),
        session_id=str(session["source_session_id"]),
        feature="auto_tutor",
        event_type="autotutor_question_returned",
        metadata={"assistant_session_id": session_id},
    )
    return {"ok": True, "return_path": (session.get("context") or {}).get("return_path") or "/student/auto-tutor"}


@router.post("/api/learning/assistant/sessions/{session_id}/messages/{message_id}/feedback")
async def learning_assistant_feedback(
    session_id: str,
    message_id: str,
    req: LearningAssistantFeedbackRequest,
    actor: Actor = Depends(require_auth),
):
    from services.learning_assistant_session_service import get_session, set_message_feedback
    try:
        session = await run_in_threadpool(get_session, session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="随问会话不存在")
    assert_student_access(actor, str(session["student_id"]))
    try:
        result = await run_in_threadpool(set_message_feedback, session_id, message_id, req.feedback)
    except LookupError:
        raise HTTPException(status_code=404, detail="随问回答不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result["changed"]:
        record_event_if_student(
            str(session["student_id"]),
            session_id=session_id,
            feature="learning_assistant",
            event_type="answer_feedback",
            metadata={
                "message_id": message_id,
                "feedback": req.feedback,
                "source_feature": session.get("source_feature"),
                "history_messages": result["history_messages"],
            },
        )
    return {
        **result,
        "followup_prompt": (
            "我仍没懂上一条回答。请用更简单的说法，配一个生活化例子，再分步骤解释一次。"
            if req.feedback == "unresolved" else None
        ),
    }


@router.post("/api/learning/assistant/tool-confirmation/cancel")
async def learning_assistant_cancel_tool_confirmation(req: ToolConfirmationCancelRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
    record_audit_event(actor_id=actor.actor_id, action="tool.confirmation_cancelled", resource_type="tool", resource_id=req.tool_name, success=True, metadata={"tool_name": req.tool_name, "student_id": req.student_id, "request_source": "learning_assistant"})
    return {"ok": True, "status": "cancelled", "tool_name": req.tool_name, "trace_id": current_trace_id()}


@router.post("/api/learning/assistant/chat")
async def learning_assistant_chat(req: LearningAssistantRequest, actor: Actor = Depends(require_auth)):
    from agents.learning_assistant import stream_learning_assistant_events
    from services.learning_assistant_session_service import append_idempotent_user_message, append_message, get_session, list_messages, prepare_regeneration, replace_assistant_message, validate_last_user_message
    from security.auth import auth_required
    session = None
    if req.session_id:
        try:
            session = await run_in_threadpool(get_session, req.session_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="随问会话不存在")
        session_student_id = str(session["student_id"])
        assert_student_access(actor, session_student_id)
        if req.student_id and req.student_id != session_student_id:
            raise HTTPException(status_code=403, detail="会话不属于该学生")
        req.student_id = session_student_id
    if req.student_id:
        assert_student_access(actor, req.student_id)
        check_rate_limit(f"learning-assistant:{req.student_id}", limit=80, window_seconds=3600)
    regenerating = False
    if req.regenerate_message_id:
        if not session or not req.session_id:
            raise HTTPException(status_code=409, detail="重新生成需要有效的随问会话")
        try:
            req.message = await run_in_threadpool(prepare_regeneration, req.session_id, req.regenerate_message_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        regenerating = True
    reusing_last_user = False
    if req.reuse_last_user:
        if not session or not req.session_id or regenerating:
            raise HTTPException(status_code=409, detail="重试需要有效且未重新生成的随问会话")
        try:
            await run_in_threadpool(validate_last_user_message, req.session_id, req.message)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        reusing_last_user = True
    if session:
        textbook = (session.get("context") or {}).get("textbook") or {}
        req.grade = req.grade or textbook.get("grade")
        req.book_id = req.book_id or textbook.get("book_id")
        req.lesson_id = req.lesson_id or textbook.get("lesson_id")
    existing_runtime_run = None
    runtime_idempotency_active = False
    if req.idempotency_key:
        from agent_runtime.context import RuntimeV2Settings

        runtime_settings = RuntimeV2Settings.from_env()
        runtime_subject = str(actor.actor_id or req.student_id or req.session_id or "")
        runtime_active, _ = runtime_settings.rollout_decision("learning_assistant", runtime_subject)
        if runtime_active and runtime_settings.observable_ready:
            runtime_idempotency_active = True
            from agent_runtime.event_store import get_run_by_idempotency_key

            existing_runtime_run = await run_in_threadpool(
                get_run_by_idempotency_key,
                actor_id=actor.actor_id,
                idempotency_key=req.idempotency_key,
            )
            if existing_runtime_run and str(existing_runtime_run.get("session_id") or "") != str(req.session_id or ""):
                raise HTTPException(status_code=409, detail="Idempotency key 已绑定到其他随问会话。")
    request_data = req.model_dump()
    request_data["actor_id"] = actor.actor_id
    request_data["actor_role"] = "student" if req.student_id and not auth_required() else actor.role
    if session:
        history = await run_in_threadpool(list_messages, req.session_id)
        request_data["conversation_history"] = history
        request_data["source_context"] = session.get("context") or {}
        request_data["source_feature"] = session.get("source_feature")
        request_data["source_session_id"] = session.get("source_session_id")
    metadata = trace_meta("learning_assistant_chat", "/api/learning/assistant/chat", session_id=req.session_id, student_id=req.student_id, grade=req.grade, book_id=req.book_id, lesson_id=req.lesson_id, stream=req.stream)

    if not req.stream:
        with trace_context(name="POST /api/learning/assistant/chat", metadata=metadata, user_id=req.student_id, session_id=req.session_id, input_data={"message": req.message}):
            trace_id = current_trace_id()
            try:
                enforce_guardrails(req.message, actor=actor, route="/api/learning/assistant/chat", student_id=req.student_id, resource_type="student" if req.student_id else None)
            except HTTPException as exc:
                guardrail_step = {"event": "runtime_step", "data": {"trace_id": trace_id, "agent_name": "learning_assistant", "step_id": "guardrail_check", "step_name": "Guardrail Check", "event_type": "guardrail", "status": "failed", "latency_ms": None, "metadata": {"error_code": "guardrail_failed", "message": exc.detail}}}
                raise HTTPException(status_code=exc.status_code, detail={"message": exc.detail, "events": [guardrail_step]}) from exc
            if session and not req.confirmation_decision and not regenerating and not reusing_last_user:
                try:
                    if runtime_idempotency_active and req.idempotency_key:
                        await run_in_threadpool(
                            append_idempotent_user_message,
                            req.session_id,
                            req.message,
                            idempotency_key=req.idempotency_key,
                            source_feature=session["source_feature"],
                        )
                    elif existing_runtime_run is None:
                        await run_in_threadpool(append_message, req.session_id, "user", req.message, metadata={"source_feature": session["source_feature"]})
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
            guardrail_step = {"event": "runtime_step", "data": {"trace_id": trace_id, "agent_name": "learning_assistant", "step_id": "guardrail_check", "step_name": "Guardrail Check", "sequence": 0, "event_type": "guardrail", "status": "success", "latency_ms": None, "metadata": {"route": "/api/learning/assistant/chat"}, "error": None}}
            record_audit_event(actor_id=actor.actor_id, action="learning_assistant.chat", resource_type="student" if req.student_id else None, resource_id=req.student_id, metadata={"stream": req.stream, "grade": req.grade})
            request_data["trace_id"] = trace_id
            events = list(stream_learning_assistant_events(request_data))
            final = next((data for event, data in events if event == "final"), None)
            if session and final and final.get("response") and not final.get("idempotent_replay"):
                context_usage = final.get("context_usage") or {}
                persist_fn = replace_assistant_message if regenerating else append_message
                persist_args = (req.session_id, req.regenerate_message_id, final["response"]) if regenerating else (req.session_id, "assistant", final["response"])
                persisted = await run_in_threadpool(
                    persist_fn,
                    *persist_args,
                    intent=final.get("intent"),
                    trace_id=trace_id,
                    tool_results=_persistable_tool_results(final.get("tool_results")),
                    metadata={
                        "history_messages": int(context_usage.get("history_messages") or 0),
                        "generation_mode": final.get("generation_mode"),
                        "source_feature": session.get("source_feature"),
                        "source_session_id": session.get("source_session_id"),
                        "textbook": (session.get("context") or {}).get("textbook"),
                        "used_memory_count": len(((final.get("profile_context") or {}).get("used_memory") or [])),
                        "tool_names": [item.get("tool_name") for item in (final.get("tool_results") or []) if item.get("tool_name")],
                        "routing": final.get("routing") or {},
                        "plan_summary": final.get("plan_summary") or {},
                        "completion_status": final.get("completion_status"),
                        "rollout_summary": final.get("rollout_summary") or {},
                        "verification_summary": final.get("verification_summary") or {},
                        "run_id": final.get("run_id"),
                        "run_revision": final.get("run_revision"),
                        "event_cursor": final.get("event_cursor"),
                    },
                )
                final["message_id"] = persisted["message_id"]
            suggestions = next((data for event, data in events if event == "suggestions"), None)
            intent = next((data for event, data in events if event == "intent"), None)
            return {"trace_id": trace_id, "intent": intent, "final": final, "suggestions": suggestions, "events": [guardrail_step, *[{"event": event, "data": data} for event, data in events]]}

    async def event_stream():
        with trace_context(name="POST /api/learning/assistant/chat", metadata=metadata, user_id=req.student_id, session_id=req.session_id, input_data={"message": req.message}):
            trace_id = current_trace_id()
            yield sse_frame("trace", {"trace_id": trace_id})
            try:
                enforce_guardrails(req.message, actor=actor, route="/api/learning/assistant/chat", student_id=req.student_id, resource_type="student" if req.student_id else None)
                yield sse_frame("runtime_step", {"trace_id": trace_id, "agent_name": "learning_assistant", "step_id": "guardrail_check", "step_name": "Guardrail Check", "sequence": 0, "event_type": "guardrail", "status": "success", "latency_ms": None, "metadata": {"route": "/api/learning/assistant/chat"}, "error": None})
            except HTTPException as exc:
                yield sse_frame("runtime_step", {"trace_id": trace_id, "agent_name": "learning_assistant", "step_id": "guardrail_check", "step_name": "Guardrail Check", "sequence": 0, "event_type": "guardrail", "status": "failed", "latency_ms": None, "metadata": {"error_code": "guardrail_failed", "message": exc.detail}, "error": {"code": "guardrail_failed", "message": exc.detail, "retryable": False}})
                yield sse_frame("error", {"message": exc.detail})
                return
            if session and not req.confirmation_decision and not regenerating and not reusing_last_user:
                try:
                    if runtime_idempotency_active and req.idempotency_key:
                        await run_in_threadpool(
                            append_idempotent_user_message,
                            req.session_id,
                            req.message,
                            idempotency_key=req.idempotency_key,
                            source_feature=session["source_feature"],
                        )
                    elif existing_runtime_run is None:
                        await run_in_threadpool(append_message, req.session_id, "user", req.message, metadata={"source_feature": session["source_feature"]})
                except ValueError as exc:
                    yield sse_frame("error", {"code": "idempotency_conflict", "message": str(exc)})
                    return
            record_audit_event(actor_id=actor.actor_id, action="learning_assistant.chat", resource_type="student" if req.student_id else None, resource_id=req.student_id, metadata={"stream": req.stream, "grade": req.grade})
            request_data["trace_id"] = trace_id
            iterator = stream_learning_assistant_events(request_data)
            try:
                while True:
                    item = await run_in_threadpool(lambda: next(iterator, None))
                    if item is None:
                        break
                    event, data = item
                    if event == "final" and session and data.get("response") and not data.get("idempotent_replay"):
                        context_usage = data.get("context_usage") or {}
                        persist_fn = replace_assistant_message if regenerating else append_message
                        persist_args = (req.session_id, req.regenerate_message_id, data["response"]) if regenerating else (req.session_id, "assistant", data["response"])
                        persisted = await run_in_threadpool(
                            persist_fn,
                            *persist_args,
                            intent=data.get("intent"),
                            trace_id=trace_id,
                            tool_results=_persistable_tool_results(data.get("tool_results")),
                            metadata={
                                "history_messages": int(context_usage.get("history_messages") or 0),
                                "generation_mode": data.get("generation_mode"),
                                "source_feature": session.get("source_feature"),
                                "source_session_id": session.get("source_session_id"),
                                "textbook": (session.get("context") or {}).get("textbook"),
                                "used_memory_count": len(((data.get("profile_context") or {}).get("used_memory") or [])),
                                "tool_names": [item.get("tool_name") for item in (data.get("tool_results") or []) if item.get("tool_name")],
                                "routing": data.get("routing") or {},
                                "plan_summary": data.get("plan_summary") or {},
                                "completion_status": data.get("completion_status"),
                                "rollout_summary": data.get("rollout_summary") or {},
                                "verification_summary": data.get("verification_summary") or {},
                                "run_id": data.get("run_id"),
                                "run_revision": data.get("run_revision"),
                                "event_cursor": data.get("event_cursor"),
                            },
                        )
                        data = {**data, "message_id": persisted["message_id"]}
                    yield sse_frame(event, data, event_id=data.get("event_cursor"))
                    await asyncio.sleep(0)
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/autotutor/start")
async def autotutor_start_session(req: AutoTutorStartRequest, actor: Actor = Depends(require_auth)):
    from agents.auto_tutor import AutoTutorUnavailableError, start_session as autotutor_start
    from security.auth import auth_required
    assert_student_access(actor, req.student_id)
    check_rate_limit(f"autotutor:{req.student_id}", limit=40, window_seconds=3600)
    actor_role = "student" if not auth_required() else actor.role
    with trace_context(name="POST /api/autotutor/start", metadata=trace_meta("auto_tutor", "/api/autotutor/start", student_id=req.student_id, grade=req.grade), user_id=req.student_id, input_data={"student_id": req.student_id}):
        trace_id = current_trace_id()
        record_audit_event(actor_id=actor.actor_id, action="autotutor.start", resource_type="student", resource_id=req.student_id, metadata={"grade": req.grade})
        try:
            return await run_in_threadpool(
                autotutor_start,
                req.student_id,
                grade=req.grade,
                actor_id=actor.actor_id,
                actor_role=actor_role,
                trace_id=trace_id,
                focus_tags=req.focus_tags or None,
                focus_reason=req.focus_reason or None,
                lesson_id=req.lesson_id,
                max_minutes=req.max_minutes,
                idempotency_key=req.idempotency_key,
            )
        except AutoTutorUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))


@router.post("/api/autotutor/answer")
async def autotutor_submit_answer(req: AutoTutorAnswerRequest, actor: Actor = Depends(require_auth)):
    from agents.auto_tutor import (
        AutoTutorIdempotencyConflict,
        get_session as autotutor_get,
        submit_answer as autotutor_answer,
    )
    from security.auth import auth_required
    try:
        session = await run_in_threadpool(autotutor_get, req.session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="辅导会话不存在或已过期，请重新开始")
    # Authorize against the persisted session owner. student_id is retained only
    # for backwards-compatible audit metadata and must never be trusted for access.
    session_student_id = str(session["student_id"])
    assert_student_access(actor, session_student_id)
    actor_role = "student" if not auth_required() else actor.role
    record_audit_event(actor_id=actor.actor_id, action="autotutor.answer", resource_type="student", resource_id=session_student_id, metadata={"session_id": req.session_id})
    try:
        return await run_in_threadpool(
            autotutor_answer,
            req.session_id,
            req.answer,
            actor_id=actor.actor_id,
            actor_role=actor_role,
            expected_revision=req.expected_revision,
            idempotency_key=req.idempotency_key,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="辅导会话不存在或已过期，请重新开始")
    except AutoTutorIdempotencyConflict:
        raise HTTPException(status_code=409, detail="同一幂等键不能提交不同答案")


@router.get("/api/autotutor/session/{session_id}")
async def autotutor_get_session(session_id: str, actor: Actor = Depends(require_auth)):
    from agents.auto_tutor import get_session as autotutor_get
    try:
        state = autotutor_get(session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="辅导会话不存在或已过期")
    if req_student := state.get("student_id"):
        assert_student_access(actor, req_student)
    return state


@router.get("/api/autotutor/student/{student_id}/latest-session")
async def autotutor_get_latest_session(student_id: str, include_completed: bool = False, actor: Actor = Depends(require_auth)):
    from agents.auto_tutor import get_latest_session as autotutor_get_latest
    assert_student_access(actor, student_id)
    try:
        return await run_in_threadpool(autotutor_get_latest, student_id, include_completed=include_completed)
    except LookupError:
        raise HTTPException(status_code=404, detail="暂无可恢复的辅导会话")
