"""Fault injection proves AutoTutor transition effects roll back together."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-autotutor-fault-injection.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from agents.auto_tutor import (  # noqa: E402
    _answer_request_hash,
    _claim_answer_transition,
    _load_persisted_session,
    _release_answer_transition,
    start_session,
)
from db.engine import get_connection  # noqa: E402
from services.autotutor_transition_service import (  # noqa: E402
    AutoTutorTransitionEffects,
    LearningEventIntent,
    WeakpointEvidenceIntent,
    commit_autotutor_transition,
)
from student_profile import LearningEvent, MemoryEntryUpsert  # noqa: E402
from sqlalchemy import text  # noqa: E402


FAULT_POINTS = [
    "after_learning_event",
    "after_weakpoint_evidence",
    "after_review_memory",
    "before_session_cas",
    "after_session_cas",
]


def _count(effect_key: str, evidence_key: str, student_id: str) -> tuple[int, int, int]:
    with get_connection() as conn:
        events = int(conn.execute(
            text("SELECT COUNT(*) FROM learning_events WHERE effect_key=:key"), {"key": effect_key}
        ).scalar() or 0)
        evidence = int(conn.execute(
            text("SELECT COUNT(*) FROM weakpoint_evidence WHERE evidence_key=:key"), {"key": evidence_key}
        ).scalar() or 0)
        memory = int(conn.execute(
            text("SELECT COUNT(*) FROM memory_entries WHERE student_id=:student_id AND type='review_goal'"),
            {"student_id": student_id},
        ).scalar() or 0)
    return events, evidence, memory


def main() -> None:
    for index, fault_point in enumerate(FAULT_POINTS):
        student_id = f"fault-student-{index}"
        started = start_session(student_id, grade="八年级上册", focus_tags=["洋务运动目的"])
        session_id = started["session_id"]
        revision = started["revision"]
        key = f"fault-transition-{index}"
        request_hash = _answer_request_hash(session_id, revision, "B")
        status, claimed = _claim_answer_transition(session_id, revision, key, request_hash)
        assert status == "claimed" and claimed is not None
        claimed.revision = revision + 1
        effect_key = f"autotutor:{session_id}:revision:{revision}:fault:event"
        evidence_key = f"autotutor:{session_id}:revision:{revision}:fault:evidence"
        effects = AutoTutorTransitionEffects(
            session_id=session_id,
            claimed_revision=revision,
            idempotency_key=key,
            learning_events=[LearningEventIntent(
                effect_key=effect_key,
                event=LearningEvent(
                    student_id=student_id,
                    session_id=session_id,
                    feature="auto_tutor",
                    event_type="auto_tutor_fault_probe",
                    topic="fault-probe",
                    success=False,
                ),
            )],
            weakpoint_evidence=[WeakpointEvidenceIntent(
                evidence_key=evidence_key,
                student_id=student_id,
                knowledge_tag="fault-probe",
                evidence_type="wrong",
                source_session_id=session_id,
                assessment_id="fault-assessment",
            )],
            review_memory=MemoryEntryUpsert(
                student_id=student_id,
                type="review_goal",
                content={"session_id": session_id, "fault_probe": True},
                source_feature="auto_tutor",
            ),
        )

        def fail_at(name: str) -> None:
            if name == fault_point or name.startswith(f"{fault_point}:"):
                raise RuntimeError(f"injected:{fault_point}")

        try:
            commit_autotutor_transition(
                previous_revision=revision,
                idempotency_key=key,
                request_hash=request_hash,
                next_state=claimed,
                response={"session_id": session_id, "revision": revision + 1},
                effects=effects,
                fault_hook=fail_at,
            )
        except RuntimeError as exc:
            assert str(exc).startswith("injected:")
        else:
            raise AssertionError(f"fault point {fault_point} was not triggered")
        _release_answer_transition(
            session_id,
            expected_revision=revision,
            idempotency_key=key,
            request_hash=request_hash,
        )
        assert _count(effect_key, evidence_key, student_id) == (0, 0, 0)
        restored = _load_persisted_session(session_id)
        assert restored is not None and restored.revision == revision

        status, claimed = _claim_answer_transition(session_id, revision, key, request_hash)
        assert status == "claimed" and claimed is not None
        claimed.revision = revision + 1
        result = commit_autotutor_transition(
            previous_revision=revision,
            idempotency_key=key,
            request_hash=request_hash,
            next_state=claimed,
            response={"session_id": session_id, "revision": revision + 1},
            effects=effects,
        )
        assert result.status == "committed"
        assert _count(effect_key, evidence_key, student_id) == (1, 1, 1)
        print("OK", fault_point)
    print(f"autotutor_finalize_fault_injection={len(FAULT_POINTS)}/{len(FAULT_POINTS)}")


if __name__ == "__main__":
    main()
