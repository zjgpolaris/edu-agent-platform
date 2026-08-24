"""AutoTutor answer effects are durable and applied exactly once."""
from __future__ import annotations

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-transition-idempotency.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE"] = "enforce"
os.environ["EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS"] = "10000"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents.auto_tutor import (  # noqa: E402
    AutoTutorIdempotencyConflict,
    _load_persisted_session,
    start_session,
    submit_answer,
)
from db.engine import get_connection  # noqa: E402
from services.weakpoint_service import record_weakpoint  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _correct_answer(session_id: str) -> str:
    state = _load_persisted_session(session_id)
    assert state is not None
    if state.phase == "exit_ticket":
        return str(state.exit_ticket.question["answer"])
    return str(state.lesson_plan[state.current_step_index].question["answer"])


def _counts(session_id: str, student_id: str) -> tuple[int, int, int, int]:
    with get_connection() as conn:
        events = int(conn.execute(
            text("SELECT COUNT(*) FROM learning_events WHERE session_id=:session_id"),
            {"session_id": session_id},
        ).scalar() or 0)
        duplicate_effects = int(conn.execute(text("""SELECT COUNT(*) FROM (
            SELECT effect_key FROM learning_events
            WHERE session_id=:session_id AND effect_key IS NOT NULL
            GROUP BY effect_key HAVING COUNT(*) > 1
        ) duplicates"""), {"session_id": session_id}).scalar() or 0)
        evidence = int(conn.execute(
            text("SELECT COUNT(*) FROM weakpoint_evidence WHERE source_session_id=:session_id"),
            {"session_id": session_id},
        ).scalar() or 0)
        memories = int(conn.execute(
            text("SELECT COUNT(*) FROM memory_entries WHERE student_id=:student_id AND type='review_goal'"),
            {"student_id": student_id},
        ).scalar() or 0)
    return events, duplicate_effects, evidence, memories


def _assert_concurrent_same_key() -> None:
    student_id = "transition-concurrent-student"
    started = start_session(student_id, grade="八年级上册", focus_tags=["洋务运动目的"])
    session_id = started["session_id"]
    answer = _correct_answer(session_id)

    def submit() -> dict:
        return submit_answer(
            session_id,
            answer,
            expected_revision=started["revision"],
            idempotency_key="transition-concurrent-practice-key",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert all(result["revision"] == started["revision"] + 1 for result in results)
    assert sum(bool(result.get("idempotent_replay")) for result in results) == 1
    events, duplicate_effects, evidence, memories = _counts(session_id, student_id)
    assert events > 0
    assert duplicate_effects == 0
    assert evidence == 0
    assert memories == 0


def main() -> None:
    student_id = "transition-student"
    tag = "洋务运动目的"
    record_weakpoint(student_id, tag, "eval_seed")
    started = start_session(student_id, grade="八年级上册", focus_tags=[tag])
    session_id = started["session_id"]
    practice = submit_answer(
        session_id,
        _correct_answer(session_id),
        expected_revision=started["revision"],
        idempotency_key="transition-practice-key",
    )
    assert practice["phase"] == "exit_ticket"
    exit_revision = practice["revision"]
    exit_answer = _correct_answer(session_id)
    completed = submit_answer(
        session_id,
        exit_answer,
        expected_revision=exit_revision,
        idempotency_key="transition-exit-key",
    )
    assert completed["status"] == "completed"
    before = _counts(session_id, student_id)
    assert before[1] == 0
    assert before[2] == 1
    assert before[3] == 1

    replay = submit_answer(
        session_id,
        exit_answer,
        expected_revision=exit_revision,
        idempotency_key="transition-exit-key",
    )
    assert replay["idempotent_replay"] is True
    assert replay["revision"] == completed["revision"]
    assert _counts(session_id, student_id) == before

    conflicting = next(letter for letter in "ABCD" if letter != exit_answer)
    try:
        submit_answer(
            session_id,
            conflicting,
            expected_revision=exit_revision,
            idempotency_key="transition-exit-key",
        )
    except AutoTutorIdempotencyConflict:
        pass
    else:
        raise AssertionError("same idempotency key with another answer was accepted")
    assert _counts(session_id, student_id) == before
    _assert_concurrent_same_key()
    print("autotutor_transition_idempotency_smoke=PASS")


if __name__ == "__main__":
    main()
