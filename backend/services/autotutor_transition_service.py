"""Atomic persistence boundary for one AutoTutor answer transition."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from db.engine import get_connection
from services.weakpoint_service import apply_weakpoint_evidence_with_connection
from services.review_mastery_service import add_retention_interval, set_mastery_state_with_connection
from student_profile import (
    LearningEvent,
    MemoryEntryUpsert,
    init_db,
    now_iso,
    record_learning_event_with_connection,
    upsert_memory_entry_with_connection,
)


class LearningEventIntent(BaseModel):
    effect_key: str = Field(min_length=8, max_length=320)
    event: LearningEvent


class WeakpointEvidenceIntent(BaseModel):
    evidence_key: str = Field(min_length=8, max_length=320)
    student_id: str
    knowledge_tag: str
    evidence_type: Literal["wrong", "retrieval_correct", "independent_correct", "retention_correct"]
    source_feature: Literal["auto_tutor"] = "auto_tutor"
    source_session_id: str
    assessment_id: str | None = None
    evidence_stage: Literal["retrieval", "verification", "retention"] | None = None
    assessment_fingerprint: str | None = None
    parent_evidence_key: str | None = None


class AutoTutorTransitionEffects(BaseModel):
    contract_version: Literal[2] = 2
    session_id: str
    claimed_revision: int
    idempotency_key: str
    learning_events: list[LearningEventIntent] = Field(default_factory=list)
    weakpoint_evidence: list[WeakpointEvidenceIntent] = Field(default_factory=list)
    review_memory: MemoryEntryUpsert | None = None
    runtime_run_id: str | None = None
    runtime_finalize_key: str | None = None


class TransitionCommitResult(BaseModel):
    status: Literal["committed", "replayed", "stale", "conflict"]
    response: dict[str, Any] | None = None


class AutoTutorTransitionConflict(RuntimeError):
    pass


def commit_autotutor_start(
    *,
    next_state: Any,
    response: dict[str, Any],
    start_idempotency_key: str | None,
    effects: AutoTutorTransitionEffects,
    fault_hook: Callable[[str], None] | None = None,
) -> None:
    """Insert a new session and its start effects in one transaction."""
    init_db()
    if effects.session_id != next_state.session_id:
        raise ValueError("start effects do not match session")
    if effects.weakpoint_evidence or effects.review_memory is not None:
        raise ValueError("start transition cannot emit mastery effects")
    if any(intent.event.student_id != next_state.student_id for intent in effects.learning_events):
        raise ValueError("learning event owner does not match AutoTutor session")

    def checkpoint(name: str) -> None:
        if fault_hook is not None:
            fault_hook(name)

    next_state.updated_at = time.time()
    payload = next_state.model_dump()
    with get_connection() as conn:
        for intent in effects.learning_events:
            record_learning_event_with_connection(conn, intent.event, effect_key=intent.effect_key)
            checkpoint(f"after_learning_event:{intent.effect_key}")
        checkpoint("before_session_insert")
        conn.execute(
            text("""INSERT INTO autotutor_sessions (
                session_id, student_id, trace_id, run_id, status, revision, state_json,
                start_idempotency_key, last_response_json, created_at, updated_at
            ) VALUES (
                :session_id, :student_id, :trace_id, :run_id, :status, :revision, :state_json,
                :start_idempotency_key, :last_response_json, :created_at, :updated_at
            )"""),
            {
                "session_id": next_state.session_id,
                "student_id": next_state.student_id,
                "trace_id": next_state.trace_id,
                "run_id": next_state.run_id,
                "status": next_state.status,
                "revision": next_state.revision,
                "state_json": json.dumps(payload, ensure_ascii=False),
                "start_idempotency_key": start_idempotency_key,
                "last_response_json": json.dumps(response, ensure_ascii=False),
                "created_at": next_state.created_at,
                "updated_at": next_state.updated_at,
            },
        )
        checkpoint("after_session_insert")


def commit_autotutor_transition(
    *,
    previous_revision: int,
    idempotency_key: str,
    request_hash: str,
    next_state: Any,
    response: dict[str, Any],
    effects: AutoTutorTransitionEffects,
    fault_hook: Callable[[str], None] | None = None,
) -> TransitionCommitResult:
    """Commit all business effects and the session CAS in one DB transaction."""
    init_db()
    if effects.session_id != next_state.session_id or effects.claimed_revision != previous_revision:
        raise ValueError("transition effects do not match session revision")
    if effects.idempotency_key != idempotency_key:
        raise ValueError("transition effects do not match idempotency key")
    if any(intent.event.student_id != next_state.student_id for intent in effects.learning_events):
        raise ValueError("learning event owner does not match AutoTutor session")
    if any(intent.student_id != next_state.student_id for intent in effects.weakpoint_evidence):
        raise ValueError("weakpoint evidence owner does not match AutoTutor session")
    if effects.review_memory is not None and effects.review_memory.student_id != next_state.student_id:
        raise ValueError("review memory owner does not match AutoTutor session")

    def checkpoint(name: str) -> None:
        if fault_hook is not None:
            fault_hook(name)

    with get_connection() as conn:
        row = conn.execute(
            text("""SELECT revision, inflight_idempotency_key, inflight_request_hash,
                last_idempotency_key, last_request_hash, last_response_json
                FROM autotutor_sessions WHERE session_id=:session_id"""),
            {"session_id": next_state.session_id},
        ).mappings().first()
        if not row:
            raise LookupError("autotutor session not found")
        if row.get("last_idempotency_key") == idempotency_key:
            if row.get("last_request_hash") != request_hash:
                return TransitionCommitResult(status="conflict")
            saved = json.loads(row["last_response_json"]) if row.get("last_response_json") else response
            return TransitionCommitResult(status="replayed", response=saved)
        if int(row.get("revision") or 0) != previous_revision:
            return TransitionCommitResult(status="stale")
        if row.get("inflight_idempotency_key") != idempotency_key:
            return TransitionCommitResult(status="conflict")
        if row.get("inflight_request_hash") != request_hash:
            return TransitionCommitResult(status="conflict")

        checkpoint("before_learning_events")
        for intent in effects.learning_events:
            record_learning_event_with_connection(
                conn,
                intent.event,
                effect_key=intent.effect_key,
            )
            checkpoint(f"after_learning_event:{intent.effect_key}")

        for intent in effects.weakpoint_evidence:
            occurred_at = now_iso()
            apply_weakpoint_evidence_with_connection(
                conn,
                evidence_key=intent.evidence_key,
                student_id=intent.student_id,
                knowledge_tag=intent.knowledge_tag,
                evidence_type=intent.evidence_type,
                source_feature=intent.source_feature,
                source_session_id=intent.source_session_id,
                assessment_id=intent.assessment_id,
                evidence_stage=intent.evidence_stage,
                assessment_fingerprint=intent.assessment_fingerprint,
                parent_evidence_key=intent.parent_evidence_key,
                occurred_at=occurred_at,
            )
            if intent.evidence_type == "independent_correct" and intent.parent_evidence_key:
                set_mastery_state_with_connection(
                    conn,
                    student_id=intent.student_id,
                    knowledge_tag=intent.knowledge_tag,
                    status="retention_due",
                    retrieval_evidence_key=intent.parent_evidence_key,
                    verification_evidence_key=intent.evidence_key,
                    retention_due_at=add_retention_interval(occurred_at),
                    updated_at=occurred_at,
                )
            checkpoint(f"after_weakpoint_evidence:{intent.evidence_key}")

        if effects.review_memory is not None:
            upsert_memory_entry_with_connection(conn, effects.review_memory)
            checkpoint("after_review_memory")

        if effects.runtime_run_id and effects.runtime_finalize_key:
            side_effect_id = "sfx_" + hashlib.sha256(
                f"{effects.runtime_run_id}:{effects.runtime_finalize_key}".encode("utf-8")
            ).hexdigest()[:32]
            timestamp = now_iso()
            conn.execute(
                text("""INSERT INTO agent_side_effects (
                    side_effect_id, run_id, step_id, operation, idempotency_key,
                    status, resource_ref, result_json, error_json, created_at, updated_at
                ) VALUES (
                    :side_effect_id, :run_id, 'finalize', 'auto_tutor.finalize', :idempotency_key,
                    'committed', :resource_ref, :result_json, NULL, :created_at, :updated_at
                ) ON CONFLICT(run_id, idempotency_key) DO NOTHING"""),
                {
                    "side_effect_id": side_effect_id,
                    "run_id": effects.runtime_run_id,
                    "idempotency_key": effects.runtime_finalize_key,
                    "resource_ref": f"autotutor_session:{next_state.session_id}",
                    "result_json": json.dumps(
                        {
                            "business_effect_keys": [
                                *[item.effect_key for item in effects.learning_events],
                                *[item.evidence_key for item in effects.weakpoint_evidence],
                            ],
                            "review_memory": effects.review_memory is not None,
                        },
                        ensure_ascii=False,
                    ),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            checkpoint("after_runtime_side_effect")

        next_state.updated_at = time.time()
        payload = next_state.model_dump()
        checkpoint("before_session_cas")
        updated = conn.execute(
            text("""UPDATE autotutor_sessions SET
                student_id=:student_id, trace_id=:trace_id, run_id=:run_id, status=:status,
                revision=revision+1, state_json=:state_json,
                inflight_idempotency_key=NULL, inflight_request_hash=NULL,
                last_idempotency_key=:idempotency_key, last_request_hash=:request_hash,
                last_response_json=:last_response_json, updated_at=:updated_at
                WHERE session_id=:session_id AND revision=:expected_revision
                  AND inflight_idempotency_key=:idempotency_key
                  AND inflight_request_hash=:request_hash"""),
            {
                "student_id": next_state.student_id,
                "trace_id": next_state.trace_id,
                "run_id": next_state.run_id,
                "status": next_state.status,
                "state_json": json.dumps(payload, ensure_ascii=False),
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "last_response_json": json.dumps(response, ensure_ascii=False),
                "updated_at": next_state.updated_at,
                "session_id": next_state.session_id,
                "expected_revision": previous_revision,
            },
        )
        if updated.rowcount != 1:
            raise AutoTutorTransitionConflict("autotutor session CAS failed")
        checkpoint("after_session_cas")
    return TransitionCommitResult(status="committed", response=response)
