"""语文功能路由：/api/chinese/*（作文批改）"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from security.auth import Actor, require_auth
from security.audit_log import record_audit_event
from tracing import trace_context
from ._shared import require_teacher_actor, trace_meta

router = APIRouter(prefix="/api/chinese", tags=["chinese"])


class EssayRequest(BaseModel):
    essay: str
    student_id: str


class EssayReviewRequest(BaseModel):
    session_id: str
    approved: bool
    teacher_comments: str = ""
    decision: str = "approved"
    score_override: float | None = None


class BatchEssayRequest(BaseModel):
    essays: list[dict]
    class_id: str | None = None


@router.post("/essay/grade")
async def grade_essay(req: EssayRequest, actor: Actor = Depends(require_auth)):
    from agents.essay_grader import build_grader_graph, EssayState
    from security.prompt_injection import check_user_input
    from session_store import save_messages
    import uuid
    check_user_input(req.essay)
    session_id = req.student_id or str(uuid.uuid4())
    with trace_context(name="POST /api/chinese/essay/grade", metadata=trace_meta("essay_grader", "/api/chinese/essay/grade", student_id=req.student_id), user_id=req.student_id or actor.actor_id):
        graph = build_grader_graph()
        state: EssayState = {"essay": req.essay, "student_id": req.student_id, "draft_score": {}, "draft_comments": "", "final_score": {}, "final_comments": "", "revision_count": 0, "critique_approved": False, "needs_human_review": False, "review_reason": None}
        result = await graph.ainvoke(state)
    from session_store import save_messages
    save_messages(session_id, [{"role": "user", "content": req.essay}, {"role": "assistant", "content": result["final_comments"]}])
    return {"student_id": req.student_id, "session_id": session_id, "comments": result["final_comments"], "needs_human_review": result.get("needs_human_review", False), "review_reason": result.get("review_reason")}


@router.post("/essay/review-result")
async def submit_essay_review(req: EssayReviewRequest, actor: Actor = Depends(require_auth)):
    from session_store import load_messages, save_messages
    msgs = load_messages(req.session_id)
    msgs.append({"role": "system", "content": f"[教师复核] approved={req.approved} decision={req.decision} {req.teacher_comments}".strip()})
    save_messages(req.session_id, msgs)
    record_audit_event(actor_id=actor.actor_id, action="teacher.essay_review", resource_type="essay", resource_id=req.session_id, metadata={"decision": req.decision, "score_override": req.score_override})
    return {"status": "ok", "decision": req.decision}


@router.get("/essay/review-stats")
async def essay_review_stats(actor: Actor = Depends(require_auth)):
    from security.audit_log import list_audit_events
    events = list_audit_events(action="teacher.essay_review", limit=200)
    counts = {"approved": 0, "edited": 0, "rejected": 0}
    for ev in events:
        d = (ev.get("metadata") or {}).get("decision", "approved")
        if d in counts:
            counts[d] += 1
    return {"total": sum(counts.values()), **counts}


@router.post("/essay/grade/batch")
async def batch_grade_essays(req: BatchEssayRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    if len(req.essays) > 50:
        raise HTTPException(status_code=400, detail="单次最多批改 50 篇作文")
    from security.prompt_injection import check_user_input
    from services.batch_essay_service import batch_grade, compute_summary
    for item in req.essays:
        check_user_input(item.get("essay", ""))
    results = await batch_grade(req.essays)
    return {"results": results, "summary": compute_summary(results)}
