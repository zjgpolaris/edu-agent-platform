"""Read-only, source-bound follow-up projection. Never creates schema or tasks."""
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db.engine import get_connection
from services.review_mastery_service import is_due, parse_time
from student_profile import now_iso


def get_follow_up(session, *, at=None):
    timestamp = at or now_iso()
    plan = session.get("lesson_plan") or []
    primary = plan[0] if plan else {}
    tag = str(primary.get("source_tag") or primary.get("knowledge_point") or "")
    result = {"status": "not_scheduled", "objective_label": tag[:160], "due_at": None, "chain_revision": None, "reason_code": None}
    payload = {"schema_version": 1, "session_revision": session.get("revision", 0), "as_of": timestamp, "follow_up": result}
    if session.get("status") != "completed" or (session.get("mastery") or {}).get("status") != "verified":
        return payload
    result.update(status="unavailable", reason_code="evidence_unavailable")
    try:
        with get_connection() as conn:
            state = conn.execute(text("SELECT * FROM review_mastery_state WHERE student_id=:sid AND knowledge_tag=:tag"),
                {"sid": session["student_id"], "tag": tag}).mappings().first()
            if not state:
                return payload
            keys = [state.get("retrieval_evidence_key"), state.get("verification_evidence_key"), state.get("retention_evidence_key")]
            rows = conn.execute(text("SELECT * FROM weakpoint_evidence WHERE evidence_key IN (:a,:b,:c)"),
                dict(zip(("a", "b", "c"), keys))).mappings().all()
        by_key = {r["evidence_key"]: r for r in rows}
        retrieval, verification = by_key.get(keys[0]), by_key.get(keys[1])
        if not retrieval or not verification or verification["evidence_type"] != "independent_correct" or verification["parent_evidence_key"] != keys[0]:
            return payload
        if any(r["student_id"] != session["student_id"] or r["knowledge_tag"] != tag for r in rows):
            return payload
        if any(r["source_session_id"] != session["session_id"] for r in (retrieval, verification)):
            result.update(status="superseded", reason_code="newer_evidence_chain")
            return payload
        status = state["status"]
        if status in {"retention_verified", "needs_retrieval"}:
            retention = by_key.get(keys[2])
            expected = "retention_correct" if status == "retention_verified" else "wrong"
            if not retention or retention["evidence_type"] != expected or retention["parent_evidence_key"] != keys[1]:
                return payload
        elif status == "retention_due":
            status = "due" if is_due(state["retention_due_at"], timestamp) else "scheduled"
        elif status != "content_blocked":
            return payload
        due = parse_time(state["retention_due_at"]).isoformat().replace("+00:00", "Z")
        result.update(status=status, due_at=due, chain_revision=int(state["revision"]),
            reason_code="independent_review_content_missing" if status == "content_blocked" else None)
    except (SQLAlchemyError, ValueError, TypeError, KeyError):
        pass
    return payload
