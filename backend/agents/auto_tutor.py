"""AutoTutor —— 自主辅导 Agent 闭环。

给定一个学生，agent 自己决定教什么、怎么教、答错了怎么补：

    plan ──> act ──> observe ──> judge ──┬── pass ──> next_step ──> ... ──> finalize
                                         └── fail ──> reflect ──> re_plan ──> act

与普通固定流水线的差异点在 reflect / re_plan：学生答错时，agent 反思"是讲得不对，
还是题超纲"，并真实地修改后续计划（补讲 / 降难度 / 换例子）。全过程 emit trace step，
课后自动落 memory + 记录错题（接已有 SM-2 复习基建）。

本模块只编排已有零件，不新增工具：
- 学生画像 / 错题本：student_profile + services.weakpoint_service
- 取材：tools.registry.run_tool("search_history_knowledge")（走工具治理 + 审计 + RAG）
- 课后记忆 / 复习：user_memory + services.weakpoint_service（错题进 SM-2 复习池）
"""
from __future__ import annotations

import json
import hashlib
import threading
import time
from time import perf_counter
from typing import Any, Iterator, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, PrivateAttr
from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection
from llm_config import llm_quality
from structured_output import StructuredInvocationProvenance, invoke_structured_with_provenance
from student_profile import LearningEvent, MemoryEntryUpsert, get_student_profile, try_record_learning_event
from services.autotutor_transition_service import (
    AutoTutorTransitionEffects,
    LearningEventIntent,
    WeakpointEvidenceIntent,
    commit_autotutor_start,
    commit_autotutor_transition,
)
from services.weakpoint_service import get_weakpoints
from tools.base import ToolExecutionContext
from tools.registry import run_tool
from trace_store import current_trace_id, emit_trace_event, set_trace_id
from agents.autotutor_content import (
    AssessmentItem,
    ContentGateSettings,
    ContentValidation,
    LearningObjective,
    TeachingEvidenceDecision,
    answer_feedback as build_answer_feedback,
    assessment_fingerprint,
    assessment_to_question,
    build_learning_objective,
    prepare_content,
    verified_mastery,
)
from agents.autotutor_public import (
    AutoTutorAssistantContextPublic,
    AutoTutorAssistantHandoff,
    PublicTeachingContext,
)
from agents.autotutor_provenance import public_decision_provenance
from agents.autotutor_domain import judge_answer, replan_policy
from agents.autotutor_execution import (
    AutoTutorExecutionContext,
    AutoTutorExecutorSettings,
    AutoTutorTransitionOutcome,
    GraphActiveTransitionExecutor,
    LegacyTransitionExecutor,
    compare_transition_outcomes,
    select_executor,
)
from agents.autotutor_observations import DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER

AGENT_NAME = "auto_tutor"


class AutoTutorUnavailableError(RuntimeError):
    """Raised when the content-safety kill switch blocks new sessions."""


class AutoTutorIdempotencyConflict(RuntimeError):
    """Raised when one idempotency key is reused for a different answer."""


# 防死循环 / 防失控护栏
MAX_STEPS = 2
MAX_REPLANS = 3
MAX_ATTEMPTS_PER_STEP = 3

Difficulty = Literal["easy", "medium", "hard"]
AdjustmentAction = Literal["reteach", "lower_difficulty", "change_example", "advance"]
SessionStatus = Literal["awaiting_answer", "needs_content", "completed"]
SessionPhase = Literal["lesson", "exit_ticket", "content_blocked", "completed"]


# --------------------------------------------------------------------------- #
# 状态对象
# --------------------------------------------------------------------------- #
class LessonStep(BaseModel):
    knowledge_point: str
    source_tag: str | None = None  # 对应错题本中的原始知识点标签（用于课后增删错题）
    difficulty: Difficulty = "medium"
    strategy: str = "讲解关键史实后用一道选择题检验。"
    tool: str = "search_history_knowledge"
    rationale: str = ""
    status: Literal["pending", "active", "practiced", "mastered", "struggling", "content_blocked"] = "pending"
    attempts: int = 0
    replanned: bool = False
    teaching: dict[str, Any] | None = None
    question: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    objective: LearningObjective | None = None
    evidence_decision: TeachingEvidenceDecision | None = None
    content_validation: ContentValidation | None = None
    content_version: str | None = None
    evidence_label: str | None = None
    practice_result: dict[str, Any] | None = None
    content_blocked: dict[str, Any] | None = None
    assessment_history: list[str] = Field(default_factory=list)


class RuntimeStep(BaseModel):
    trace_id: str | None = None
    agent_name: str = AGENT_NAME
    step_id: str
    step_name: str
    sequence: int
    event_type: str
    status: str = "success"
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class ReflectionRecord(BaseModel):
    step_index: int
    knowledge_point: str
    diagnosis: str
    adjustment: AdjustmentAction
    explanation: str
    decision_provenance: dict[str, Any] | None = None


class ExitTicket(BaseModel):
    knowledge_point: str
    source_tag: str | None = None
    difficulty: Difficulty = "medium"
    strategy: str = "课后退出票检验"
    question: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    generated_from: Literal["struggling_step", "replanned_step", "mastered_step", "fallback"] = "fallback"
    objective: LearningObjective | None = None
    content_validation: ContentValidation | None = None
    content_version: str | None = None
    evidence_label: str | None = None


class ExitTicketResult(BaseModel):
    knowledge_point: str
    source_tag: str | None = None
    selected_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str = ""
    mastery_signal: Literal["exit_ticket_passed", "exit_ticket_failed"]
    assessment_id: str | None = None
    objective_id: str | None = None
    content_validation_status: str | None = None
    verified_mastery: bool = False


class EvidenceSummary(BaseModel):
    exit_ticket_recorded: bool = False
    learning_event_types: list[str] = Field(default_factory=list)
    weakpoint_action: str = "not_recorded"
    review_action: str = "not_scheduled"
    tutor_effectiveness_ready: bool = False
    verified_mastery: bool = False
    content_validation_status: str | None = None


class AutoTutorState(BaseModel):
    session_id: str
    run_id: str | None = None
    trace_id: str
    student_id: str
    grade: str | None = None
    lesson_id: str | None = None
    max_minutes: int = 12
    lesson_plan: list[LessonStep] = Field(default_factory=list)
    current_step_index: int = 0
    step_history: list[dict[str, Any]] = Field(default_factory=list)
    reflect_log: list[ReflectionRecord] = Field(default_factory=list)
    replans: int = 0
    mastery_delta: dict[str, float] = Field(default_factory=dict)
    runtime_steps: list[RuntimeStep] = Field(default_factory=list)
    status: SessionStatus = "awaiting_answer"
    phase: SessionPhase = "lesson"
    exit_ticket: ExitTicket | None = None
    exit_ticket_result: ExitTicketResult | None = None
    evidence: EvidenceSummary | None = None
    summary: str | None = None
    content_gate_mode: Literal["off", "shadow", "enforce"] = "off"
    content_blocked: dict[str, Any] | None = None
    answer_feedback: dict[str, Any] | None = None
    verified_mastery: bool = False
    legacy_unverified: bool = False
    transition_contract_version: Literal[2] = 2
    executor_contract_version: Literal[3] = 3
    executor_mode: Literal["legacy", "graph_active"] = "legacy"
    executor_assigned_mode: Literal["legacy", "graph_active"] | None = None
    executor_config_version: str | None = None
    executor_bucket: int | None = None
    executor_fallback_reason: str | None = None
    revision: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    _sequence: int = PrivateAttr(default=0)
    _transition_active: bool = PrivateAttr(default=False)
    _observation_capture: bool = PrivateAttr(default=False)
    _pending_learning_events: list[LearningEventIntent] = PrivateAttr(default_factory=list)
    _pending_weakpoint_evidence: list[WeakpointEvidenceIntent] = PrivateAttr(default_factory=list)
    _pending_review_memory: MemoryEntryUpsert | None = PrivateAttr(default=None)


def _execution_context(
    *,
    actor_id: str | None,
    actor_role: str | None,
    account_status: str,
    traffic_cohort: str,
    data_scope: str,
    rollout_eligible: bool,
    eligibility_reason: str,
    internal_force_graph: bool = False,
) -> AutoTutorExecutionContext:
    from deployment import deployed_commit, deployment_environment

    return AutoTutorExecutionContext(
        actor_id=actor_id,
        actor_role=actor_role,
        account_status=account_status,
        traffic_cohort=traffic_cohort,
        data_scope=data_scope,
        rollout_eligible=rollout_eligible,
        eligibility_reason=eligibility_reason,
        environment=deployment_environment(),
        deployed_commit=deployed_commit(),
        internal_force_graph=internal_force_graph,
    )


def _execute_selected_transition(
    before: AutoTutorState,
    *,
    transition_kind: Literal["start", "lesson_answer", "exit_ticket_answer", "recovery_resume"],
    command: dict[str, Any],
    context: AutoTutorExecutionContext,
    started_at: float,
) -> AutoTutorTransitionOutcome:
    """Acquire one observation bundle, compute both candidates, select one pre-commit."""
    effective_command = {**command, "transition_kind": transition_kind}
    provider_started = perf_counter()
    observations = DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER.prepare(
        before=before,
        command=effective_command,
        context=context,
    )
    provider_latency_ms = round((perf_counter() - provider_started) * 1000, 3)
    settings = AutoTutorExecutorSettings.from_env()
    legacy = LegacyTransitionExecutor()
    graph = GraphActiveTransitionExecutor()
    selected_executor = graph if before.executor_mode == "graph_active" else legacy
    comparator_executor = legacy if before.executor_mode == "graph_active" else graph
    selected_started = perf_counter()
    try:
        selected = selected_executor.execute(
            before=before,
            command=effective_command,
            observations=observations,
        )
    except Exception as exc:
        if before.executor_mode != "graph_active" or not settings.fallback_enabled:
            raise
        selected = legacy.execute(before=before, command=effective_command, observations=observations)
        reason = f"graph_precommit_fallback:{exc.__class__.__name__}"[:120]
        selected.next_state.executor_mode = "legacy"
        selected.next_state.executor_fallback_reason = reason
        selected.executor_mode = "legacy"
        selected.public_result = _public_state(selected.next_state)
        selected.diagnostics.comparator_matched = False
        selected.diagnostics.fallback_reason = reason
        selected.diagnostics.provider_latency_ms = provider_latency_ms
        selected.diagnostics.executor_latency_ms = round((perf_counter() - selected_started) * 1000, 3)
        return selected
    selected.diagnostics.provider_latency_ms = provider_latency_ms
    selected.diagnostics.executor_latency_ms = round((perf_counter() - selected_started) * 1000, 3)

    compare_required = before.executor_mode == "graph_active" or settings.mode == "shadow"
    if not compare_required:
        return selected
    comparator_started = perf_counter()
    try:
        comparator = comparator_executor.execute(
            before=before,
            command=effective_command,
            observations=observations,
        )
        matched, reasons = compare_transition_outcomes(selected, comparator)
    except Exception as exc:
        if before.executor_mode != "graph_active":
            selected.diagnostics.comparator_matched = False
            selected.diagnostics.fallback_reason = f"graph_shadow_failed:{exc.__class__.__name__}"[:120]
            try:
                from agents.autotutor_shadow import record_shadow_metric

                record_shadow_metric(
                    transition_kind=transition_kind,
                    matched=False,
                    duration_ms=(perf_counter() - comparator_started) * 1000,
                    reason_codes=["shadow_execution_failed"],
                )
            except Exception:
                pass
            return selected
        if not settings.fallback_enabled:
            raise
        comparator = legacy.execute(before=before, command=effective_command, observations=observations)
        matched, reasons = False, ("legacy_comparator_failed",)
    selected.diagnostics.comparator_latency_ms = round((perf_counter() - comparator_started) * 1000, 3)
    selected.diagnostics.comparator_matched = matched
    if before.executor_mode != "graph_active":
        try:
            from agents.autotutor_shadow import record_shadow_metric

            record_shadow_metric(
                transition_kind=transition_kind,
                matched=matched,
                duration_ms=(perf_counter() - comparator_started) * 1000,
                reason_codes=list(reasons),
            )
        except Exception:
            pass
    if matched or before.executor_mode != "graph_active":
        return selected
    if not settings.fallback_enabled:
        raise RuntimeError("active_comparator_mismatch:" + ",".join(reasons))
    reason = ("active_comparator_mismatch:" + ",".join(reasons))[:120]
    comparator.next_state.executor_mode = "legacy"
    comparator.next_state.executor_fallback_reason = reason
    comparator.executor_mode = "legacy"
    comparator.public_result = _public_state(comparator.next_state)
    comparator.diagnostics.provider_latency_ms = selected.diagnostics.provider_latency_ms
    comparator.diagnostics.executor_latency_ms = selected.diagnostics.executor_latency_ms
    comparator.diagnostics.comparator_latency_ms = selected.diagnostics.comparator_latency_ms
    comparator.diagnostics.comparator_matched = False
    comparator.diagnostics.fallback_reason = reason
    return comparator


def _record_executor_observation(
    state: AutoTutorState,
    *,
    transition_kind: str,
    context: AutoTutorExecutionContext,
    started_at: float,
    outcome: AutoTutorTransitionOutcome | None = None,
) -> None:
    try:
        from agent_runtime.rollout_observations import try_record_rollout_observation

        status = "completed" if state.status == "completed" else "committed"
        if state.executor_fallback_reason:
            status = "fallback"
        comparator_observed = bool(
            outcome
            and (
                state.executor_mode == "graph_active"
                or outcome.diagnostics.comparator_latency_ms > 0
                or not outcome.diagnostics.comparator_matched
            )
        )
        try_record_rollout_observation(
            agent_type="auto_tutor",
            runtime_mode="active" if state.executor_mode == "graph_active" else "control",
            status=f"{status}:{transition_kind}"[:40],
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
            trace_id=state.trace_id,
            data_scope=context.data_scope,
            config_version=state.executor_config_version,
            deployed_commit=context.deployed_commit,
            environment=context.environment,
            traffic_cohort=context.traffic_cohort,
            rollout_eligible=context.rollout_eligible,
            eligibility_reason=context.eligibility_reason,
            assigned_executor=state.executor_assigned_mode or state.executor_mode,
            selected_executor=state.executor_mode,
            transition_kind=transition_kind,
            transition_id=outcome.diagnostics.transition_id if outcome else None,
            observation_schema_version="v1.49.2-observation" if outcome else None,
            outcome_schema_version=outcome.schema_version if outcome else None,
            commit_status=status,
            comparator_matched=outcome.diagnostics.comparator_matched if comparator_observed and outcome else None,
            fallback_reason=state.executor_fallback_reason,
            provider_latency_ms=round(outcome.diagnostics.provider_latency_ms) if outcome else None,
            executor_latency_ms=round(outcome.diagnostics.executor_latency_ms) if outcome else None,
            comparator_latency_ms=round(outcome.diagnostics.comparator_latency_ms) if outcome else None,
            observation_external_calls=outcome.diagnostics.observation_external_calls if outcome else None,
            effect_intent_count=(
                len(outcome.learning_events)
                + len(outcome.weakpoint_evidence)
                + (1 if outcome.review_memory else 0)
            ) if outcome else None,
        )
    except Exception:
        return


# --------------------------------------------------------------------------- #
# 会话存储（内存 + TTL，沿用 trace_store 的轻量做法）
# --------------------------------------------------------------------------- #
class _SessionStore:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._sessions: dict[str, AutoTutorState] = {}
        self._timestamps: dict[str, float] = {}
        self._session_locks: dict[str, threading.RLock] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def save(self, state: AutoTutorState) -> None:
        self.cache(state)
        _persist_session(state)

    def cache(self, state: AutoTutorState) -> None:
        with self._lock:
            self._cleanup_locked()
            self._sessions[state.session_id] = state
            self._timestamps[state.session_id] = time.time()

    def get(self, session_id: str) -> AutoTutorState | None:
        with self._lock:
            self._cleanup_locked()
            existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        restored = _load_persisted_session(session_id)
        if restored is not None:
            with self._lock:
                self._sessions[session_id] = restored
                self._timestamps[session_id] = time.time()
        return restored

    def session_lock(self, session_id: str) -> threading.RLock:
        """Serialize mutations for one session without blocking other sessions."""
        with self._lock:
            return self._session_locks.setdefault(session_id, threading.RLock())

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, ts in self._timestamps.items() if now - ts > self._ttl]
        for sid in expired:
            self._sessions.pop(sid, None)
            self._timestamps.pop(sid, None)
            self._session_locks.pop(sid, None)


_store = _SessionStore()


def _ensure_session_table() -> None:
    with get_connection() as conn:
        if conn.dialect.name != "sqlite":
            inspector = sa_inspect(conn)
            if "autotutor_sessions" not in set(inspector.get_table_names()):
                raise RuntimeError("autotutor_sessions is not migrated; run Alembic 007")
            required = {
                "session_id", "student_id", "trace_id", "run_id", "status",
                "revision", "state_json", "inflight_idempotency_key",
                "start_idempotency_key", "last_idempotency_key",
                "last_response_json", "created_at", "updated_at",
                "inflight_request_hash", "last_request_hash",
            }
            missing = sorted(required - {column["name"] for column in inspector.get_columns("autotutor_sessions")})
            if missing:
                raise RuntimeError(f"autotutor_sessions migration 007 is incomplete: {', '.join(missing)}")
            return
        conn.execute(
            text(
                """CREATE TABLE IF NOT EXISTS autotutor_sessions (
                    session_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    run_id TEXT,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    state_json TEXT NOT NULL,
                    inflight_idempotency_key TEXT,
                    inflight_request_hash TEXT,
                    start_idempotency_key TEXT,
                    last_idempotency_key TEXT,
                    last_request_hash TEXT,
                    last_response_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
        )
        columns = {column["name"] for column in sa_inspect(conn).get_columns("autotutor_sessions")}
        additions = {
            "run_id": "TEXT",
            "revision": "INTEGER NOT NULL DEFAULT 0",
            "inflight_idempotency_key": "TEXT",
            "inflight_request_hash": "TEXT",
            "start_idempotency_key": "TEXT",
            "last_idempotency_key": "TEXT",
            "last_request_hash": "TEXT",
            "last_response_json": "TEXT",
        }
        for column_name, column_type in additions.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE autotutor_sessions ADD COLUMN {column_name} {column_type}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autotutor_sessions_student_updated ON autotutor_sessions(student_id, updated_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autotutor_sessions_run ON autotutor_sessions(run_id)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_autotutor_sessions_start_idempotency ON autotutor_sessions(student_id, start_idempotency_key)"))


def _restore_state(payload: dict[str, Any]) -> AutoTutorState:
    if "executor_assigned_mode" not in payload:
        payload = {**payload, "executor_assigned_mode": payload.get("executor_mode", "legacy")}
    state = AutoTutorState.model_validate(payload)
    if state.status == "completed" and state.phase != "completed":
        # 兼容 v1.26 之前持久化的已完成会话（当时还没有 phase 字段）。
        state.phase = "completed"
    legacy_active_step = next(
        (
            step for step in state.lesson_plan
            if step.question and (step.content_validation is None or step.objective is None)
        ),
        None,
    )
    if legacy_active_step is not None:
        state.legacy_unverified = True
        state.verified_mastery = False
        if state.status != "completed":
            legacy_active_step.status = "content_blocked"
            legacy_active_step.question = None
            blocked = {
                "objective_label": legacy_active_step.knowledge_point,
                "message": "这节旧课程缺少内容验证记录，已安全暂停，也不会改变你的掌握记录。",
                "reason": "legacy_content_unverified",
                "suggested_actions": ["重新开始这个知识点", "进入随问继续提问"],
            }
            legacy_active_step.content_blocked = blocked
            state.content_blocked = blocked
            state.status = "needs_content"
            state.phase = "content_blocked"
    state._sequence = max((step.sequence for step in state.runtime_steps), default=0)
    return state


def _persist_session(state: AutoTutorState, *, start_idempotency_key: str | None = None) -> None:
    _ensure_session_table()
    payload = state.model_dump()
    with get_connection() as conn:
        conn.execute(
            text(
                """INSERT INTO autotutor_sessions (
                    session_id, student_id, trace_id, run_id, status, revision, state_json,
                    start_idempotency_key, created_at, updated_at
                ) VALUES (
                    :session_id, :student_id, :trace_id, :run_id, :status, :revision, :state_json,
                    :start_idempotency_key, :created_at, :updated_at
                )
                ON CONFLICT(session_id) DO UPDATE SET
                    student_id=excluded.student_id,
                    trace_id=excluded.trace_id,
                    run_id=excluded.run_id,
                    status=excluded.status,
                    revision=excluded.revision,
                    state_json=excluded.state_json,
                    start_idempotency_key=COALESCE(autotutor_sessions.start_idempotency_key, excluded.start_idempotency_key),
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at"""
            ),
            {
                "session_id": state.session_id,
                "student_id": state.student_id,
                "trace_id": state.trace_id,
                "run_id": state.run_id,
                "status": state.status,
                "revision": state.revision,
                "state_json": json.dumps(payload, ensure_ascii=False),
                "start_idempotency_key": start_idempotency_key,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
            },
        )


def _load_start_idempotent_session(student_id: str, idempotency_key: str) -> AutoTutorState | None:
    _ensure_session_table()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT state_json FROM autotutor_sessions
            WHERE student_id=:student_id AND start_idempotency_key=:idempotency_key
            ORDER BY updated_at DESC LIMIT 1"""), {
            "student_id": student_id,
            "idempotency_key": idempotency_key,
        }).mappings().first()
    if not row:
        return None
    try:
        return _restore_state(json.loads(row["state_json"]))
    except Exception:
        return None


def _claim_answer_transition(
    session_id: str,
    expected_revision: int,
    idempotency_key: str,
    request_hash: str,
) -> tuple[str, AutoTutorState | dict[str, Any] | None]:
    """Atomically claim one answer transition before any judging side effect."""
    _ensure_session_table()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT state_json, revision, inflight_idempotency_key,
            inflight_request_hash, last_idempotency_key, last_request_hash,
            last_response_json, updated_at FROM autotutor_sessions
            WHERE session_id=:session_id"""), {"session_id": session_id}).mappings().first()
        if not row:
            return "missing", None
        if row.get("last_idempotency_key") == idempotency_key:
            if row.get("last_request_hash") != request_hash:
                return "conflict", None
            if row.get("last_response_json"):
                return "replayed", json.loads(row["last_response_json"])
        state = _restore_state(json.loads(row["state_json"]))
        state.revision = int(row["revision"] or 0)
        if int(row["revision"] or 0) != expected_revision:
            return "stale", state
        if row.get("inflight_idempotency_key") == idempotency_key and row.get("inflight_request_hash") != request_hash:
            return "conflict", state
        stale_before = time.time() - 60.0
        claimed = conn.execute(text("""UPDATE autotutor_sessions
            SET inflight_idempotency_key=:idempotency_key,
                inflight_request_hash=:request_hash, updated_at=:updated_at
            WHERE session_id=:session_id AND revision=:expected_revision
              AND (inflight_idempotency_key IS NULL OR inflight_idempotency_key=''
                   OR updated_at < :stale_before)"""), {
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "updated_at": time.time(),
            "stale_before": stale_before,
            "session_id": session_id,
            "expected_revision": expected_revision,
        })
        if claimed.rowcount != 1:
            return "busy", state
    return "claimed", state


def _release_answer_transition(
    session_id: str,
    *,
    expected_revision: int,
    idempotency_key: str,
    request_hash: str,
) -> None:
    """Release a rolled-back claim without advancing the business revision."""
    with get_connection() as conn:
        conn.execute(text("""UPDATE autotutor_sessions SET
            inflight_idempotency_key=NULL, inflight_request_hash=NULL,
            updated_at=:updated_at
            WHERE session_id=:session_id AND revision=:expected_revision
              AND inflight_idempotency_key=:idempotency_key
              AND inflight_request_hash=:request_hash"""), {
            "updated_at": time.time(),
            "session_id": session_id,
            "expected_revision": expected_revision,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
        })


def _load_persisted_session(session_id: str) -> AutoTutorState | None:
    _ensure_session_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT state_json, revision FROM autotutor_sessions WHERE session_id=:session_id"),
            {"session_id": session_id},
        ).mappings().first()
    if not row:
        return None
    try:
        state = _restore_state(json.loads(row["state_json"]))
        state.revision = int(row["revision"] or 0)
        return state
    except Exception:
        return None


def _load_latest_persisted_session(student_id: str, *, include_completed: bool = False) -> AutoTutorState | None:
    _ensure_session_table()
    sql = "SELECT state_json, revision FROM autotutor_sessions WHERE student_id=:student_id"
    if not include_completed:
        sql += " AND status != 'completed'"
    sql += " ORDER BY updated_at DESC LIMIT 1"
    with get_connection() as conn:
        row = conn.execute(text(sql), {"student_id": student_id}).mappings().first()
    if not row:
        return None
    try:
        state = _restore_state(json.loads(row["state_json"]))
        state.revision = int(row["revision"] or 0)
        return state
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# trace / runtime step 辅助
# --------------------------------------------------------------------------- #
def _emit(
    state: AutoTutorState,
    step_id: str,
    step_name: str,
    event_type: str,
    status: str = "success",
    *,
    started_at: float | None = None,
    metadata: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """记录一个 runtime step：写入 trace_store（可被 /api/traces 查询）并挂到会话状态上。"""
    if state._observation_capture:
        return
    latency_ms = round((perf_counter() - started_at) * 1000, 2) if started_at is not None else None
    if not state._transition_active:
        emit_trace_event(
            agent_name=AGENT_NAME,
            step_name=step_name,
            event_type=event_type,
            status=status,
            latency_ms=int(latency_ms) if latency_ms is not None else None,
            metadata=metadata,
        )
    state._sequence += 1
    state.runtime_steps.append(
        RuntimeStep(
            trace_id=state.trace_id,
            step_id=f"{step_id}_{state._sequence}",
            step_name=step_name,
            sequence=state._sequence,
            event_type=event_type,
            status=status,
            latency_ms=latency_ms,
            metadata=metadata or {},
            error=error,
        )
    )


def _mirror_transition_trace(state: AutoTutorState, *, from_sequence: int) -> None:
    """Best-effort trace mirror after the business transition has committed."""
    for step in state.runtime_steps:
        if step.sequence <= from_sequence:
            continue
        try:
            emit_trace_event(
                agent_name=AGENT_NAME,
                step_name=step.step_name,
                event_type=step.event_type,
                status=step.status,
                latency_ms=int(step.latency_ms) if step.latency_ms is not None else None,
                metadata=step.metadata,
            )
        except Exception:
            continue


def _tool_context(student_id: str, actor_id: str | None, actor_role: str | None) -> ToolExecutionContext:
    return ToolExecutionContext(
        actor_id=actor_id,
        role=actor_role or "student",
        student_id=student_id,
        request_source="auto_tutor",
    )


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #
def _fallback_plan(weakpoints: list[dict[str, Any]], weak_topics: list[str], recent_topics: list[str]) -> list[LessonStep]:
    """从学情中选择一个主目标，避免把无关近期主题拼成一节课。"""
    seen: list[str] = []
    steps: list[LessonStep] = []
    ranked = [w["knowledge_tag"] for w in weakpoints] + weak_topics + recent_topics
    for tag in ranked:
        if not tag or tag in seen:
            continue
        seen.append(tag)
        wrong = next((w["wrong_count"] for w in weakpoints if w["knowledge_tag"] == tag), 0)
        difficulty: Difficulty = "easy" if wrong >= 2 else "medium"
        steps.append(
            LessonStep(
                knowledge_point=tag,
                source_tag=tag,
                difficulty=difficulty,
                rationale=f"错题本中错过 {wrong} 次，优先巩固。" if wrong else "近期学习主题，纳入巩固。",
            )
        )
        if len(steps) >= 1:
            break
    if not steps:
        steps.append(LessonStep(knowledge_point="鸦片战争影响", difficulty="easy", rationale="暂无学情，从近代史开篇的核心影响切入。"))
    return steps


def _generate_plan(state: AutoTutorState, weakpoints: list[dict[str, Any]], profile: Any, focus_tags: list[str] | None = None, focus_reason: str | None = None) -> list[LessonStep]:
    """生成受控课时计划：一个主目标，后续仅在有审核关系时再扩支持目标。"""
    weak_topics = list(getattr(profile, "weak_topics", []) or [])
    recent_topics = list(getattr(profile, "recent_topics", []) or [])
    if focus_tags and str(focus_tags[0]).strip():
        tag = str(focus_tags[0]).strip()
        wrong = next((int(w.get("wrong_count") or 0) for w in weakpoints if w.get("knowledge_tag") == tag), 0)
        rationale = f"显式聚焦目标；错题本中错过 {wrong} 次。" if wrong else "显式聚焦目标，作为本节主目标。"
        if focus_reason:
            rationale += f" 错因提示：{focus_reason}"
        return [LessonStep(
            knowledge_point=tag,
            source_tag=tag,
            difficulty="easy" if wrong >= 2 else "medium",
            strategy="先明确学习目标，再区分易混概念并用有效题检验。",
            rationale=rationale,
        )]
    return _fallback_plan(weakpoints, weak_topics, recent_topics)[:1]


# --------------------------------------------------------------------------- #
# act：取材 + 教学 + 出题检验
# --------------------------------------------------------------------------- #
def _record_content_event(
    state: AutoTutorState,
    step: LessonStep,
    event_type: str,
    *,
    metadata: dict[str, Any],
    success: bool | None = None,
) -> None:
    if state._observation_capture:
        return
    objective = step.objective
    event_success = event_type == "auto_tutor_content_verified" if success is None else success
    event = LearningEvent(
        student_id=state.student_id,
        session_id=state.session_id,
        feature="auto_tutor",
        event_type=event_type,
        grade=state.grade,
        topic=step.source_tag or step.knowledge_point,
        success=event_success,
        score=1.0 if event_success else 0.0,
        metadata={
            "objective_id": objective.objective_id if objective else None,
            "aspect": objective.aspect if objective else None,
            "content_version": step.content_version,
            **metadata,
        },
    )
    if not state._transition_active:
        try_record_learning_event(event)
        return
    assessment_or_step = str(metadata.get("assessment_id") or f"step-{state.current_step_index}")
    effect_key = (
        f"autotutor:{state.session_id}:revision:{state.revision}:"
        f"{event_type}:{assessment_or_step}"
    )
    if any(item.effect_key == effect_key for item in state._pending_learning_events):
        return
    state._pending_learning_events.append(LearningEventIntent(effect_key=effect_key, event=event))


def _block_content(state: AutoTutorState, step: LessonStep, reason: str) -> None:
    step.status = "content_blocked"
    step.question = None
    step.teaching = None
    message = "当前教材证据或审定题目不足，暂不生成题目，也不会改变你的掌握记录。"
    blocked = {
        "objective_label": step.knowledge_point,
        "message": message,
        "reason": reason,
        "suggested_actions": ["换一个相关知识点", "进入随问继续提问"],
    }
    step.content_blocked = blocked
    state.content_blocked = blocked
    state.phase = "content_blocked"
    state.status = "needs_content"
    _record_content_event(
        state,
        step,
        "auto_tutor_content_blocked",
        metadata={"reason": reason, "content_validation_status": "blocked", "mastery_eligible": False},
    )
    _emit(
        state,
        "content_blocked",
        "Content Gate · 内容阻断",
        "content_gate",
        "blocked",
        metadata={
            "knowledge_point": step.knowledge_point,
            "reason": reason,
            "result_summary": message,
        },
    )


def _act(state: AutoTutorState, step: LessonStep, ctx: ToolExecutionContext) -> None:
    """结构化取材并通过内容门禁后，才向学生提供讲解和可评分题。"""
    step.status = "active"
    step.objective = step.objective or build_learning_objective(
        step.knowledge_point,
        source_tag=step.source_tag,
        grade=state.grade,
        lesson=state.lesson_id,
        misconception_hint=step.rationale,
    )
    objective = step.objective
    tool_started = perf_counter()
    _emit(
        state,
        "tool_selection",
        "Tool Selection",
        "tool_selection",
        metadata={"tool_name": step.tool, "input_summary": {"query": step.knowledge_point, "k": 4}},
    )
    retrieval_data: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    retrieval_error: str | None = None
    try:
        result = run_tool(
            "search_history_knowledge",
            {
                "query": step.knowledge_point,
                "grade": state.grade,
                "lesson": state.lesson_id,
                "topic": objective.entity or step.knowledge_point,
                "k": 4,
            },
            context=ctx,
        )
        if result.ok:
            retrieval_data = dict(result.data or {})
            sources = [source for source in retrieval_data.get("sources", []) if isinstance(source, dict)]
        else:
            retrieval_error = result.error.message if result.error else "retrieval_failed"
        sufficiency = retrieval_data.get("evidence_sufficiency") or {}
        _emit(
            state,
            "act_retrieval",
            "Act · 取材",
            "tool_result",
            "success" if result.ok else "degraded",
            started_at=tool_started,
            metadata={
                "tool_name": "search_history_knowledge",
                "ok": result.ok,
                "source_count": len(sources),
                "answer_bearing_source_count": int(sufficiency.get("answer_bearing_source_count") or 0),
                "retrieval_status": sufficiency.get("status") or retrieval_data.get("retrieval_status") or "none",
                "result_summary": f"已为「{step.knowledge_point}」完成结构化取材与证据诊断",
            },
        )
    except Exception as exc:
        retrieval_error = exc.__class__.__name__
        _emit(
            state,
            "act_retrieval",
            "Act · 取材",
            "tool_result",
            "degraded",
            started_at=tool_started,
            metadata={"tool_name": "search_history_knowledge", "result_summary": "检索不可用，转入审定内容门禁"},
            error={"message": str(exc)},
        )

    current_assessment_id = str((step.question or {}).get("assessment_id") or "")
    if current_assessment_id and current_assessment_id not in step.assessment_history:
        step.assessment_history.append(current_assessment_id)
    prepared = prepare_content(
        objective,
        retrieval_data,
        kind="practice",
        variant_index=step.attempts,
        target_difficulty=step.difficulty,
        excluded_assessment_ids=set(step.assessment_history),
        preferred_cognitive_actions=["recall", "explain"] if step.replanned else None,
        selection_seed=f"{state.session_id}:{state.current_step_index}:{step.attempts}",
    )
    step.evidence_decision = prepared.evidence
    step.content_validation = prepared.validation
    step.content_version = prepared.content_version
    step.evidence_label = prepared.evidence_label
    step.sources = [source for source in sources if source.get("answer_bearing") is True][:4]
    if prepared.validation.status != "verified" or prepared.teaching is None or prepared.assessment is None:
        _block_content(state, step, prepared.blocked_reason or retrieval_error or "content_validation_failed")
        return

    step.teaching = prepared.teaching.model_dump(mode="json")
    if step.replanned and state.answer_feedback:
        correction = str(state.answer_feedback.get("correction") or "").strip()
        if correction:
            step.teaching["explanation"] = f"先纠正刚才的混淆：{correction} {step.teaching['explanation']}"
            step.teaching["example"] = f"先对照你刚才选择的说法，再判断它回答的是不是“{step.objective.target_outcome}”。"
    step.question = assessment_to_question(prepared.assessment)
    step.difficulty = prepared.assessment.difficulty
    if prepared.assessment.assessment_id not in step.assessment_history:
        step.assessment_history.append(prepared.assessment.assessment_id)
    step.content_blocked = None
    state.content_blocked = None
    state.phase = "lesson"
    state.status = "awaiting_answer"
    _record_content_event(
        state,
        step,
        "auto_tutor_content_verified",
        metadata={
            "assessment_id": prepared.assessment.assessment_id,
            "assessment_kind": "practice",
            "content_validation_status": "verified",
            "mastery_eligible": state.content_gate_mode == "enforce",
            "generation_mode": prepared.assessment.generation_mode,
        },
    )
    teach_started = perf_counter()
    _emit(
        state,
        "reteach" if step.replanned else "teach",
        "Re-teach · 调整讲解" if step.replanned else "Teach · 知识讲解",
        "reteach" if step.replanned else "teach",
        started_at=teach_started,
        metadata={
            "knowledge_point": step.knowledge_point,
            "difficulty": step.difficulty,
            "attempt": step.attempts + 1,
            "content_validation_status": "verified",
            "result_summary": str(step.teaching.get("explanation") or "")[:80],
        },
    )
    _emit(
        state,
        "act_question",
        "Act · 有效练习",
        "act",
        metadata={
            "knowledge_point": step.knowledge_point,
            "difficulty": step.difficulty,
            "assessment_id": prepared.assessment.assessment_id,
            "content_validation_status": "verified",
            "result_summary": prepared.assessment.stem[:60],
        },
    )
    _emit(
        state,
        "observe",
        "Observe · 等待作答",
        "observe",
        "waiting_answer",
        metadata={"knowledge_point": step.knowledge_point, "step_index": state.current_step_index},
    )


# --------------------------------------------------------------------------- #
# judge
# --------------------------------------------------------------------------- #
def _judge(step: LessonStep, answer: str) -> tuple[bool, str]:
    question = step.question or {}
    judgement = judge_answer(
        answer=answer,
        correct_answer=str(question.get("answer") or ""),
        content_verified=bool(step.content_validation and step.content_validation.status == "verified"),
    )
    return judgement.is_correct, judgement.correct_option


def _assessment_from_question(question: dict[str, Any]) -> AssessmentItem:
    return AssessmentItem.model_validate({
        "assessment_id": question.get("assessment_id"),
        "objective_id": question.get("objective_id"),
        "kind": question.get("kind"),
        "stem": question.get("question"),
        "options": question.get("options_meta") or [],
        "difficulty": question.get("difficulty") or "medium",
        "cognitive_action": question.get("cognitive_action") or "explain",
        "source_ids": question.get("source_ids") or [],
        "variant_of": question.get("variant_of"),
        "generation_mode": question.get("generation_mode") or "curated",
    })


# --------------------------------------------------------------------------- #
# reflect + re_plan
# --------------------------------------------------------------------------- #
class _Reflection(BaseModel):
    diagnosis: str
    adjustment: AdjustmentAction
    explanation: str


def _acquire_reflection_observation(
    step: LessonStep,
    answer: str,
    *,
    step_index: int,
) -> ReflectionRecord:
    """Acquire one model/fallback reflection without mutating transition state."""
    question = step.question or {}
    assessment = _assessment_from_question(question)
    feedback = build_answer_feedback(assessment, answer)
    selected_option = next((option for option in assessment.options if option.option_id == feedback["selected_option"]), None)
    correct_option = next(option for option in assessment.options if option.is_correct)
    prompt = [
        {
            "role": "system",
            "content": (
                "你是辅导 agent 的反思模块。学生答错了一道题，请诊断原因并决定如何调整教学计划。\n"
                "adjustment 取值：reteach（讲解不到位，需补讲）、lower_difficulty（题目超纲/偏难，需降难度）、"
                "change_example（概念没听懂，换个例子）。\n"
                "只输出 JSON：{\"diagnosis\":\"一句诊断\",\"adjustment\":\"reteach\",\"explanation\":\"给学生的补充讲解，2-3句，不带Markdown\"}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"知识点：{step.knowledge_point}\n难度：{step.difficulty}\n"
                f"学习目标：{step.objective.model_dump(mode='json') if step.objective else {}}\n"
                f"题目：{question.get('question', '')}\n"
                f"学生所选：{selected_option.text if selected_option else answer}\n"
                f"对应误区：{selected_option.misconception_code if selected_option else 'invalid_option'}\n"
                f"正确选项：{correct_option.text}\n正确依据：{correct_option.feedback}\n"
                f"历史错因：{step.rationale}\n当前讲解：{(step.teaching or {}).get('explanation', '')}\n"
                f"本步已尝试次数：{step.attempts}"
            ),
        },
    ]
    fallback = _Reflection(
        diagnosis=feedback["message"],
        adjustment="reteach",
        explanation=feedback["correction"],
    )
    try:
        invocation = invoke_structured_with_provenance(
            llm_quality,
            prompt,
            model=_Reflection,
            fallback=fallback,
        )
        reflection = invocation.value
        provenance = invocation.provenance.model_dump(mode="json")
    except Exception:
        reflection = fallback
        provenance = StructuredInvocationProvenance(
            decision_source="deterministic_fallback",
            configured_profile=getattr(llm_quality, "name", None),
            configured_model=getattr(llm_quality, "model", None),
            fallback_used=True,
        ).model_dump(mode="json")

    return ReflectionRecord(
        step_index=step_index,
        knowledge_point=step.knowledge_point,
        diagnosis=reflection.diagnosis,
        adjustment=reflection.adjustment,
        explanation=reflection.explanation,
        decision_provenance=provenance,
    )


def _reflect_and_replan(state: AutoTutorState, step: LessonStep, answer: str, ctx: ToolExecutionContext) -> ReflectionRecord:
    """学生答错 → 反思（讲错/超纲/粗心）→ 真实修改计划（补讲/降难度/换例子）。"""
    reflect_started = perf_counter()
    record = _acquire_reflection_observation(step, answer, step_index=state.current_step_index)
    public_provenance = public_decision_provenance(record.decision_provenance)

    _emit(
        state,
        "reflect",
        "Reflect · 反思诊断",
        "reflect",
        started_at=reflect_started,
        metadata={
            "knowledge_point": step.knowledge_point,
            "diagnosis": record.diagnosis,
            "adjustment": record.adjustment,
            "decision_provenance": public_provenance,
            "result_summary": f"诊断：{record.diagnosis} → 调整：{record.adjustment}",
        },
    )

    # —— re_plan：真实修改计划 ——
    replan_started = perf_counter()
    state.replans += 1
    step.replanned = True
    later_steps = state.lesson_plan[state.current_step_index + 1:]
    replan = replan_policy(
        current_difficulty=step.difficulty,
        later_difficulties=[later.difficulty for later in later_steps],
        adjustment=record.adjustment,
        explanation=record.explanation,
        later_labels=[later.knowledge_point for later in later_steps],
    )
    step.difficulty = replan.current_difficulty
    step.strategy = replan.strategy
    for later, difficulty in zip(later_steps, replan.later_difficulties, strict=True):
        later.difficulty = difficulty
    changes = list(replan.changes)

    _emit(
        state,
        "re_plan",
        "Re-plan · 调整计划",
        "re_plan",
        started_at=replan_started,
        metadata={
            "replans": state.replans,
            "adjustment": record.adjustment,
            "plan_changes": changes,
            "result_summary": "；".join(changes),
        },
    )

    # 重新取材出题（被调整后的难度）
    _KERNEL_ACT(state, step, ctx)

    state.reflect_log.append(record)
    return record


# --------------------------------------------------------------------------- #
# exit ticket：课后退出票检验
# --------------------------------------------------------------------------- #
def _select_exit_ticket_target(state: AutoTutorState) -> tuple[LessonStep | None, str]:
    if not state.lesson_plan:
        return None, "fallback"
    primary = state.lesson_plan[0]
    if primary.status == "struggling":
        return primary, "struggling_step"
    if primary.replanned:
        return primary, "replanned_step"
    return primary, "fallback"


def _start_exit_ticket(state: AutoTutorState, ctx: ToolExecutionContext) -> None:
    ticket_started = perf_counter()
    target, generated_from = _select_exit_ticket_target(state)
    if target is None:
        _KERNEL_FINALIZE(state)
        return
    difficulty: Difficulty = "medium"
    if target.objective is None:
        _block_content(state, target, "exit_ticket_objective_missing")
        return
    retrieval_data = {
        "sources": target.sources,
        "evidence_sufficiency": target.evidence_decision.model_dump(mode="json") if target.evidence_decision else {},
    }
    practice_assessment_id = str((target.question or {}).get("assessment_id") or "") or None
    practice_assessment = _assessment_from_question(target.question) if target.question else None
    prepared = prepare_content(
        target.objective,
        retrieval_data,
        kind="exit_ticket",
        target_difficulty=difficulty,
        excluded_assessment_ids=set(target.assessment_history),
        preferred_cognitive_actions=["apply"],
        selection_seed=f"{state.session_id}:exit-ticket:{target.objective.objective_id}",
        excluded_assessment_id=practice_assessment_id,
        excluded_assessment=practice_assessment,
    )
    if prepared.validation.status != "verified" or prepared.assessment is None:
        target.content_validation = prepared.validation
        _block_content(state, target, prepared.blocked_reason or "exit_ticket_validation_failed")
        return
    question = assessment_to_question(prepared.assessment)
    state.exit_ticket = ExitTicket(
        knowledge_point=target.knowledge_point,
        source_tag=target.source_tag,
        difficulty=prepared.assessment.difficulty,
        strategy="课后退出票检验：用一道迁移题确认本节辅导是否真正生效。",
        question=question,
        sources=target.sources[:4],
        generated_from=generated_from,  # type: ignore[arg-type]
        objective=target.objective,
        content_validation=prepared.validation,
        content_version=prepared.content_version,
        evidence_label=prepared.evidence_label,
    )
    state.phase = "exit_ticket"
    state.status = "awaiting_answer"
    _record_content_event(
        state,
        target,
        "auto_tutor_content_verified",
        metadata={
            "assessment_id": prepared.assessment.assessment_id,
            "assessment_kind": "exit_ticket",
            "content_validation_status": "verified",
            "mastery_eligible": state.content_gate_mode == "enforce",
            "generation_mode": prepared.assessment.generation_mode,
        },
    )
    _emit(
        state,
        "exit_ticket",
        "Exit Ticket · 生成退出票",
        "exit_ticket",
        "waiting_answer",
        started_at=ticket_started,
        metadata={
            "knowledge_point": state.exit_ticket.knowledge_point,
            "source_tag": state.exit_ticket.source_tag,
            "difficulty": state.exit_ticket.question.get("difficulty") or state.exit_ticket.difficulty,
            "cognitive_action": state.exit_ticket.question.get("cognitive_action"),
            "generated_from": generated_from,
            "assessment_id": prepared.assessment.assessment_id,
            "result_summary": f"为「{state.exit_ticket.knowledge_point}」生成课后退出票，等待学生完成最后检验",
        },
    )


def _submit_exit_ticket_answer(state: AutoTutorState, answer: str) -> tuple[bool, str]:
    if state.exit_ticket is None:
        raise RuntimeError("exit ticket not prepared")
    if not state.exit_ticket.content_validation or state.exit_ticket.content_validation.status != "verified":
        raise RuntimeError("invalid exit ticket cannot enter judge")
    assessment = _assessment_from_question(state.exit_ticket.question)
    given = (answer or "").strip()[:1].upper()
    correct_letter = str(state.exit_ticket.question.get("answer") or "").strip()[:1].upper()
    if correct_letter not in {"A", "B", "C", "D"}:
        raise RuntimeError("verified exit ticket has no valid answer")
    is_correct = bool(given) and given == correct_letter
    feedback = build_answer_feedback(assessment, given)
    state.answer_feedback = feedback
    primary = state.lesson_plan[0] if state.lesson_plan else None
    practice = primary.practice_result if primary else None
    mastery_gate_passed = verified_mastery(
        practice_assessment_id=str((practice or {}).get("assessment_id") or "") or None,
        practice_objective_id=str((practice or {}).get("objective_id") or "") or None,
        practice_correct=bool((practice or {}).get("is_correct")),
        practice_validation_status=(practice or {}).get("content_validation_status"),
        exit_assessment_id=assessment.assessment_id,
        exit_objective_id=assessment.objective_id,
        exit_correct=is_correct,
        exit_validation_status=state.exit_ticket.content_validation.status,
    )
    mastery_verified = bool(mastery_gate_passed and state.content_gate_mode == "enforce")
    state.verified_mastery = mastery_verified
    if primary and mastery_verified:
        primary.status = "mastered"
    state.exit_ticket_result = ExitTicketResult(
        knowledge_point=state.exit_ticket.knowledge_point,
        source_tag=state.exit_ticket.source_tag,
        selected_answer=given,
        correct_answer=correct_letter,
        is_correct=is_correct,
        explanation=feedback["correction"],
        mastery_signal="exit_ticket_passed" if is_correct else "exit_ticket_failed",
        assessment_id=assessment.assessment_id,
        objective_id=assessment.objective_id,
        content_validation_status=state.exit_ticket.content_validation.status,
        verified_mastery=mastery_verified,
    )
    _emit(
        state,
        "exit_ticket_judge",
        "Exit Ticket · 判定学习证据",
        "exit_ticket",
        "success" if is_correct else "failed",
        metadata={
            "knowledge_point": state.exit_ticket.knowledge_point,
            "answer": given,
            "correct": correct_letter,
            "is_correct": is_correct,
            "verified_mastery": mastery_verified,
            "result_summary": "退出票通过，掌握证据已验证" if mastery_verified else "退出票已作答，掌握尚未验证",
        },
    )
    return is_correct, correct_letter


# --------------------------------------------------------------------------- #
# finalize：落 memory + 错题进 SM-2 复习池
# --------------------------------------------------------------------------- #
def _finalize(state: AutoTutorState) -> None:
    if state.status == "completed":
        return
    finalize_started = perf_counter()
    event_types: list[str] = []
    for step in state.lesson_plan:
        practice = step.practice_result or {}
        if not practice:
            continue
        tag = step.source_tag or step.knowledge_point
        practice_ok = bool(practice.get("is_correct"))
        metadata = {
            "objective_id": practice.get("objective_id"),
            "aspect": step.objective.aspect if step.objective else None,
            "content_version": step.content_version,
            "assessment_id": practice.get("assessment_id"),
            "assessment_kind": "practice",
            "content_validation_status": practice.get("content_validation_status"),
            "mastery_eligible": False,
            "generation_mode": (step.question or {}).get("generation_mode"),
            "legacy_practice_result": True,
            "difficulty": step.difficulty,
            "attempts": step.attempts,
            "replanned": step.replanned,
        }
        for event_type in ("auto_tutor_step",):
            _record_content_event(
                state,
                step,
                event_type,
                success=practice_ok,
                metadata=metadata,
            )
            event_types.append(event_type)

    weakpoint_action = "not_recorded"
    review_action = "no_new_review_needed"
    exit_ticket_summary = "退出票未生成"
    primary = state.lesson_plan[0] if state.lesson_plan else None
    if state.exit_ticket and state.exit_ticket_result:
        ticket = state.exit_ticket
        result = state.exit_ticket_result
        ticket_tag = ticket.source_tag or ticket.knowledge_point
        ticket_metadata = {
            "objective_id": result.objective_id,
            "aspect": ticket.objective.aspect if ticket.objective else None,
            "content_version": ticket.content_version,
            "assessment_id": result.assessment_id,
            "assessment_kind": "exit_ticket",
            "content_validation_status": result.content_validation_status,
            "mastery_eligible": state.content_gate_mode == "enforce",
            "generation_mode": ticket.question.get("generation_mode"),
            "generated_from": ticket.generated_from,
            "replans": state.replans,
        }
        for event_type in ("auto_tutor_exit_ticket_answered", "auto_tutor_exit_ticket"):
            if primary is not None:
                _record_content_event(
                    state,
                    primary,
                    event_type,
                    success=result.is_correct,
                    metadata=ticket_metadata,
                )
            event_types.append(event_type)

        if state.verified_mastery:
            weakpoint_action = "independent_correct_evidence_recorded"
            evidence_type: Literal["independent_correct"] = "independent_correct"
            if primary is not None:
                _record_content_event(
                    state,
                    primary,
                    "auto_tutor_verified_mastery",
                    success=True,
                    metadata={**ticket_metadata, "mastery_eligible": True},
                )
            event_types.append("auto_tutor_verified_mastery")
            practice_result = primary.practice_result if primary is not None else None
            practice_id = str((practice_result or {}).get("assessment_id") or "")
            retrieval_key = (
                f"autotutor:{state.session_id}:revision:{state.revision}:"
                f"weakpoint:retrieval_correct:{practice_id}"
            )
            if primary is not None and practice_id:
                state._pending_weakpoint_evidence.append(WeakpointEvidenceIntent(
                    evidence_key=retrieval_key,
                    student_id=state.student_id,
                    knowledge_tag=ticket_tag,
                    evidence_type="retrieval_correct",
                    source_session_id=state.session_id,
                    assessment_id=practice_id,
                    evidence_stage="retrieval",
                    assessment_fingerprint=assessment_fingerprint(_assessment_from_question(primary.question or {})),
                ))
            evidence_key = (
                f"autotutor:{state.session_id}:revision:{state.revision}:"
                f"weakpoint:{evidence_type}:{result.assessment_id}"
            )
            state._pending_weakpoint_evidence.append(WeakpointEvidenceIntent(
                evidence_key=evidence_key,
                student_id=state.student_id,
                knowledge_tag=ticket_tag,
                evidence_type=evidence_type,
                source_session_id=state.session_id,
                assessment_id=result.assessment_id,
                evidence_stage="verification",
                assessment_fingerprint=assessment_fingerprint(_assessment_from_question(ticket.question or {})),
                parent_evidence_key=retrieval_key if practice_id else None,
            ))
        elif not result.is_correct or (primary and primary.status == "struggling"):
            weakpoint_action = "weakpoint_recorded"
            review_action = "weakpoint_added_to_review_pool"
            evidence_type = "wrong"
            evidence_key = (
                f"autotutor:{state.session_id}:revision:{state.revision}:"
                f"weakpoint:{evidence_type}:{result.assessment_id}"
            )
            state._pending_weakpoint_evidence.append(WeakpointEvidenceIntent(
                evidence_key=evidence_key,
                student_id=state.student_id,
                knowledge_tag=ticket_tag,
                evidence_type=evidence_type,
                source_session_id=state.session_id,
                assessment_id=result.assessment_id,
                evidence_stage="verification",
                assessment_fingerprint=assessment_fingerprint(_assessment_from_question(ticket.question or {})),
            ))
        elif state.content_gate_mode in {"off", "shadow"}:
            weakpoint_action = "rollout_unverified_no_mastery_write"
        exit_ticket_summary = (
            f"退出票通过并已验证掌握：{ticket.knowledge_point}"
            if state.verified_mastery
            else f"退出票{'答对' if result.is_correct else '未通过'}，掌握尚未验证：{ticket.knowledge_point}"
        )

    mastered = [step.knowledge_point for step in state.lesson_plan if step.status == "mastered"]
    practiced = [step.knowledge_point for step in state.lesson_plan if step.status == "practiced"]
    struggling = [step.knowledge_point for step in state.lesson_plan if step.status == "struggling"]
    state.evidence = EvidenceSummary(
        exit_ticket_recorded=bool(state.exit_ticket_result),
        learning_event_types=list(dict.fromkeys(event_types)),
        weakpoint_action=weakpoint_action,
        review_action=review_action,
        tutor_effectiveness_ready=bool(state.exit_ticket_result),
        verified_mastery=state.verified_mastery,
        content_validation_status=state.exit_ticket_result.content_validation_status if state.exit_ticket_result else None,
    )

    summary = (
        f"AutoTutor 本节课：已验证掌握 {('、'.join(mastered) or '无')}；"
        f"完成有效练习但尚未验证 {('、'.join(practiced) or '无')}；"
        f"仍需巩固 {('、'.join(struggling) or '无')}；触发 {state.replans} 次重规划；{exit_ticket_summary}。"
    )
    state.summary = summary
    state._pending_review_memory = MemoryEntryUpsert(
        student_id=state.student_id,
        type="review_goal",
        content={
            "mastered": mastered,
            "practiced": practiced,
            "struggling": struggling,
            "session_id": state.session_id,
            "exit_ticket": state.exit_ticket_result.model_dump() if state.exit_ticket_result else None,
            "evidence": state.evidence.model_dump() if state.evidence else None,
        },
        source_feature="auto_tutor",
        confidence=0.9 if state.verified_mastery else 0.7,
        reason="AutoTutor 自主辅导课后退出票与学习证据，用于排下一次复习。",
        metadata={"replans": state.replans, "exit_ticket_recorded": bool(state.exit_ticket_result)},
    )

    _emit(
        state,
        "finalize",
        "Finalize · 课后记忆与复习",
        "memory",
        started_at=finalize_started,
        metadata={
            "mastered": mastered,
            "practiced": practiced,
            "struggling": struggling,
            "replans": state.replans,
            "exit_ticket_result": state.exit_ticket_result.model_dump() if state.exit_ticket_result else None,
            "evidence": state.evidence.model_dump() if state.evidence else None,
            "wrote_memory": True,
            "scheduled_review_tags": struggling,
            "result_summary": summary,
        },
    )
    state.phase = "completed"
    state.status = "completed"


# --------------------------------------------------------------------------- #
# 对外 API：start / answer / get
# --------------------------------------------------------------------------- #
def _public_reflection(reflection: ReflectionRecord) -> dict[str, Any]:
    return {
        "step_index": reflection.step_index,
        "knowledge_point": reflection.knowledge_point,
        "diagnosis": reflection.diagnosis,
        "adjustment": reflection.adjustment,
        "explanation": reflection.explanation,
        "decision_provenance": public_decision_provenance(reflection.decision_provenance),
    }


def _public_state(state: AutoTutorState) -> dict[str, Any]:
    current = state.lesson_plan[state.current_step_index] if state.current_step_index < len(state.lesson_plan) else None
    current_question = None
    if state.phase == "exit_ticket" and state.exit_ticket and state.status == "awaiting_answer":
        objective = state.exit_ticket.objective
        current_question = {
            "kind": "exit_ticket",
            "assessment_id": state.exit_ticket.question.get("assessment_id"),
            "knowledge_point": state.exit_ticket.knowledge_point,
            "objective": {
                "objective_id": objective.objective_id,
                "label": state.exit_ticket.knowledge_point,
            } if objective else None,
            "content_status": state.exit_ticket.content_validation.status if state.exit_ticket.content_validation else "blocked",
            "evidence_label": state.exit_ticket.evidence_label,
            "difficulty": state.exit_ticket.difficulty,
            "question": state.exit_ticket.question.get("question"),
            "options": state.exit_ticket.question.get("options"),
            "step_index": len(state.lesson_plan),
            "replanned": False,
        }
    elif current and current.question and state.status == "awaiting_answer":
        # 不向前端泄露答案
        current_question = {
            "kind": "practice",
            "assessment_id": current.question.get("assessment_id"),
            "knowledge_point": current.knowledge_point,
            "objective": {
                "objective_id": current.objective.objective_id,
                "label": current.knowledge_point,
            } if current.objective else None,
            "content_status": current.content_validation.status if current.content_validation else "blocked",
            "evidence_label": current.evidence_label,
            "difficulty": current.difficulty,
            "cognitive_action": current.question.get("cognitive_action"),
            "teaching": {
                key: value
                for key, value in (current.teaching or {}).items()
                if key in {"explanation", "key_points", "example"}
            } if current.teaching else None,
            "question": current.question.get("question"),
            "options": current.question.get("options"),
            "step_index": state.current_step_index,
            "replanned": current.replanned,
            "adaptation": {
                "type": state.reflect_log[-1].adjustment if state.reflect_log else "reteach",
                "student_message": "换一道不更难的新题，先确认核心概念。",
            } if current.replanned else None,
        }
    primary = state.lesson_plan[0] if state.lesson_plan else None
    practice = primary.practice_result if primary else None
    exit_validation = state.exit_ticket.content_validation.status if state.exit_ticket and state.exit_ticket.content_validation else None
    public_runtime_steps = []
    for runtime_step in state.runtime_steps:
        payload = runtime_step.model_dump()
        payload["metadata"] = {
            key: value
            for key, value in (payload.get("metadata") or {}).items()
            if key not in {"answer", "correct", "source_ids", "answer_bearing_source_ids", "input_summary"}
        }
        public_runtime_steps.append(payload)
    return {
        "session_id": state.session_id,
        "run_id": state.run_id,
        "trace_id": state.trace_id,
        "student_id": state.student_id,
        "grade": state.grade,
        "status": state.status,
        "phase": state.phase,
        "content_gate_mode": state.content_gate_mode,
        "legacy_unverified": state.legacy_unverified,
        "revision": state.revision,
        "lesson_plan": [
            {
                "knowledge_point": s.knowledge_point,
                "source_tag": s.source_tag,
                "difficulty": s.difficulty,
                "status": s.status,
                "attempts": s.attempts,
                "replanned": s.replanned,
                "objective": {
                    "objective_id": s.objective.objective_id,
                    "entity": s.objective.entity,
                    "aspect": s.objective.aspect,
                    "target_outcome": s.objective.target_outcome,
                } if s.objective else None,
                "content_status": s.content_validation.status if s.content_validation else None,
            }
            for s in state.lesson_plan
        ],
        "current_step_index": state.current_step_index,
        "current_question": current_question,
        "reflect_log": [_public_reflection(reflection) for reflection in state.reflect_log],
        "replans": state.replans,
        "summary": state.summary,
        "exit_ticket_result": state.exit_ticket_result.model_dump() if state.exit_ticket_result else None,
        "evidence": state.evidence.model_dump() if state.evidence else None,
        "answer_feedback": state.answer_feedback,
        "mastery": {
            "status": "verified" if state.verified_mastery else "not_yet_verified",
            "practice_verified": bool(practice and practice.get("content_validation_status") == "verified"),
            "practice_correct": bool(practice and practice.get("is_correct")),
            "exit_ticket_verified": bool(state.exit_ticket_result and exit_validation == "verified"),
        },
        "content_blocked": {
            key: value
            for key, value in (state.content_blocked or {}).items()
            if key in {"objective_label", "message", "suggested_actions"}
        } if state.content_blocked else None,
        "runtime_steps": public_runtime_steps,
    }


def _autotutor_runtime_plan(session_id: str):
    from agent_runtime.models import AgentPlan, AgentStep

    return AgentPlan(
        plan_id=f"plan_{uuid4().hex}",
        objective="完成一次有界自主辅导课",
        strategy="subgraph",
        generated_by="template",
        planner_version="auto-tutor-v2",
        steps=[
            AgentStep(step_id="plan", kind="control", operation="auto_tutor.plan", side_effect="none", risk_level="low"),
            AgentStep(step_id="teach", kind="generation", operation="auto_tutor.teach", depends_on=["plan"], side_effect="external_call", risk_level="low", timeout_seconds=30),
            AgentStep(step_id="observe", kind="control", operation="auto_tutor.observe_judge", depends_on=["teach"], side_effect="none", risk_level="low"),
            AgentStep(
                step_id="finalize",
                kind="control",
                operation="auto_tutor.finalize",
                depends_on=["observe"],
                side_effect="write",
                risk_level="medium",
                idempotency_key=f"autotutor:{session_id}:finalize",
            ),
        ],
    )


def _autotutor_checkpoint_state(state: AutoTutorState, *, event_cursor: int | None = None) -> dict[str, Any]:
    """Persist recovery pointers without copying question or student content."""
    if state.phase == "exit_ticket" and state.exit_ticket:
        question = state.exit_ticket.question
        question_kind = "exit_ticket"
    elif state.current_step_index < len(state.lesson_plan):
        question = state.lesson_plan[state.current_step_index].question or {}
        question_kind = "lesson"
    else:
        question = {}
        question_kind = "none"
    question_digest = hashlib.sha256(
        json.dumps(question, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "autotutor_session_id": state.session_id,
        "autotutor_revision": state.revision,
        "phase": state.phase,
        "current_step_index": state.current_step_index,
        "question_kind": question_kind,
        "question_sha256": question_digest,
        **({"event_cursor": event_cursor} if event_cursor is not None else {}),
    }


def _sync_runtime_milestones(state: AutoTutorState, run: dict[str, Any]) -> dict[str, Any]:
    """Dual-write new legacy state-machine steps as sanitized v2 milestones."""
    from agent_runtime.event_store import get_run, list_run_events
    from agent_runtime.lifecycle import RuntimeRunController

    emitted = {
        int(event.data["autotutor_step_sequence"])
        for event in list_run_events(state.run_id or "", limit=500)
        if isinstance(event.data.get("autotutor_step_sequence"), int)
    }
    controller = RuntimeRunController.attach(state.run_id or "", policy_caller="auto_tutor")
    allowlisted_metadata = {
        "knowledge_point",
        "difficulty",
        "attempt",
        "is_correct",
        "adjustment",
        "replans",
        "generated_from",
        "wrote_memory",
    }
    current = run
    for step in state.runtime_steps:
        if step.sequence in emitted:
            continue
        metadata = {
            key: value
            for key, value in step.metadata.items()
            if key in allowlisted_metadata and isinstance(value, (str, int, float, bool, type(None)))
        }
        controller.event(
            "autotutor_milestone",
            public_payload={
                "autotutor_step_sequence": step.sequence,
                "step_id": step.step_id,
                "step_name": step.step_name,
                "event_type": step.event_type,
                "status": step.status,
                "latency_ms": step.latency_ms,
                "metadata": metadata,
            },
            step_id=step.step_id,
            operation=f"auto_tutor.{step.event_type}",
        )
        current = get_run(state.run_id or "")
    return current


def _autotutor_side_effect_ledger(state: AutoTutorState) -> list[dict[str, Any]]:
    if state.status != "completed" or not state.run_id:
        return []
    from agent_runtime.side_effect_store import get_side_effect

    record = get_side_effect(state.run_id, f"autotutor:{state.session_id}:finalize")
    if record is None or record.get("status") != "committed":
        return []
    return [{
        "step_id": record["step_id"],
        "operation": record["operation"],
        "idempotency_key": record["idempotency_key"],
        "status": record["status"],
        "resource_ref": record.get("resource_ref"),
    }]


def _start_runtime_run(state: AutoTutorState, *, actor_id: str | None, actor_role: str | None) -> None:
    if not state.run_id or state.status != "awaiting_answer":
        return
    from agent_runtime.context import RuntimeV2Settings

    settings = RuntimeV2Settings.from_env()
    active, _ = settings.rollout_decision("auto_tutor", str(actor_id or state.student_id))
    if not active or not settings.resumable_ready:
        # Database CAS/idempotency remains active as the safe legacy path. The
        # resumable Runtime only starts after artifact/checkpoint readiness is
        # explicitly enabled.
        state.run_id = None
        return
    from agent_runtime.checkpoint_store import save_checkpoint
    from agent_runtime.event_store import get_run
    from agent_runtime.lifecycle import RuntimeRunController
    from agent_runtime.models import AgentBudget, AgentContext, default_data_scope

    context = AgentContext(
        run_id=state.run_id,
        agent_type="auto_tutor",
        actor_id=actor_id,
        actor_role=(actor_role if actor_role in {"anonymous", "student", "teacher", "admin"} else "student"),
        student_id=state.student_id,
        session_id=state.session_id,
        trace_id=state.trace_id,
        data_scope=default_data_scope(),
        durability_mode="resumable",
        config_version=settings.config_version,
    )
    controller, run = RuntimeRunController.create(
        context,
        objective="AutoTutor 有界教学会话",
        budget=AgentBudget(max_steps=4, max_tool_calls=2, max_llm_calls=3, max_replans=1, max_wall_time_ms=300_000),
        policy_caller="auto_tutor",
        idempotency_key=f"autotutor:{state.session_id}",
        runtime_mode="shadow" if settings.shadow_mode else "active",
    )
    state.run_id = controller.run_id
    if run["status"] != "received":
        return
    plan = _autotutor_runtime_plan(state.session_id)
    controller.route({"agent_type": "auto_tutor"})
    controller.admit_plan(plan)
    controller.start_step("teach", "auto_tutor.teach", phase=state.phase)
    _sync_runtime_milestones(state, get_run(state.run_id))
    waiting = controller.wait_for_input(
        {"kind": "answer", "autotutor_revision": state.revision, "phase": state.phase},
        step_id="observe",
    )
    save_checkpoint(
        state.run_id,
        revision=get_run(state.run_id)["revision"],
        node_name="question_displayed",
        state=_autotutor_checkpoint_state(state, event_cursor=waiting.sequence),
    )


def _checkpoint_runtime_transition(state: AutoTutorState) -> bool:
    if not state.run_id:
        return False
    from agent_runtime.checkpoint_store import prune_terminal_checkpoints, save_checkpoint
    from agent_runtime.event_store import get_run
    from agent_runtime.lifecycle import RuntimeRunController
    from agent_runtime.completion import CompletionEvaluator

    try:
        run = get_run(state.run_id)
        controller = RuntimeRunController.attach(state.run_id, policy_caller="auto_tutor")
        if run["status"] in {"completed", "partial", "failed", "cancelled"}:
            return True
        if run["status"] == "waiting_input":
            controller.start_step("observe", "auto_tutor.observe_judge", autotutor_revision=state.revision)
            run = get_run(state.run_id)
        run = _sync_runtime_milestones(state, run)
        controller.event(
            "step_completed",
            public_payload={
                "step_id": "observe",
                "autotutor_revision": state.revision,
                "phase": state.phase,
                "status": state.status,
            },
            current_step_id="finalize" if state.status == "completed" else "observe",
        )
        current = get_run(state.run_id)
        if state.status == "completed":
            save_checkpoint(
                state.run_id,
                revision=current["revision"],
                node_name="finalize",
                state=_autotutor_checkpoint_state(state),
                side_effect_ledger=_autotutor_side_effect_ledger(state),
            )
            controller.event("verification_result", public_payload={"status": "teaching_evidence_recorded"}, next_status="verifying")
            decision = CompletionEvaluator().from_outcome(
                status="completed",
                completed_steps=4,
                total_steps=4,
                verification_status="not_required",
                reason_codes=["autotutor_finalized"],
            )
            controller.event("run_completed", public_payload={"completion": decision.model_dump()}, next_status="completed", completion=decision)
            prune_terminal_checkpoints(state.run_id)
        else:
            waiting = controller.wait_for_input(
                {"kind": "answer", "autotutor_revision": state.revision, "phase": state.phase},
                step_id="observe",
            )
            save_checkpoint(
                state.run_id,
                revision=get_run(state.run_id)["revision"],
                node_name="question_displayed",
                state=_autotutor_checkpoint_state(state, event_cursor=waiting.sequence),
            )
        return True
    except Exception:
        return False


def start_session(
    student_id: str,
    *,
    grade: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    account_status: str = "anonymous",
    traffic_cohort: str = "anonymous",
    data_scope: str = "runtime",
    rollout_eligible: bool = False,
    eligibility_reason: str = "anonymous_actor",
    internal_force_graph: bool = False,
    trace_id: str | None = None,
    focus_tags: list[str] | None = None,
    focus_reason: str | None = None,
    lesson_id: str | None = None,
    max_minutes: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    transition_started = perf_counter()
    content_gate = ContentGateSettings.from_env()
    if idempotency_key:
        existing = _load_start_idempotent_session(student_id, idempotency_key)
        if existing is not None:
            _store.cache(existing)
            replay = _public_state(existing)
            replay["idempotent_replay"] = True
            return replay
    if content_gate.kill_switch:
        raise AutoTutorUnavailableError("AutoTutor 内容安全开关已暂停新课程")
    trace_id = trace_id or current_trace_id() or uuid4().hex
    set_trace_id(trace_id)
    now = time.time()
    state = AutoTutorState(
        session_id=f"at_{uuid4().hex[:12]}",
        run_id=f"run_{uuid4().hex}",
        trace_id=trace_id,
        student_id=student_id,
        grade=grade,
        lesson_id=lesson_id,
        max_minutes=max(5, min(int(max_minutes or 12), 45)),
        content_gate_mode=content_gate.selected_mode(student_id),
        created_at=now,
        updated_at=now,
    )
    execution_context = _execution_context(
        actor_id=actor_id,
        actor_role=actor_role,
        account_status=account_status,
        traffic_cohort=traffic_cohort,
        data_scope=data_scope,
        rollout_eligible=rollout_eligible,
        eligibility_reason=eligibility_reason,
        internal_force_graph=internal_force_graph,
    )
    decision = select_executor(subject=actor_id or student_id, context=execution_context)
    state.executor_mode = decision.mode
    state.executor_assigned_mode = decision.mode
    state.executor_config_version = decision.config_version
    state.executor_bucket = decision.bucket
    state.executor_fallback_reason = decision.fallback_reason
    selected_outcome = _execute_selected_transition(
        state,
        transition_kind="start",
        command={"focus_tags": focus_tags or [], "focus_reason": focus_reason},
        context=execution_context,
        started_at=transition_started,
    )
    state = selected_outcome.next_state
    if state.status != "awaiting_answer":
        state.run_id = None
    elif state.run_id:
        from agent_runtime.context import RuntimeV2Settings

        runtime_settings = RuntimeV2Settings.from_env()
        runtime_active, _ = runtime_settings.rollout_decision("auto_tutor", str(actor_id or state.student_id))
        if not runtime_active or not runtime_settings.resumable_ready:
            state.run_id = None
    start_result = _public_state(state)
    _ensure_session_table()
    start_effects = AutoTutorTransitionEffects(
        session_id=state.session_id,
        claimed_revision=0,
        idempotency_key=idempotency_key or f"start:{state.session_id}",
        learning_events=list(state._pending_learning_events),
    )
    try:
        commit_autotutor_start(
            next_state=state,
            response=start_result,
            start_idempotency_key=idempotency_key,
            effects=start_effects,
        )
    except Exception:
        if idempotency_key:
            existing = _load_start_idempotent_session(student_id, idempotency_key)
            if existing is not None:
                _store.cache(existing)
                replay = _public_state(existing)
                replay["idempotent_replay"] = True
                return replay
        raise
    if state.run_id:
        try:
            _start_runtime_run(state, actor_id=actor_id, actor_role=actor_role)
        except Exception:
            pass
    _mirror_transition_trace(state, from_sequence=0)
    state._transition_active = False
    state._pending_learning_events.clear()
    state._pending_weakpoint_evidence.clear()
    state._pending_review_memory = None
    _store.cache(state)
    _record_executor_observation(
        state,
        transition_kind="start",
        context=execution_context,
        started_at=transition_started,
        outcome=selected_outcome,
    )
    return start_result


def submit_answer(
    session_id: str,
    answer: str,
    *,
    actor_id: str | None = None,
    actor_role: str | None = None,
    account_status: str = "anonymous",
    traffic_cohort: str = "anonymous",
    data_scope: str = "runtime",
    rollout_eligible: bool = False,
    eligibility_reason: str = "anonymous_actor",
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    # FastAPI runs this function in a threadpool. Serialize each session so two
    # rapid clicks cannot judge the same question twice or write duplicate events.
    with _store.session_lock(session_id):
        return _submit_answer_locked(
            session_id,
            answer,
            actor_id=actor_id,
            actor_role=actor_role,
            account_status=account_status,
            traffic_cohort=traffic_cohort,
            data_scope=data_scope,
            rollout_eligible=rollout_eligible,
            eligibility_reason=eligibility_reason,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )


def _answer_request_hash(session_id: str, revision: int, answer: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "session_id": session_id,
                "revision": revision,
                "answer": str(answer or "").strip().upper(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _completed_transition_replay(
    state: AutoTutorState,
    *,
    answer: str,
    expected_revision: int | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    if not idempotency_key:
        return _public_state(state)
    request_revision = expected_revision if expected_revision is not None else max(0, state.revision - 1)
    request_hash = _answer_request_hash(state.session_id, request_revision, answer)
    with get_connection() as conn:
        row = conn.execute(
            text("""SELECT last_idempotency_key, last_request_hash, last_response_json
                FROM autotutor_sessions WHERE session_id=:session_id"""),
            {"session_id": state.session_id},
        ).mappings().first()
    if row and row.get("last_idempotency_key") == idempotency_key:
        if row.get("last_request_hash") != request_hash:
            raise AutoTutorIdempotencyConflict("idempotency key payload conflict")
        if row.get("last_response_json"):
            replay = json.loads(row["last_response_json"])
            replay["idempotent_replay"] = True
            return replay
    return _public_state(state)


def _commit_claimed_answer_transition(
    state: AutoTutorState,
    *,
    claimed_revision: int,
    transition_key: str,
    request_hash: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    effects = AutoTutorTransitionEffects(
        session_id=state.session_id,
        claimed_revision=claimed_revision,
        idempotency_key=transition_key,
        learning_events=list(state._pending_learning_events),
        weakpoint_evidence=list(state._pending_weakpoint_evidence),
        review_memory=state._pending_review_memory,
        runtime_run_id=state.run_id if state.status == "completed" else None,
        runtime_finalize_key=(
            f"autotutor:{state.session_id}:finalize"
            if state.status == "completed" and state.run_id
            else None
        ),
    )
    committed = commit_autotutor_transition(
        previous_revision=claimed_revision,
        idempotency_key=transition_key,
        request_hash=request_hash,
        next_state=state,
        response=result,
        effects=effects,
    )
    state._transition_active = False
    state._pending_learning_events.clear()
    state._pending_weakpoint_evidence.clear()
    state._pending_review_memory = None
    if committed.status == "replayed" and committed.response is not None:
        replay = dict(committed.response)
        replay["idempotent_replay"] = True
        return replay
    if committed.status == "conflict":
        raise AutoTutorIdempotencyConflict("idempotency key payload conflict")
    if committed.status == "stale":
        latest = _load_persisted_session(state.session_id) or state
        stale = _public_state(latest)
        stale["stale_answer_ignored"] = True
        return stale
    _checkpoint_runtime_transition(state)
    _store.cache(state)
    return result


def _submit_answer_locked(
    session_id: str,
    answer: str,
    *,
    actor_id: str | None = None,
    actor_role: str | None = None,
    account_status: str = "anonymous",
    traffic_cohort: str = "anonymous",
    data_scope: str = "runtime",
    rollout_eligible: bool = False,
    eligibility_reason: str = "anonymous_actor",
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    transition_started = perf_counter()
    state = _load_persisted_session(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    if state.status == "completed":
        return _completed_transition_replay(
            state,
            answer=answer,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
    if state.status != "awaiting_answer" or state.phase == "content_blocked":
        return _public_state(state)
    claimed_revision = state.revision if expected_revision is None else expected_revision
    transition_key = idempotency_key or (
        f"answer:{session_id}:{claimed_revision}:"
        f"{hashlib.sha256(str(answer).encode('utf-8')).hexdigest()[:16]}"
    )
    request_hash = _answer_request_hash(session_id, claimed_revision, answer)
    claim_status, claim_payload = _claim_answer_transition(
        session_id,
        claimed_revision,
        transition_key,
        request_hash,
    )
    if claim_status == "missing":
        raise LookupError("autotutor session not found")
    if claim_status == "replayed":
        replay = dict(claim_payload or {})
        replay["idempotent_replay"] = True
        return replay
    if claim_status == "conflict":
        raise AutoTutorIdempotencyConflict("idempotency key payload conflict")
    if claim_status in {"stale", "busy"}:
        latest = _load_persisted_session(session_id) or state
        result = _public_state(latest)
        result["stale_answer_ignored"] = True
        result["transition_in_progress"] = claim_status == "busy"
        return result
    if not isinstance(claim_payload, AutoTutorState):
        raise RuntimeError("autotutor transition claim returned invalid state")
    state = claim_payload
    execution_context = _execution_context(
        actor_id=actor_id,
        actor_role=actor_role,
        account_status=account_status,
        traffic_cohort=traffic_cohort,
        data_scope=data_scope,
        rollout_eligible=rollout_eligible,
        eligibility_reason=eligibility_reason,
    )
    settings = AutoTutorExecutorSettings.from_env()
    if state.executor_mode == "graph_active" and settings.kill_switch:
        state.executor_mode = "legacy"
        state.executor_fallback_reason = "kill_switch_enabled"
    set_trace_id(state.trace_id)
    previous_sequence = max((step.sequence for step in state.runtime_steps), default=0)
    try:
        transition_kind: Literal["lesson_answer", "exit_ticket_answer"] = (
            "exit_ticket_answer" if state.phase == "exit_ticket" else "lesson_answer"
        )
        selected_outcome = _execute_selected_transition(
            state,
            transition_kind=transition_kind,
            command={"answer": (answer or "")[:1].upper(), "claimed_revision": claimed_revision},
            context=execution_context,
            started_at=transition_started,
        )
        state = selected_outcome.next_state
        result = selected_outcome.public_result
        committed_result = _commit_claimed_answer_transition(
            state,
            claimed_revision=claimed_revision,
            transition_key=transition_key,
            request_hash=request_hash,
            result=result,
        )
        _mirror_transition_trace(state, from_sequence=previous_sequence)
        _record_executor_observation(
            state,
            transition_kind=transition_kind,
            context=execution_context,
            started_at=transition_started,
            outcome=selected_outcome,
        )
        return committed_result
    except Exception:
        _release_answer_transition(
            session_id,
            expected_revision=claimed_revision,
            idempotency_key=transition_key,
            request_hash=request_hash,
        )
        raise


def _advance(state: AutoTutorState, ctx: ToolExecutionContext) -> None:
    """进入下一步；若已无教学步骤则先进入退出票检验，再 finalize。"""
    next_index = state.current_step_index + 1
    if next_index >= len(state.lesson_plan) or next_index >= MAX_STEPS:
        if state.phase == "lesson" and state.exit_ticket is None:
            _KERNEL_START_EXIT_TICKET(state, ctx)
        else:
            _KERNEL_FINALIZE(state)
        return
    state.current_step_index = next_index
    _emit(
        state,
        "next_step",
        "Next Step · 进入下一知识点",
        "plan",
        metadata={
            "step_index": next_index,
            "knowledge_point": state.lesson_plan[next_index].knowledge_point,
            "result_summary": f"进入第 {next_index + 1} 步：{state.lesson_plan[next_index].knowledge_point}",
        },
    )
    _KERNEL_ACT(state, state.lesson_plan[next_index], ctx)


def _mutate_answer_candidate(
    state: AutoTutorState,
    answer: str,
    ctx: ToolExecutionContext,
) -> tuple[bool, ReflectionRecord | None]:
    """Compatibility mutation used only by the observation provider on a private clone."""
    if state.phase == "exit_ticket":
        is_correct, _ = _KERNEL_SUBMIT_EXIT_TICKET(state, answer)
        _KERNEL_FINALIZE(state)
        return is_correct, None

    step = state.lesson_plan[state.current_step_index]
    step.attempts += 1
    is_correct, _ = _judge(step, answer)
    assessment = _assessment_from_question(step.question or {})
    feedback = build_answer_feedback(assessment, answer)
    state.answer_feedback = feedback
    step.practice_result = {
        "assessment_id": assessment.assessment_id,
        "objective_id": assessment.objective_id,
        "is_correct": is_correct,
        "selected_answer": feedback["selected_option"],
        "content_validation_status": step.content_validation.status if step.content_validation else "blocked",
    }
    state.step_history.append({
        "step_index": state.current_step_index,
        "knowledge_point": step.knowledge_point,
        "answer": (answer or "")[:1].upper(),
        "is_correct": is_correct,
        "attempt": step.attempts,
    })
    if is_correct:
        step.status = "practiced"
        state.mastery_delta[step.knowledge_point] = 0.0
        _KERNEL_ADVANCE(state, ctx)
        return True, None
    if step.attempts < MAX_ATTEMPTS_PER_STEP and state.replans < MAX_REPLANS:
        return False, _KERNEL_REFLECT(state, step, answer, ctx)
    step.status = "struggling"
    state.mastery_delta[step.knowledge_point] = -0.2
    _KERNEL_ADVANCE(state, ctx)
    return False, None


# Stable references let the v1.49.1 provider characterize external observations
# on a private clone while the Graph executor is independently tripwired against
# the public Legacy wrapper names.
_KERNEL_ACT = _act
_KERNEL_REFLECT = _reflect_and_replan
_KERNEL_START_EXIT_TICKET = _start_exit_ticket
_KERNEL_SUBMIT_EXIT_TICKET = _submit_exit_ticket_answer
_KERNEL_FINALIZE = _finalize
_KERNEL_ADVANCE = _advance
_KERNEL_MUTATE_ANSWER = _mutate_answer_candidate


def get_session(session_id: str) -> dict[str, Any]:
    state = _store.get(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    return _public_state(state)


def get_learning_assistant_handoff(session_id: str) -> AutoTutorAssistantHandoff:
    """Return an internal ownership envelope around a student-safe context."""
    state = _store.get(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    current = state.lesson_plan[state.current_step_index] if state.current_step_index < len(state.lesson_plan) else None
    if state.phase == "exit_ticket" and state.exit_ticket:
        context = AutoTutorAssistantContextPublic(
            autotutor_session_id=state.session_id,
            phase=state.phase,
            knowledge_point=state.exit_ticket.knowledge_point,
            difficulty=state.exit_ticket.question.get("difficulty") or state.exit_ticket.difficulty,
            teaching=None,
            question=state.exit_ticket.question.get("question"),
        )
        return AutoTutorAssistantHandoff(student_id=state.student_id, context=context)
    if current is None:
        raise LookupError("autotutor current step not found")
    teaching = current.teaching or {}
    public_teaching = PublicTeachingContext(
        explanation=str(teaching.get("explanation") or "")[:1200],
        key_points=[str(item)[:240] for item in (teaching.get("key_points") or [])[:8]],
        example=str(teaching.get("example"))[:600] if teaching.get("example") else None,
    ) if teaching else None
    context = AutoTutorAssistantContextPublic(
        autotutor_session_id=state.session_id,
        phase=state.phase,
        knowledge_point=current.knowledge_point,
        difficulty=(current.question or {}).get("difficulty") or current.difficulty,
        teaching=public_teaching,
        question=(current.question or {}).get("question"),
    )
    return AutoTutorAssistantHandoff(student_id=state.student_id, context=context)


def get_learning_assistant_context(session_id: str) -> dict[str, Any]:
    """Compatibility helper returning only the public context."""
    return get_learning_assistant_handoff(session_id).context.model_dump(mode="json")


def get_latest_session(student_id: str, *, include_completed: bool = False) -> dict[str, Any]:
    state = _load_latest_persisted_session(student_id, include_completed=include_completed)
    if state is None:
        raise LookupError("autotutor session not found")
    with _store._lock:
        _store._sessions[state.session_id] = state
        _store._timestamps[state.session_id] = time.time()
    return _public_state(state)
