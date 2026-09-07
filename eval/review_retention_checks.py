"""Same retention transactions exercised on SQLite and real PostgreSQL."""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import text
from db.engine import get_connection
from services import review_service as review
from services.weakpoint_service import record_weakpoint

NOW = "2030-01-01T03:00:00Z"
DUE = "2030-01-02T03:00:00Z"
DAY = "2030-01-01"


def check_retention_transactions():
    student = "retention-atomic-" + uuid4().hex
    tag = "戊戌变法失败原因"
    record_weakpoint(student, tag, source="test")
    session = review.create_today_session(student, DAY, at=NOW)
    answer = review.submit_answer(student, DAY, 0, session["tasks"][0]["answer"], session["revision"], "retention-retrieval", occurred_at=NOW)
    advanced = review.advance_after_feedback(student, DAY, 0, answer["session_revision"], "retention-feedback")
    session = review.get_today_session(student, DAY, at=NOW)
    index = advanced["task_index"]
    review.submit_answer(student, DAY, index, session["tasks"][index]["answer"], session["revision"], "retention-verify", occurred_at=NOW)
    def snapshot():
        with get_connection() as conn:
            state = dict(conn.execute(text("SELECT * FROM review_mastery_state WHERE student_id=:s"), {"s": student}).mappings().one())
            sessions = [dict(r) for r in conn.execute(text("SELECT * FROM review_sessions WHERE student_id=:s ORDER BY date"), {"s": student}).mappings()]
            evidence = [dict(r) for r in conn.execute(text("SELECT * FROM weakpoint_evidence WHERE student_id=:s ORDER BY evidence_key"), {"s": student}).mappings()]
        return state, sessions, evidence
    initial = snapshot()
    def fail(point):
        if point in {"after_retention_state", "after_retention_session", "after_mastery_state"}:
            raise RuntimeError("injected_retention_failure")
    for missing in (True, False):
        context = patch("services.review_retention.role_question", return_value=None) if missing else patch("services.review_retention.is_due", wraps=review.is_due)
        with context:
            try:
                review.get_today_session(student, DAY, at=DUE, fault_hook=fail)
            except RuntimeError as exc:
                assert str(exc) == "injected_retention_failure"
            else:
                raise AssertionError("failure hook not reached")
        assert snapshot() == initial, "retention maintenance did not roll back"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: review.get_today_session(student, DAY, at=DUE), range(2)))
    assert results[0]["revision"] == results[1]["revision"]
    session = results[-1]
    tasks = [t for t in session["tasks"] if t.get("task_role") == "retention"]
    assert len(tasks) == 1
    before_submit = snapshot()
    index = next(i for i,t in enumerate(session["tasks"]) if t.get("task_role") == "retention")
    try:
        review.submit_answer(student, DAY, index, tasks[0]["answer"], session["revision"], "retention-rollback", occurred_at=DUE, fault_hook=fail)
    except RuntimeError:
        pass
    else:
        raise AssertionError("submission failure hook not reached")
    assert snapshot() == before_submit
    # A different day may publish the same pending chain; it still cannot score twice.
    next_day = review.create_today_session(student, "2030-01-02", at=DUE)
    next_index = next(i for i,t in enumerate(next_day["tasks"]) if t.get("task_role") == "retention")
    submitted = review.submit_answer(student, DAY, index, tasks[0]["answer"], session["revision"], "retention-success", occurred_at=DUE)
    assert submitted["phase"] == "retention_verified"
    replay = review.submit_answer(student, DAY, index, tasks[0]["answer"], session["revision"], "retention-success", occurred_at=DUE)
    assert replay["replayed"]
    try:
        review.submit_answer(student, "2030-01-02", next_index, next_day["tasks"][next_index]["answer"], next_day["revision"], "retention-duplicate-day", occurred_at=DUE)
    except review.ReviewConflictError:
        pass
    else:
        raise AssertionError("cross-day evidence counted twice")
    assert len([e for e in snapshot()[2] if e["evidence_type"] == "retention_correct"]) == 1
    print("OK retention_atomic_rollback_concurrency_cross_day_and_replay")
