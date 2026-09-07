"""Role and evidence constraints shared by publication, hydration and submission."""
from __future__ import annotations

from sqlalchemy import text

from services.history_review_question import build_curated_review_question, blocked_review_question
from services.review_mastery_service import evidence_rows_with_connection, is_due, stable_chain_id, validate_retention_chain


def chain_rows(conn, state):
    if not state:
        return []
    rows = evidence_rows_with_connection(conn, [state.get("retrieval_evidence_key"), state.get("verification_evidence_key")])
    if any(r.get("student_id") != state["student_id"] or r.get("knowledge_tag") != state["knowledge_tag"] for r in rows):
        return []
    return rows


def role_question(conn, state, role, *, seed="", assessment_id=None):
    if not state:
        return None
    rows = chain_rows(conn, state)
    keys = {r["evidence_key"] for r in rows}
    if state.get("retrieval_evidence_key") not in keys:
        return None
    if role == "retention":
        by_key = {r["evidence_key"]: r for r in rows}
        verified = by_key.get(state.get("verification_evidence_key"), {})
        if verified.get("evidence_type") != "independent_correct" or verified.get("parent_evidence_key") != state.get("retrieval_evidence_key"):
            return None
    return build_curated_review_question(state["knowledge_tag"], task_role=role, target_difficulty="medium",
        selection_seed=seed, assessment_id=assessment_id,
        excluded_assessment_ids={r["assessment_id"] for r in rows if r.get("assessment_id")},
        excluded_fingerprints={r["assessment_fingerprint"] for r in rows if r.get("assessment_fingerprint")})


def matches_chain(task, state):
    return bool(state and task.get("retrieval_evidence_key") == state.get("retrieval_evidence_key")
        and task.get("evidence_chain_id") == stable_chain_id(state["student_id"], state["knowledge_tag"], str(state.get("retrieval_evidence_key") or "")))


def valid_task(conn, task, state, *, at):
    role = task.get("task_role")
    if role not in {"verification", "retention"} or not matches_chain(task, state):
        return False
    if role == "verification" and state.get("status") != "verification_pending":
        return False
    if role == "retention":
        try:
            validate_retention_chain(state=state, evidence_rows=chain_rows(conn, state),
                retention_assessment_id=task.get("question_id"), retention_fingerprint=task.get("assessment_fingerprint"), occurred_at=at)
        except (ValueError, TypeError):
            return False
    current = role_question(conn, state, role, assessment_id=task.get("question_id"))
    return bool(current and all(current.get(key) == task.get(key) for key in
        ("question_id", "assessment_fingerprint", "question", "options", "answer", "material", "difficulty", "task_role")))


def maintain_retention(conn, student_id, today, session_id, tasks, *, at, fault_hook=None):
    """Caller owns review-session lock and transaction; lock chains in tag order."""
    from services.review_mastery_service import get_mastery_state_with_connection
    from services.review_service import _decorate_task
    # Bound candidate generation, but validate every already-published unfinished task.
    due = conn.execute(text("""SELECT knowledge_tag FROM review_mastery_state
        WHERE student_id=:sid AND status IN ('retention_due','content_blocked')
        AND verification_evidence_key IS NOT NULL AND retention_due_at IS NOT NULL
        ORDER BY retention_due_at, knowledge_tag"""), {"sid": student_id}).scalars().all()
    tags = set(due[:8]) | {t.get("tag") for t in tasks if not t.get("done") and t.get("task_role") in {"verification", "retention"}}
    states = {tag: get_mastery_state_with_connection(conn, student_id, tag, for_update=True) for tag in sorted(filter(None, tags))}
    before = [dict(t) for t in tasks]
    # Invalid historical tasks become non-scoreable; preserve indexes and answered history.
    for task in tasks:
        if task.get("done") or task.get("task_role") not in {"verification", "retention"}:
            continue
        state = states.get(task.get("tag"))
        if not valid_task(conn, task, state, at=at):
            replacement = blocked_review_question(str(task.get("tag") or ""), "independent_review_content_missing")
            replacement.update(task_role=task.get("task_role"), retrieval_evidence_key=task.get("retrieval_evidence_key"),
                evidence_chain_id=task.get("evidence_chain_id"), due_at=task.get("due_at"),
                obsolete=not matches_chain(task, state) or bool(state and state["status"] not in {"verification_pending", "retention_due", "content_blocked"}))
            task.clear(); task.update(replacement)
    # Repair only same-chain verification tasks, never generate without exclusions.
    for task in [t for t in tasks if not t.get("done") and t.get("task_role") == "verification"][:8]:
        state = states.get(task.get("tag"))
        if state and state["status"] == "verification_pending" and matches_chain(task, state) and task.get("quality_status") == "blocked":
            question = role_question(conn, state, "verification", seed=f"{session_id}:{state['knowledge_tag']}:repair")
            if question:
                _decorate_task(question, student_id=student_id, session_id=session_id, task_role="verification",
                    retrieval_evidence_key=state["retrieval_evidence_key"])
                task.clear(); task.update(question)
    blocked = []
    additions = []
    for tag in due[:8]:
        state = states[tag]
        if not state or state["status"] not in {"retention_due", "content_blocked"} or not is_due(state.get("retention_due_at"), at):
            continue
        existing = next((t for t in tasks if t.get("task_role") == "retention" and t.get("tag") == tag and matches_chain(t, state)), None)
        if existing and (existing.get("done") or valid_task(conn, existing, state, at=at)):
            continue
        question = role_question(conn, state, "retention", seed=f"{student_id}:{today}:{tag}:retention")
        status = "retention_due" if question else "content_blocked"
        if state["status"] != status:
            changed = conn.execute(text("""UPDATE review_mastery_state SET status=:status, revision=revision+1, updated_at=:at
                WHERE student_id=:sid AND knowledge_tag=:tag AND revision=:revision"""),
                {"status": status, "at": at, "sid": student_id, "tag": tag, "revision": state["revision"]})
            if changed.rowcount != 1:
                from services.review_service import ReviewConflictError
                raise ReviewConflictError("review chain changed", code="evidence_chain_conflict")
            if fault_hook:
                fault_hook("after_retention_state")
        if question:
            _decorate_task(question, student_id=student_id, session_id=session_id, task_role="retention",
                retrieval_evidence_key=state["retrieval_evidence_key"], due_at=state["retention_due_at"])
            if existing is not None:
                existing.clear(); existing.update(question)
            else:
                additions.append(question)
        else:
            blocked.append({"knowledge_tag": tag, "available_at": state["retention_due_at"], "reason_code": "independent_review_content_missing"})
    return [*additions, *tasks], blocked, bool(additions or tasks != before)
