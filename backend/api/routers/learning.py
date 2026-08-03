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
from ._shared import sse_frame, enforce_guardrails, trace_meta

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


class ToolConfirmationCancelRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    confirmation_token: str | None = None
    student_id: str | None = None


class AutoTutorStartRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    grade: str | None = None
    focus_tags: list[str] | None = None
    focus_reason: str | None = Field(default=None, max_length=200)


class AutoTutorAnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=8)
    student_id: str | None = None


@router.get("/api/learning/assistant/tools")
async def learning_assistant_tools(actor: Actor = Depends(require_auth)):
    return {"schema_version": 1, "tools": list_tools()}


@router.post("/api/learning/assistant/tool-confirmation/cancel")
async def learning_assistant_cancel_tool_confirmation(req: ToolConfirmationCancelRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
    record_audit_event(actor_id=actor.actor_id, action="tool.confirmation_cancelled", resource_type="tool", resource_id=req.tool_name, success=True, metadata={"tool_name": req.tool_name, "student_id": req.student_id, "request_source": "learning_assistant"})
    return {"ok": True, "status": "cancelled", "tool_name": req.tool_name, "trace_id": current_trace_id()}


@router.post("/api/learning/assistant/chat")
async def learning_assistant_chat(req: LearningAssistantRequest, actor: Actor = Depends(require_auth)):
    from agents.learning_assistant import stream_learning_assistant_events
    from security.auth import auth_required
    if req.student_id:
        assert_student_access(actor, req.student_id)
        check_rate_limit(f"learning-assistant:{req.student_id}", limit=80, window_seconds=3600)
    request_data = req.model_dump()
    request_data["actor_id"] = actor.actor_id
    request_data["actor_role"] = "student" if req.student_id and not auth_required() else actor.role
    metadata = trace_meta("learning_assistant_chat", "/api/learning/assistant/chat", session_id=req.session_id, student_id=req.student_id, grade=req.grade, book_id=req.book_id, lesson_id=req.lesson_id, stream=req.stream)

    if not req.stream:
        with trace_context(name="POST /api/learning/assistant/chat", metadata=metadata, user_id=req.student_id, session_id=req.session_id, input_data={"message": req.message}):
            trace_id = current_trace_id()
            try:
                enforce_guardrails(req.message, actor=actor, route="/api/learning/assistant/chat", student_id=req.student_id, resource_type="student" if req.student_id else None)
            except HTTPException as exc:
                guardrail_step = {"event": "runtime_step", "data": {"trace_id": trace_id, "agent_name": "learning_assistant", "step_id": "guardrail_check", "step_name": "Guardrail Check", "event_type": "guardrail", "status": "failed", "latency_ms": None, "metadata": {"error_code": "guardrail_failed", "message": exc.detail}}}
                raise HTTPException(status_code=exc.status_code, detail={"message": exc.detail, "events": [guardrail_step]}) from exc
            guardrail_step = {"event": "runtime_step", "data": {"trace_id": trace_id, "agent_name": "learning_assistant", "step_id": "guardrail_check", "step_name": "Guardrail Check", "sequence": 0, "event_type": "guardrail", "status": "success", "latency_ms": None, "metadata": {"route": "/api/learning/assistant/chat"}, "error": None}}
            record_audit_event(actor_id=actor.actor_id, action="learning_assistant.chat", resource_type="student" if req.student_id else None, resource_id=req.student_id, metadata={"stream": req.stream, "grade": req.grade})
            request_data["trace_id"] = trace_id
            events = list(stream_learning_assistant_events(request_data))
            final = next((data for event, data in events if event == "final"), None)
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
            record_audit_event(actor_id=actor.actor_id, action="learning_assistant.chat", resource_type="student" if req.student_id else None, resource_id=req.student_id, metadata={"stream": req.stream, "grade": req.grade})
            request_data["trace_id"] = trace_id
            iterator = stream_learning_assistant_events(request_data)
            try:
                while True:
                    item = await run_in_threadpool(lambda: next(iterator, None))
                    if item is None:
                        break
                    event, data = item
                    yield sse_frame(event, data)
                    await asyncio.sleep(0)
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/autotutor/start")
async def autotutor_start_session(req: AutoTutorStartRequest, actor: Actor = Depends(require_auth)):
    from agents.auto_tutor import start_session as autotutor_start
    from security.auth import auth_required
    assert_student_access(actor, req.student_id)
    check_rate_limit(f"autotutor:{req.student_id}", limit=40, window_seconds=3600)
    actor_role = "student" if not auth_required() else actor.role
    with trace_context(name="POST /api/autotutor/start", metadata=trace_meta("auto_tutor", "/api/autotutor/start", student_id=req.student_id, grade=req.grade), user_id=req.student_id, input_data={"student_id": req.student_id}):
        trace_id = current_trace_id()
        record_audit_event(actor_id=actor.actor_id, action="autotutor.start", resource_type="student", resource_id=req.student_id, metadata={"grade": req.grade})
        return await run_in_threadpool(autotutor_start, req.student_id, grade=req.grade, actor_id=actor.actor_id, actor_role=actor_role, trace_id=trace_id, focus_tags=req.focus_tags or None, focus_reason=req.focus_reason or None)


@router.post("/api/autotutor/answer")
async def autotutor_submit_answer(req: AutoTutorAnswerRequest, actor: Actor = Depends(require_auth)):
    from agents.auto_tutor import submit_answer as autotutor_answer
    from security.auth import auth_required
    if req.student_id:
        assert_student_access(actor, req.student_id)
    actor_role = "student" if not auth_required() else actor.role
    record_audit_event(actor_id=actor.actor_id, action="autotutor.answer", resource_type="student", resource_id=req.student_id, metadata={"session_id": req.session_id})
    try:
        return await run_in_threadpool(autotutor_answer, req.session_id, req.answer, actor_id=actor.actor_id, actor_role=actor_role)
    except LookupError:
        raise HTTPException(status_code=404, detail="辅导会话不存在或已过期，请重新开始")


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
