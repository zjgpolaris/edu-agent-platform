"""Deterministic v1.38 gate for independent review mastery evidence."""
from __future__ import annotations

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-review-mastery-v138.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from db.engine import get_connection
from services.review_service import (
    ReviewConflictError,
    advance_after_feedback,
    create_today_session,
    get_today_session,
    public_review_session,
    submit_answer,
)
from services.weakpoint_service import get_weakpoints, record_weakpoint
from services.tutor_effectiveness_service import get_student_tutor_effectiveness

TODAY = "2026-08-25"
NOW = "2026-08-25T02:00:00Z"


def weakpoint_exists(student_id: str, tag: str) -> bool:
    return any(item["knowledge_tag"] == tag for item in get_weakpoints(student_id))


def run_mastery_chain() -> None:
    student = "v138-chain"
    tag = "戊戌变法失败原因"
    record_weakpoint(student, tag, source="assignment")
    session = create_today_session(student, TODAY)
    retrieval = session["tasks"][0]
    safe = public_review_session(session)
    assert safe["tasks"][0]["task_role"] == "retrieval", safe
    assert "answer" not in safe["tasks"][0] and "material" not in safe["tasks"][0], safe

    retrieval_result = submit_answer(
        student, TODAY, 0, retrieval["answer"], 0, "v138-retrieval-submit", occurred_at=NOW,
    )
    assert retrieval_result["phase"] == "awaiting_feedback", retrieval_result
    assert retrieval_result["task"].get("material"), retrieval_result
    assert weakpoint_exists(student, tag), "retrieval correct must not remove weakpoint"
    refreshed = get_today_session(student, TODAY, at=NOW)
    assert refreshed
    refreshed_public = public_review_session(refreshed)
    assert refreshed_public["tasks"][0]["phase"] == "awaiting_feedback", refreshed_public
    assert refreshed_public["tasks"][0].get("material"), "feedback must survive refresh"
    replay = submit_answer(
        student, TODAY, 0, retrieval["answer"], 0, "v138-retrieval-submit", occurred_at=NOW,
    )
    assert replay["replayed"] is True and replay["session_revision"] == 1, replay

    advanced = advance_after_feedback(student, TODAY, 0, 1, "v138-feedback-advance")
    verification = advanced["task"]
    assert advanced["phase"] == "verification_pending", advanced
    assert verification["question_id"] != retrieval["question_id"], (retrieval, verification)
    assert "material" not in verification and "answer" not in verification, verification
    advance_replay = advance_after_feedback(student, TODAY, 0, 1, "v138-feedback-advance")
    assert advance_replay["replayed"] is True and advance_replay["task_index"] == 1, advance_replay

    internal = get_today_session(student, TODAY)
    assert internal
    verification_internal = internal["tasks"][1]
    verified = submit_answer(
        student, TODAY, 1, verification_internal["answer"], 2, "v138-verification-submit", occurred_at=NOW,
    )
    assert verified["phase"] == "retention_scheduled", verified
    assert verified["mastery"]["status"] == "not_yet_retained", verified
    assert weakpoint_exists(student, tag), "verification correct must not remove weakpoint"

    due_at = str(verified["available_at"])
    after_due = (datetime.fromisoformat(due_at.replace("Z", "+00:00")) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    due_session = get_today_session(student, TODAY, at=after_due)
    assert due_session
    retention_index = next(
        index for index, task in enumerate(due_session["tasks"]) if task.get("task_role") == "retention"
    )
    retention = due_session["tasks"][retention_index]
    prior_ids = {retrieval["question_id"], verification_internal["question_id"]}
    assert retention["question_id"] not in prior_ids, retention

    try:
        submit_answer(
            student,
            TODAY,
            retention_index,
            retention["answer"],
            due_session["revision"],
            "v138-retention-early",
            occurred_at=NOW,
        )
    except ReviewConflictError as exc:
        assert exc.code == "retention_not_due", exc.code
    else:
        raise AssertionError("early retention must be rejected")

    retained = submit_answer(
        student,
        TODAY,
        retention_index,
        retention["answer"],
        due_session["revision"],
        "v138-retention-submit",
        occurred_at=after_due,
    )
    assert retained["phase"] == "retention_verified", retained
    assert not weakpoint_exists(student, tag), "only retained mastery may remove weakpoint"
    with get_connection() as conn:
        evidence = conn.execute(text("""SELECT evidence_type, evidence_stage, assessment_id,
            assessment_fingerprint FROM weakpoint_evidence WHERE student_id=:sid ORDER BY occurred_at"""),
            {"sid": student}).mappings().all()
        state = conn.execute(text("SELECT * FROM review_mastery_state WHERE student_id=:sid AND knowledge_tag=:tag"),
            {"sid": student, "tag": tag}).mappings().one()
    assert [row["evidence_type"] for row in evidence] == [
        "retrieval_correct", "independent_correct", "retention_correct",
    ], evidence
    assert len({row["assessment_id"] for row in evidence}) == 3, evidence
    assert len({row["assessment_fingerprint"] for row in evidence}) == 3, evidence
    assert state["status"] == "retention_verified", state
    metrics = get_student_tutor_effectiveness(student)["summary"]
    assert metrics["review_retrieval_attempts"] == 1 and metrics["review_retrieval_accuracy"] == 100.0, metrics
    assert metrics["review_verification_attempts"] == 1 and metrics["review_verification_accuracy"] == 100.0, metrics
    assert metrics["review_retention_attempts"] == 1 and metrics["review_retention_accuracy"] == 100.0, metrics
    assert metrics["delayed_retention_status"] == "NOT_RUN", metrics


def run_wrong_and_rollback_cases() -> None:
    student = "v138-wrong"
    tag = "洋务运动目的"
    record_weakpoint(student, tag, source="assignment")
    session = create_today_session(student, TODAY)
    retrieval = session["tasks"][0]
    wrong = next(letter for letter in "ABCD" if letter != retrieval["answer"])
    submit_answer(student, TODAY, 0, wrong, 0, "v138-wrong-retrieval", occurred_at=NOW)
    advanced = advance_after_feedback(student, TODAY, 0, 1, "v138-wrong-advance")
    internal = get_today_session(student, TODAY)
    assert internal
    verification = internal["tasks"][advanced["task_index"]]
    wrong_verification = next(letter for letter in "ABCD" if letter != verification["answer"])
    result = submit_answer(
        student, TODAY, advanced["task_index"], wrong_verification, 2, "v138-wrong-verification", occurred_at=NOW,
    )
    assert result["phase"] == "needs_support" and weakpoint_exists(student, tag), result

    rollback_student = "v138-rollback"
    rollback_tag = "赤壁之战的影响"
    record_weakpoint(rollback_student, rollback_tag, source="assignment")
    rollback_session = create_today_session(rollback_student, TODAY)
    rollback_task = rollback_session["tasks"][0]

    def fail_after_evidence(name: str) -> None:
        if name == "after_weakpoint_evidence":
            raise RuntimeError("injected failure")

    try:
        submit_answer(
            rollback_student,
            TODAY,
            0,
            rollback_task["answer"],
            0,
            "v138-rollback-submit",
            occurred_at=NOW,
            fault_hook=fail_after_evidence,
        )
    except RuntimeError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("fault injection must fail")
    with get_connection() as conn:
        evidence_count = conn.execute(
            text("SELECT COUNT(*) FROM weakpoint_evidence WHERE student_id=:sid"), {"sid": rollback_student}
        ).scalar_one()
        row = conn.execute(
            text("SELECT revision, completed FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": rollback_student, "date": TODAY},
        ).mappings().one()
    assert evidence_count == 0 and row["revision"] == 0 and row["completed"] == 0, (evidence_count, row)


def run_concurrency_case() -> None:
    student = "v138-concurrent"
    tag = "鸦片战争的影响"
    record_weakpoint(student, tag, source="assignment")
    session = create_today_session(student, TODAY)
    task = session["tasks"][0]

    def submit() -> dict:
        return submit_answer(
            student,
            TODAY,
            0,
            task["answer"],
            0,
            "v138-concurrent-submit",
            occurred_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sum(bool(result.get("replayed")) for result in results) == 1, results
    assert {result["session_revision"] for result in results} == {1}, results
    with get_connection() as conn:
        evidence_count = conn.execute(
            text("SELECT COUNT(*) FROM weakpoint_evidence WHERE student_id=:sid"), {"sid": student}
        ).scalar_one()
        event_count = conn.execute(
            text("SELECT COUNT(*) FROM learning_events WHERE student_id=:sid"), {"sid": student}
        ).scalar_one()
    assert evidence_count == 1 and event_count == 1, (evidence_count, event_count)

    def advance() -> dict:
        return advance_after_feedback(student, TODAY, 0, 1, "v138-concurrent-advance")

    with ThreadPoolExecutor(max_workers=2) as pool:
        advances = list(pool.map(lambda _: advance(), range(2)))
    assert sum(bool(result.get("replayed")) for result in advances) == 1, advances
    persisted = get_today_session(student, TODAY)
    assert persisted and persisted["revision"] == 2, persisted
    assert len([task for task in persisted["tasks"] if task.get("task_role") == "verification"]) == 1, persisted


if __name__ == "__main__":
    run_mastery_chain()
    print("OK independent_mastery_chain")
    run_wrong_and_rollback_cases()
    print("OK wrong_and_transaction_rollback")
    run_concurrency_case()
    print("OK concurrent_same_key")
    print("review_mastery_evidence_eval=3/3")
