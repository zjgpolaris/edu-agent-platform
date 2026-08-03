"""教材/教科书路由：/api/textbooks/*, /api/textbook-learning/*"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from security.auth import Actor, require_auth
from textbook_learning.schema import TextbookAskRequest, TextbookQuizRequest, TextbookSummaryRequest, TextbookQuizSubmitRequest
from textbook_learning.service import generate_quiz, get_lesson, get_toc, list_textbooks, stream_ask_events, stream_summary_events, submit_quiz_answers
from tracing import trace_context
from ._shared import sse_frame, record_event_if_student, trace_meta

router = APIRouter(tags=["textbook"])
_next = lambda it: next(it, None)


@router.get("/api/textbooks")
async def textbooks_list(actor: Actor = Depends(require_auth)):
    return {"textbooks": [item.model_dump() for item in list_textbooks()]}


@router.get("/api/textbooks/{book_id}/toc")
async def textbook_toc(book_id: str, actor: Actor = Depends(require_auth)):
    try:
        return get_toc(book_id).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/textbooks/{book_id}/lessons/{lesson_id}")
async def textbook_lesson(book_id: str, lesson_id: str, actor: Actor = Depends(require_auth)):
    try:
        return get_lesson(book_id, lesson_id).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/textbook-learning/ask")
async def textbook_learning_ask(req: TextbookAskRequest, actor: Actor = Depends(require_auth)):
    async def event_stream():
        with trace_context(name="POST /api/textbook-learning/ask", metadata=trace_meta("textbook_learning_ask", "/api/textbook-learning/ask", session_id=req.session_id, book_id=req.book_id, lesson_id=req.lesson_id, item_id=req.item_id, action=req.action, has_selected_text=bool(req.selected_text), stream=True), user_id=req.student_id, session_id=req.session_id):
            iterator = stream_ask_events(req)
            try:
                while True:
                    item = await run_in_threadpool(_next, iterator)
                    if item is None:
                        break
                    event, data = item
                    yield sse_frame(event, data)
                    await asyncio.sleep(0)
                record_event_if_student(req.student_id, session_id=req.session_id, feature="textbook_learning", event_type="textbook_ask", book_id=req.book_id, lesson_id=req.lesson_id, success=True, metadata={"action": req.action, "item_id": req.item_id})
            except (LookupError, ValueError, Exception) as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/textbook-learning/summary")
async def textbook_learning_summary(req: TextbookSummaryRequest, actor: Actor = Depends(require_auth)):
    async def event_stream():
        with trace_context(name="POST /api/textbook-learning/summary", metadata=trace_meta("textbook_learning_summary", "/api/textbook-learning/summary", book_id=req.book_id, lesson_id=req.lesson_id, mode=req.mode, stream=True), user_id=req.student_id):
            iterator = stream_summary_events(req)
            try:
                while True:
                    item = await run_in_threadpool(_next, iterator)
                    if item is None:
                        break
                    event, data = item
                    yield sse_frame(event, data)
                    await asyncio.sleep(0)
                record_event_if_student(req.student_id, feature="textbook_learning", event_type="textbook_summary", book_id=req.book_id, lesson_id=req.lesson_id, success=True, metadata={"mode": req.mode})
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/textbook-learning/quiz")
async def textbook_learning_quiz(req: TextbookQuizRequest, actor: Actor = Depends(require_auth)):
    with trace_context(name="POST /api/textbook-learning/quiz", metadata=trace_meta("textbook_learning_quiz", "/api/textbook-learning/quiz", book_id=req.book_id, lesson_id=req.lesson_id, stream=False)):
        try:
            result = await run_in_threadpool(generate_quiz, req)
            record_event_if_student(req.student_id, feature="textbook_learning", event_type="quiz_generated", book_id=req.book_id, lesson_id=req.lesson_id, success=True, metadata={"question_count": len(result.questions)})
            return result.model_dump()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/textbook-learning/quiz/submit")
async def textbook_learning_quiz_submit(req: TextbookQuizSubmitRequest, actor: Actor = Depends(require_auth)):
    try:
        result = await run_in_threadpool(submit_quiz_answers, req)
        record_event_if_student(req.student_id, feature="textbook_learning", event_type="quiz_submitted", book_id=req.book_id, lesson_id=req.lesson_id, score=result.get("score"), success=result.get("score", 0) >= 0.6, metadata={"total": result.get("total"), "correct": result.get("correct")})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
