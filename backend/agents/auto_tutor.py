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

from pydantic import BaseModel, Field
from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection
from llm_config import llm_fast, llm_quality
from security.prompt_injection import build_untrusted_context_block, evaluate_user_input
from structured_output import invoke_structured
from student_profile import LearningEvent, get_student_profile, try_record_learning_event
from services.weakpoint_service import delete_weakpoint, get_weakpoints, record_correct_evidence, record_weakpoint
from services.learning_preference_service import build_preference_prompt
from tools.base import ToolExecutionContext
from tools.registry import run_tool
from trace_store import current_trace_id, emit_trace_event, set_trace_id
from user_memory import record_typed_memory

AGENT_NAME = "auto_tutor"

# 防死循环 / 防失控护栏
MAX_STEPS = 4
MAX_REPLANS = 3
MAX_ATTEMPTS_PER_STEP = 3

Difficulty = Literal["easy", "medium", "hard"]
AdjustmentAction = Literal["reteach", "lower_difficulty", "change_example", "advance"]
SessionStatus = Literal["awaiting_answer", "completed"]
SessionPhase = Literal["lesson", "exit_ticket", "completed"]


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
    status: Literal["pending", "active", "mastered", "struggling"] = "pending"
    attempts: int = 0
    replanned: bool = False
    teaching: dict[str, Any] | None = None
    question: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


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


class ExitTicket(BaseModel):
    knowledge_point: str
    source_tag: str | None = None
    difficulty: Difficulty = "medium"
    strategy: str = "课后退出票检验"
    question: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    generated_from: Literal["struggling_step", "replanned_step", "mastered_step", "fallback"] = "fallback"


class ExitTicketResult(BaseModel):
    knowledge_point: str
    source_tag: str | None = None
    selected_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str = ""
    mastery_signal: Literal["exit_ticket_passed", "exit_ticket_failed"]


class EvidenceSummary(BaseModel):
    exit_ticket_recorded: bool = False
    learning_event_types: list[str] = Field(default_factory=list)
    weakpoint_action: str = "not_recorded"
    review_action: str = "not_scheduled"
    tutor_effectiveness_ready: bool = False


class AutoTutorState(BaseModel):
    session_id: str
    run_id: str | None = None
    trace_id: str
    student_id: str
    grade: str | None = None
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
    revision: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    _sequence: int = 0  # 内部：runtime step 递增序号（Pydantic v2 私有属性，不进 model_dump）


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
                    start_idempotency_key TEXT,
                    last_idempotency_key TEXT,
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
            "start_idempotency_key": "TEXT",
            "last_idempotency_key": "TEXT",
            "last_response_json": "TEXT",
        }
        for column_name, column_type in additions.items():
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE autotutor_sessions ADD COLUMN {column_name} {column_type}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autotutor_sessions_student_updated ON autotutor_sessions(student_id, updated_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_autotutor_sessions_run ON autotutor_sessions(run_id)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_autotutor_sessions_start_idempotency ON autotutor_sessions(student_id, start_idempotency_key)"))


def _restore_state(payload: dict[str, Any]) -> AutoTutorState:
    state = AutoTutorState.model_validate(payload)
    if state.status == "completed" and state.phase != "completed":
        # 兼容 v1.26 之前持久化的已完成会话（当时还没有 phase 字段）。
        state.phase = "completed"
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


def _claim_answer_transition(session_id: str, expected_revision: int, idempotency_key: str) -> tuple[str, AutoTutorState | dict[str, Any] | None]:
    """Atomically claim one answer transition before any judging side effect."""
    _ensure_session_table()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT state_json, revision, inflight_idempotency_key,
            last_idempotency_key, last_response_json FROM autotutor_sessions
            WHERE session_id=:session_id"""), {"session_id": session_id}).mappings().first()
        if not row:
            return "missing", None
        if row.get("last_idempotency_key") == idempotency_key and row.get("last_response_json"):
            return "replayed", json.loads(row["last_response_json"])
        state = _restore_state(json.loads(row["state_json"]))
        state.revision = int(row["revision"] or 0)
        if int(row["revision"] or 0) != expected_revision:
            return "stale", state
        claimed = conn.execute(text("""UPDATE autotutor_sessions
            SET inflight_idempotency_key=:idempotency_key, updated_at=:updated_at
            WHERE session_id=:session_id AND revision=:expected_revision
              AND (inflight_idempotency_key IS NULL OR inflight_idempotency_key='')"""), {
            "idempotency_key": idempotency_key,
            "updated_at": time.time(),
            "session_id": session_id,
            "expected_revision": expected_revision,
        })
        if claimed.rowcount != 1:
            return "busy", state
    return "claimed", state


def _complete_answer_transition(
    state: AutoTutorState,
    *,
    expected_revision: int,
    idempotency_key: str,
    response: dict[str, Any],
) -> bool:
    state.revision = expected_revision + 1
    state.updated_at = time.time()
    payload = state.model_dump()
    with get_connection() as conn:
        result = conn.execute(text("""UPDATE autotutor_sessions SET
            student_id=:student_id, trace_id=:trace_id, run_id=:run_id, status=:status,
            revision=revision+1, state_json=:state_json,
            inflight_idempotency_key=NULL, last_idempotency_key=:idempotency_key,
            last_response_json=:last_response_json, updated_at=:updated_at
            WHERE session_id=:session_id AND revision=:expected_revision
              AND inflight_idempotency_key=:idempotency_key"""), {
            "student_id": state.student_id,
            "trace_id": state.trace_id,
            "run_id": state.run_id,
            "status": state.status,
            "state_json": json.dumps(payload, ensure_ascii=False),
            "idempotency_key": idempotency_key,
            "last_response_json": json.dumps(response, ensure_ascii=False),
            "updated_at": state.updated_at,
            "session_id": state.session_id,
            "expected_revision": expected_revision,
        })
    return result.rowcount == 1


def _fail_answer_transition(session_id: str, *, expected_revision: int, idempotency_key: str, error: Exception) -> None:
    """Close an ambiguous transition so recovery never auto-replays its side effects."""
    response = {
        "session_id": session_id,
        "revision": expected_revision + 1,
        "transition_failed": True,
        "retryable": False,
        "error": {"code": "answer_transition_failed", "type": error.__class__.__name__},
    }
    with get_connection() as conn:
        conn.execute(text("""UPDATE autotutor_sessions SET
            revision=revision+1, inflight_idempotency_key=NULL,
            last_idempotency_key=:idempotency_key, last_response_json=:last_response_json,
            updated_at=:updated_at
            WHERE session_id=:session_id AND revision=:expected_revision
              AND inflight_idempotency_key=:idempotency_key"""), {
            "idempotency_key": idempotency_key,
            "last_response_json": json.dumps(response, ensure_ascii=False),
            "updated_at": time.time(),
            "session_id": session_id,
            "expected_revision": expected_revision,
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
    latency_ms = round((perf_counter() - started_at) * 1000, 2) if started_at is not None else None
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
    """无 LLM 时，直接从学生数据派生计划——换个学生权重不同，计划即不同。"""
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
        if len(steps) >= MAX_STEPS:
            break
    if not steps:
        steps.append(LessonStep(knowledge_point="鸦片战争", difficulty="easy", rationale="暂无学情，从近代史开篇切入。"))
    return steps


class _PlanItem(BaseModel):
    knowledge_point: str
    difficulty: Difficulty = "medium"
    strategy: str = "讲解关键史实后用一道选择题检验。"
    rationale: str = ""


class _PlanResponse(BaseModel):
    lesson_plan: list[_PlanItem]


def _match_source_tag(knowledge_point: str, candidate_tags: list[str]) -> str | None:
    """把（可能被 LLM 扩写的）知识点映射回错题本里的原始短标签，用于课后增删错题。"""
    best: str | None = None
    for tag in candidate_tags:
        tag = (tag or "").strip()
        if not tag:
            continue
        if tag in knowledge_point or knowledge_point in tag:
            if best is None or len(tag) > len(best):
                best = tag
    return best


def _generate_plan(state: AutoTutorState, weakpoints: list[dict[str, Any]], profile: Any, focus_tags: list[str] | None = None, focus_reason: str | None = None) -> list[LessonStep]:
    weak_topics = list(getattr(profile, "weak_topics", []) or [])
    recent_topics = list(getattr(profile, "recent_topics", []) or [])
    fallback_steps = _fallback_plan(weakpoints, weak_topics, recent_topics)

    weak_summary = "、".join(
        f"{w['knowledge_tag']}(错{w['wrong_count']}次)" for w in weakpoints[:8]
    ) or "（错题本为空）"
    focus_line = (
        f"\n本节课必须优先讲解（来自学生刚做错的作业）：{('、'.join(focus_tags))}，把它们排在计划最前。"
        if focus_tags else ""
    )
    # 来自错题本根因诊断的错因提示：让计划针对真实错因调整教学策略
    reason_line = (
        f"\n针对优先讲解知识点的错因诊断：{focus_reason}。"
        "请据此调整教学策略——概念模糊→重讲核心概念并举例；知识遗忘→先带背关键史实再检验；"
        "审题失误→强调圈画题干关键词；粗心大意→检验时提示复查。"
        if focus_reason else ""
    )

    # 注入学生偏好设置
    preference_prompt = build_preference_prompt(state.student_id)

    prompt = [
        {
            "role": "system",
            "content": (
                "你是初中历史辅导 agent，需要为一个学生规划本节课。根据学生的薄弱知识点和近期主题，"
                f"产出最多 {MAX_STEPS} 个教学步骤的计划，按优先级排序（最薄弱的先教）。\n"
                "每步包含：knowledge_point（知识点）、difficulty（easy/medium/hard，错得多的从 easy 起）、"
                "strategy（一句话教学策略）、rationale（为何把它排在这个位置，要引用学情）。\n"
                "只输出 JSON：{\"lesson_plan\": [{\"knowledge_point\":\"\",\"difficulty\":\"easy\",\"strategy\":\"\",\"rationale\":\"\"}]}"
                f"{preference_prompt}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"年级：{state.grade or '未知'}\n"
                f"错题本薄弱点：{weak_summary}\n"
                f"画像薄弱主题：{('、'.join(weak_topics[:6]) or '无')}\n"
                f"近期学习主题：{('、'.join(recent_topics[:6]) or '无')}\n"
                f"{focus_line}{reason_line}\n"
                "请生成本节课计划。"
            ),
        },
    ]
    try:
        result = invoke_structured(llm_quality, prompt, model=_PlanResponse, fallback=None)
    except Exception:
        result = None
    if not result or not result.lesson_plan:
        return fallback_steps
    candidate_tags = [w["knowledge_tag"] for w in weakpoints] + weak_topics
    steps = [
        LessonStep(
            knowledge_point=item.knowledge_point.strip(),
            source_tag=_match_source_tag(item.knowledge_point.strip(), candidate_tags),
            difficulty=item.difficulty,
            strategy=item.strategy.strip() or "讲解关键史实后用一道选择题检验。",
            rationale=item.rationale.strip(),
        )
        for item in result.lesson_plan[:MAX_STEPS]
        if item.knowledge_point.strip()
    ]
    return steps or fallback_steps


# --------------------------------------------------------------------------- #
# act：取材 + 教学 + 出题检验
# --------------------------------------------------------------------------- #
class _Teaching(BaseModel):
    explanation: str
    key_points: list[str] = Field(default_factory=list)
    example: str = ""


class _Question(BaseModel):
    question: str
    options: list[str]
    answer: str
    explanation: str


_DIFFICULTY_HINT = {
    "easy": "题目直接考查最核心的史实，选项区分度大。",
    "medium": "题目考查因果或意义，选项有一定迷惑性。",
    "hard": "题目考查比较、评价或综合分析。",
}


def _fallback_teaching(knowledge_point: str, strategy: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    snippets = [str(source.get("snippet") or "").strip() for source in sources[:2]]
    # A fallback must not echo a retrieved prompt-injection payload directly to
    # the student. Keep only source text that passes the same guardrail taxonomy.
    snippets = [snippet for snippet in snippets if snippet and not evaluate_user_input(snippet).blocked]
    factual_basis = snippets[0][:240] if snippets else f"先抓住「{knowledge_point}」的核心史实、原因与影响。"
    explanation = f"{factual_basis} 本轮采用的讲法是：{strategy}"
    return {
        "explanation": explanation,
        "key_points": [knowledge_point, "关键史实", "原因与影响"],
        "example": strategy,
    }


def _generate_teaching(step: LessonStep, sources: list[dict[str, Any]]) -> dict[str, Any]:
    context = build_untrusted_context_block(sources[:3], title="史料") if sources else ""
    prompt = [
        {
            "role": "system",
            "content": (
                "你是初中历史教师。先教学，再检验，不要直接出题。请根据史料和教学策略，"
                "用学生能理解的语言讲清指定知识点。解释控制在3-5句，列出2-3个关键点，并给一个帮助理解的例子或类比。"
                "只输出 JSON：{\"explanation\":\"\",\"key_points\":[\"\"],\"example\":\"\"}。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"知识点：{step.knowledge_point}\n难度：{step.difficulty}\n教学策略：{step.strategy}\n"
                f"这是第 {step.attempts + 1} 次教学，{'需要换一种讲法' if step.replanned else '首次讲解'}。\n{context}"
            ).strip(),
        },
    ]
    try:
        result = invoke_structured(llm_fast, prompt, model=_Teaching, fallback=None)
    except Exception:
        result = None
    if not result or not result.explanation.strip():
        return _fallback_teaching(step.knowledge_point, step.strategy, sources)
    return {
        "explanation": result.explanation.strip(),
        "key_points": [point.strip() for point in result.key_points[:3] if point.strip()],
        "example": result.example.strip(),
    }


def _fallback_question(knowledge_point: str) -> dict[str, Any]:
    return {
        "question": f"关于「{knowledge_point}」，下列说法最准确的是？",
        "options": [f"A. {knowledge_point}的基本史实", "B. 与史实不符的说法", "C. 张冠李戴的说法", "D. 完全无关的说法"],
        "answer": "A",
        "explanation": f"请复习「{knowledge_point}」的核心史实。",
        "knowledge_point": knowledge_point,
    }


def _generate_question(knowledge_point: str, difficulty: Difficulty, sources: list[dict[str, Any]]) -> dict[str, Any]:
    context = build_untrusted_context_block(sources[:3], title="史料") if sources else ""
    prompt = [
        {
            "role": "system",
            "content": (
                "你是初中历史教师，根据史料为指定知识点出一道四选一选择题。"
                f"{_DIFFICULTY_HINT.get(difficulty, '')}\n"
                "只输出 JSON：{\"question\":\"题干\",\"options\":[\"A. ..\",\"B. ..\",\"C. ..\",\"D. ..\"],"
                "\"answer\":\"A\",\"explanation\":\"1-2句解析\"}。answer 为正确选项字母。"
            ),
        },
        {
            "role": "user",
            "content": f"知识点：{knowledge_point}\n难度：{difficulty}\n{context}".strip(),
        },
    ]
    try:
        result = invoke_structured(llm_fast, prompt, model=_Question, fallback=None)
    except Exception:
        result = None
    if not result or len(result.options) < 2:
        return _fallback_question(knowledge_point)
    return {
        "question": result.question.strip(),
        "options": result.options,
        "answer": (result.answer.strip() or "A")[:1].upper(),
        "explanation": result.explanation.strip(),
        "knowledge_point": knowledge_point,
    }


def _act(state: AutoTutorState, step: LessonStep, ctx: ToolExecutionContext) -> None:
    """对当前步骤取材（走工具治理），先教学，再出题检验。"""
    step.status = "active"

    # 1) 取材 —— 通过工具注册表，带来审计 / 治理 / span
    tool_started = perf_counter()
    _emit(
        state,
        "tool_selection",
        "Tool Selection",
        "tool_selection",
        metadata={"tool_name": step.tool, "input_summary": {"query": step.knowledge_point, "k": 4}},
    )
    sources: list[dict[str, Any]] = []
    retrieval_ok = False
    retrieval_note = ""
    try:
        result = run_tool(
            "search_history_knowledge",
            {"query": step.knowledge_point, "grade": state.grade, "topic": step.knowledge_point, "k": 4},
            context=ctx,
        )
        if result.ok:
            sources = (result.data or {}).get("sources") or []
            retrieval_ok = bool(sources)
            retrieval_note = f"检索到 {len(sources)} 条史料" if sources else "知识库无相关史料，将基于模型自有知识出题"
        else:
            retrieval_note = (result.error.message if result.error else "检索不可用") + "，降级为模型自有知识出题"
        # 取材失败/无召回不是教学失败：agent 自适应地用模型知识继续。状态用 degraded 区分硬失败。
        retrieval_status = "success" if retrieval_ok else "degraded"
        _emit(
            state,
            "act_retrieval",
            "Act · 取材",
            "tool_result",
            retrieval_status,
            started_at=tool_started,
            metadata={
                "tool_name": "search_history_knowledge",
                "ok": result.ok,
                "source_count": len(sources),
                "degraded": not retrieval_ok,
                "result_summary": f"为「{step.knowledge_point}」{retrieval_note}",
                **{k: result.metadata.get(k) for k in ("risk_level", "side_effect", "required_role") if result.metadata},
            },
        )
    except Exception as exc:  # 取材异常不阻断教学，降级继续
        _emit(state, "act_retrieval", "Act · 取材", "tool_result", "degraded", started_at=tool_started,
              metadata={"tool_name": "search_history_knowledge", "degraded": True,
                        "result_summary": "史料检索不可用，降级为模型自有知识出题"},
              error={"message": str(exc)})

    step.sources = sources[:4]

    # 2) 先教学：首次讲解或反思后的重新讲解都形成独立 trace。
    teach_started = perf_counter()
    teaching = _generate_teaching(step, sources)
    step.teaching = teaching
    _emit(
        state,
        "reteach" if step.replanned else "teach",
        "Re-teach · 调整讲解" if step.replanned else "Teach · 知识讲解",
        "reteach" if step.replanned else "teach",
        started_at=teach_started,
        metadata={
            "knowledge_point": step.knowledge_point,
            "difficulty": step.difficulty,
            "strategy": step.strategy,
            "attempt": step.attempts + 1,
            "key_points": teaching.get("key_points") or [],
            "result_summary": str(teaching.get("explanation") or "")[:80],
        },
    )

    # 3) 出题检验
    q_started = perf_counter()
    question = _generate_question(step.knowledge_point, step.difficulty, sources)
    step.question = question
    _emit(
        state,
        "act_question",
        "Act · 出题",
        "act",
        started_at=q_started,
        metadata={
            "knowledge_point": step.knowledge_point,
            "difficulty": step.difficulty,
            "strategy": step.strategy,
            "result_summary": question["question"][:60],
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
    correct_letter = str(question.get("answer", "A")).strip()[:1].upper()
    given = (answer or "").strip()[:1].upper()
    is_correct = bool(given) and given == correct_letter
    return is_correct, correct_letter


# --------------------------------------------------------------------------- #
# reflect + re_plan
# --------------------------------------------------------------------------- #
class _Reflection(BaseModel):
    diagnosis: str
    adjustment: AdjustmentAction
    explanation: str


_DOWNGRADE = {"hard": "medium", "medium": "easy", "easy": "easy"}


def _reflect_and_replan(state: AutoTutorState, step: LessonStep, answer: str, ctx: ToolExecutionContext) -> ReflectionRecord:
    """学生答错 → 反思（讲错/超纲/粗心）→ 真实修改计划（补讲/降难度/换例子）。"""
    reflect_started = perf_counter()
    question = step.question or {}
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
                f"题目：{question.get('question', '')}\n正确答案：{question.get('answer', '')}\n"
                f"学生选择：{answer}\n本步已尝试次数：{step.attempts}"
            ),
        },
    ]
    fallback = _Reflection(
        diagnosis="学生答错，可能是讲解不够清晰或难度偏高。",
        adjustment="reteach",
        explanation=f"我们再梳理一下「{step.knowledge_point}」的核心史实，然后用一道更基础的题检验。",
    )
    try:
        reflection = invoke_structured(llm_quality, prompt, model=_Reflection, fallback=fallback)
    except Exception:
        reflection = fallback

    _emit(
        state,
        "reflect",
        "Reflect · 反思诊断",
        "reflect",
        started_at=reflect_started,
        metadata={
            "knowledge_point": step.knowledge_point,
            "diagnosis": reflection.diagnosis,
            "adjustment": reflection.adjustment,
            "result_summary": f"诊断：{reflection.diagnosis} → 调整：{reflection.adjustment}",
        },
    )

    # —— re_plan：真实修改计划 ——
    replan_started = perf_counter()
    state.replans += 1
    step.replanned = True
    changes: list[str] = []

    if reflection.adjustment in ("lower_difficulty", "reteach"):
        old = step.difficulty
        step.difficulty = _DOWNGRADE.get(step.difficulty, "easy")  # type: ignore[assignment]
        if step.difficulty != old:
            changes.append(f"当前步难度 {old}→{step.difficulty}")
        # 后续步骤同步降难度，体现"计划真实改变"
        for later in state.lesson_plan[state.current_step_index + 1:]:
            if later.difficulty == "hard":
                later.difficulty = "medium"
                changes.append(f"后续「{later.knowledge_point}」难度 hard→medium")

    if reflection.adjustment == "reteach":
        step.strategy = f"先补讲：{reflection.explanation}"
    elif reflection.adjustment == "change_example":
        step.strategy = f"换一个生活化例子重新解释：{reflection.explanation}"
    elif reflection.adjustment == "lower_difficulty":
        step.strategy = f"降低认知负担，先讲最基础史实：{reflection.explanation}"
    if not changes:
        changes.append("保持难度，换一道同知识点的题重新检验")

    _emit(
        state,
        "re_plan",
        "Re-plan · 调整计划",
        "re_plan",
        started_at=replan_started,
        metadata={
            "replans": state.replans,
            "adjustment": reflection.adjustment,
            "plan_changes": changes,
            "result_summary": "；".join(changes),
        },
    )

    # 重新取材出题（被调整后的难度）
    _act(state, step, ctx)

    record = ReflectionRecord(
        step_index=state.current_step_index,
        knowledge_point=step.knowledge_point,
        diagnosis=reflection.diagnosis,
        adjustment=reflection.adjustment,
        explanation=reflection.explanation,
    )
    state.reflect_log.append(record)
    return record


# --------------------------------------------------------------------------- #
# exit ticket：课后退出票检验
# --------------------------------------------------------------------------- #
def _select_exit_ticket_target(state: AutoTutorState) -> tuple[LessonStep | None, str]:
    for step in state.lesson_plan:
        if step.status == "struggling":
            return step, "struggling_step"
    for step in state.lesson_plan:
        if step.replanned:
            return step, "replanned_step"
    for step in state.lesson_plan:
        if step.status == "mastered":
            return step, "mastered_step"
    return (state.lesson_plan[0], "fallback") if state.lesson_plan else (None, "fallback")


def _start_exit_ticket(state: AutoTutorState, ctx: ToolExecutionContext) -> None:
    ticket_started = perf_counter()
    target, generated_from = _select_exit_ticket_target(state)
    if target is None:
        _finalize(state)
        return
    difficulty: Difficulty = "easy" if target.status == "struggling" else "medium"
    sources = target.sources[:4]
    question = _generate_question(target.knowledge_point, difficulty, sources)
    state.exit_ticket = ExitTicket(
        knowledge_point=target.knowledge_point,
        source_tag=target.source_tag,
        difficulty=difficulty,
        strategy="课后退出票检验：用一道迁移题确认本节辅导是否真正生效。",
        question=question,
        sources=sources,
        generated_from=generated_from,  # type: ignore[arg-type]
    )
    state.phase = "exit_ticket"
    state.status = "awaiting_answer"
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
            "difficulty": state.exit_ticket.difficulty,
            "generated_from": generated_from,
            "result_summary": f"为「{state.exit_ticket.knowledge_point}」生成课后退出票，等待学生完成最后检验",
        },
    )


def _submit_exit_ticket_answer(state: AutoTutorState, answer: str) -> tuple[bool, str]:
    if state.exit_ticket is None:
        raise RuntimeError("exit ticket not prepared")
    given = (answer or "").strip()[:1].upper()
    correct_letter = str(state.exit_ticket.question.get("answer", "A")).strip()[:1].upper()
    is_correct = bool(given) and given == correct_letter
    state.exit_ticket_result = ExitTicketResult(
        knowledge_point=state.exit_ticket.knowledge_point,
        source_tag=state.exit_ticket.source_tag,
        selected_answer=given,
        correct_answer=correct_letter,
        is_correct=is_correct,
        explanation=str(state.exit_ticket.question.get("explanation", "")),
        mastery_signal="exit_ticket_passed" if is_correct else "exit_ticket_failed",
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
            "result_summary": "退出票通过，记录掌握证据" if is_correct else "退出票未通过，回流错题与复习",
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
    mastered = [s.knowledge_point for s in state.lesson_plan if s.status == "mastered"]
    struggling = [s.knowledge_point for s in state.lesson_plan if s.status == "struggling"]
    event_types = ["auto_tutor_step"]

    for step in state.lesson_plan:
        if step.status not in ("mastered", "struggling"):
            continue
        success = step.status == "mastered"
        tag = step.source_tag or step.knowledge_point
        try_record_learning_event(
            LearningEvent(
                student_id=state.student_id,
                session_id=state.session_id,
                feature="auto_tutor",
                event_type="auto_tutor_step",
                grade=state.grade,
                topic=tag,
                success=success,
                score=1.0 if success else 0.0,
                metadata={"difficulty": step.difficulty, "attempts": step.attempts, "replanned": step.replanned},
            )
        )
        try:
            if success:
                # 答对累积掌握证据，连续答对达阈值才移出错题本（接入 SM-2）
                record_correct_evidence(state.student_id, tag)
            else:
                # 仍薄弱 → 记入/强化错题本，自动进入今日复习池
                record_weakpoint(state.student_id, tag, source="auto_tutor")
        except Exception:
            pass

    weakpoint_action = "not_recorded"
    review_action = "no_new_review_needed"
    exit_ticket_summary = "退出票未生成"
    if state.exit_ticket and state.exit_ticket_result:
        event_types.append("auto_tutor_exit_ticket")
        ticket_tag = state.exit_ticket.source_tag or state.exit_ticket.knowledge_point
        ticket_ok = state.exit_ticket_result.is_correct
        try_record_learning_event(
            LearningEvent(
                student_id=state.student_id,
                session_id=state.session_id,
                feature="auto_tutor",
                event_type="auto_tutor_exit_ticket",
                grade=state.grade,
                topic=ticket_tag,
                success=ticket_ok,
                score=1.0 if ticket_ok else 0.0,
                metadata={
                    "session_phase": "exit_ticket",
                    "difficulty": state.exit_ticket.difficulty,
                    "generated_from": state.exit_ticket.generated_from,
                    "replans": state.replans,
                    "selected_answer": state.exit_ticket_result.selected_answer,
                    "correct_answer": state.exit_ticket_result.correct_answer,
                },
            )
        )
        try:
            if ticket_ok:
                record_correct_evidence(state.student_id, ticket_tag)
                weakpoint_action = "correct_evidence_recorded"
            else:
                record_weakpoint(state.student_id, ticket_tag, source="auto_tutor_exit_ticket")
                weakpoint_action = "weakpoint_recorded"
                review_action = "weakpoint_added_to_review_pool"
        except Exception:
            weakpoint_action = "record_failed"
        exit_ticket_summary = f"退出票{'通过' if ticket_ok else '未通过'}：{state.exit_ticket.knowledge_point}"

    state.evidence = EvidenceSummary(
        exit_ticket_recorded=bool(state.exit_ticket_result),
        learning_event_types=event_types,
        weakpoint_action=weakpoint_action,
        review_action=review_action,
        tutor_effectiveness_ready=bool(state.exit_ticket_result),
    )

    summary = (
        f"AutoTutor 本节课：掌握 {('、'.join(mastered) or '无')}；"
        f"仍需巩固 {('、'.join(struggling) or '无')}；触发 {state.replans} 次重规划；{exit_ticket_summary}。"
    )
    state.summary = summary
    # 课后记忆：本节课目标 + 结果
    record_typed_memory(
        state.student_id,
        memory_type="review_goal",
        content={
            "mastered": mastered,
            "struggling": struggling,
            "session_id": state.session_id,
            "exit_ticket": state.exit_ticket_result.model_dump() if state.exit_ticket_result else None,
            "evidence": state.evidence.model_dump() if state.evidence else None,
        },
        source_feature="auto_tutor",
        confidence=0.85 if state.exit_ticket_result and state.exit_ticket_result.is_correct else 0.75,
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
def _public_state(state: AutoTutorState) -> dict[str, Any]:
    current = state.lesson_plan[state.current_step_index] if state.current_step_index < len(state.lesson_plan) else None
    current_question = None
    if state.phase == "exit_ticket" and state.exit_ticket and state.status == "awaiting_answer":
        current_question = {
            "kind": "exit_ticket",
            "knowledge_point": state.exit_ticket.knowledge_point,
            "difficulty": state.exit_ticket.difficulty,
            "strategy": state.exit_ticket.strategy,
            "question": state.exit_ticket.question.get("question"),
            "options": state.exit_ticket.question.get("options"),
            "step_index": len(state.lesson_plan),
            "replanned": False,
        }
    elif current and current.question and state.status == "awaiting_answer":
        # 不向前端泄露答案
        current_question = {
            "kind": "lesson",
            "knowledge_point": current.knowledge_point,
            "difficulty": current.difficulty,
            "strategy": current.strategy,
            "teaching": current.teaching,
            "question": current.question.get("question"),
            "options": current.question.get("options"),
            "step_index": state.current_step_index,
            "replanned": current.replanned,
        }
    return {
        "session_id": state.session_id,
        "run_id": state.run_id,
        "trace_id": state.trace_id,
        "student_id": state.student_id,
        "grade": state.grade,
        "status": state.status,
        "phase": state.phase,
        "revision": state.revision,
        "lesson_plan": [
            {
                "knowledge_point": s.knowledge_point,
                "source_tag": s.source_tag,
                "difficulty": s.difficulty,
                "strategy": s.strategy,
                "rationale": s.rationale,
                "status": s.status,
                "attempts": s.attempts,
                "replanned": s.replanned,
            }
            for s in state.lesson_plan
        ],
        "current_step_index": state.current_step_index,
        "current_question": current_question,
        "reflect_log": [r.model_dump() for r in state.reflect_log],
        "replans": state.replans,
        "summary": state.summary,
        "exit_ticket_result": state.exit_ticket_result.model_dump() if state.exit_ticket_result else None,
        "evidence": state.evidence.model_dump() if state.evidence else None,
        "runtime_steps": [s.model_dump() for s in state.runtime_steps],
    }


def _autotutor_runtime_plan():
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
            AgentStep(step_id="finalize", kind="control", operation="auto_tutor.finalize", depends_on=["observe"], side_effect="none", risk_level="low"),
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
    if state.status != "completed" or state.evidence is None:
        return []
    records: list[dict[str, Any]] = []
    for event_type in state.evidence.learning_event_types:
        records.append({
            "step_id": "finalize",
            "operation": f"learning_event.{event_type}",
            "idempotency_key": f"autotutor:{state.session_id}:{event_type}:{state.revision}",
            "status": "committed",
        })
    if state.evidence.weakpoint_action not in {"not_recorded", "record_failed"}:
        records.append({
            "step_id": "finalize",
            "operation": "weakpoint.update",
            "idempotency_key": f"autotutor:{state.session_id}:weakpoint:{state.revision}",
            "status": "committed",
        })
    records.append({
        "step_id": "finalize",
        "operation": "memory.record_review_goal",
        "idempotency_key": f"autotutor:{state.session_id}:memory:{state.revision}",
        "status": "committed",
    })
    return records


def _start_runtime_run(state: AutoTutorState, *, actor_id: str | None, actor_role: str | None) -> None:
    if not state.run_id:
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
    plan = _autotutor_runtime_plan()
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
    trace_id: str | None = None,
    focus_tags: list[str] | None = None,
    focus_reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if idempotency_key:
        existing = _load_start_idempotent_session(student_id, idempotency_key)
        if existing is not None:
            _store.cache(existing)
            replay = _public_state(existing)
            replay["idempotent_replay"] = True
            return replay
    trace_id = trace_id or current_trace_id() or uuid4().hex
    set_trace_id(trace_id)
    now = time.time()
    state = AutoTutorState(
        session_id=f"at_{uuid4().hex[:12]}",
        run_id=f"run_{uuid4().hex}",
        trace_id=trace_id,
        student_id=student_id,
        grade=grade,
        created_at=now,
        updated_at=now,
    )

    # plan
    plan_started = perf_counter()
    profile = get_student_profile(student_id)
    try:
        weakpoints = get_weakpoints(student_id)
    except Exception:
        weakpoints = []
    # 若调用方指定了 focus_tags（如来自作业错题），将这些 tag 提升到 weakpoints 列表最前面
    if focus_tags:
        focus_set = set(focus_tags)
        existing_tags = {w["knowledge_tag"] for w in weakpoints}
        extra = [{"knowledge_tag": t, "wrong_count": 1, "last_wrong_at": "", "source": "assignment"} for t in focus_tags if t not in existing_tags]
        weakpoints = [w for w in weakpoints if w["knowledge_tag"] in focus_set] + extra + [w for w in weakpoints if w["knowledge_tag"] not in focus_set]
    if not state.grade:
        state.grade = getattr(profile, "grade", None)
    state.lesson_plan = _generate_plan(state, weakpoints, profile, focus_tags=focus_tags, focus_reason=focus_reason)
    _emit(
        state,
        "plan",
        "Plan · 规划本节课",
        "plan",
        started_at=plan_started,
        metadata={
            "weakpoint_count": len(weakpoints),
            "targeted_points": [s.knowledge_point for s in state.lesson_plan],
            "plan": [{"knowledge_point": s.knowledge_point, "difficulty": s.difficulty, "rationale": s.rationale} for s in state.lesson_plan],
            "result_summary": "本节课计划：" + " → ".join(s.knowledge_point for s in state.lesson_plan),
        },
    )

    # act 第一步
    ctx = _tool_context(student_id, actor_id, actor_role)
    _act(state, state.lesson_plan[0], ctx)
    state.updated_at = time.time()
    _start_runtime_run(state, actor_id=actor_id, actor_role=actor_role)
    _store.cache(state)
    try:
        _persist_session(state, start_idempotency_key=idempotency_key)
    except Exception:
        if idempotency_key:
            existing = _load_start_idempotent_session(student_id, idempotency_key)
            if existing is not None:
                _store.cache(existing)
                replay = _public_state(existing)
                replay["idempotent_replay"] = True
                return replay
        raise
    return _public_state(state)


def submit_answer(
    session_id: str,
    answer: str,
    *,
    actor_id: str | None = None,
    actor_role: str | None = None,
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
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )


def _submit_answer_locked(
    session_id: str,
    answer: str,
    *,
    actor_id: str | None = None,
    actor_role: str | None = None,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    state = _load_persisted_session(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    if state.status == "completed":
        return _public_state(state)
    claimed_revision = state.revision if expected_revision is None else expected_revision
    if claimed_revision != state.revision:
        result = _public_state(state)
        result["stale_answer_ignored"] = True
        return result
    transition_key = idempotency_key or (
        f"answer:{session_id}:{claimed_revision}:"
        f"{hashlib.sha256(str(answer).encode('utf-8')).hexdigest()[:16]}"
    )
    claim_status, claim_payload = _claim_answer_transition(session_id, claimed_revision, transition_key)
    if claim_status == "missing":
        raise LookupError("autotutor session not found")
    if claim_status == "replayed":
        replay = dict(claim_payload or {})
        replay["idempotent_replay"] = True
        return replay
    if claim_status in {"stale", "busy"}:
        latest = _load_persisted_session(session_id) or state
        result = _public_state(latest)
        result["stale_answer_ignored"] = True
        result["transition_in_progress"] = claim_status == "busy"
        return result
    if not isinstance(claim_payload, AutoTutorState):
        raise RuntimeError("autotutor transition claim returned invalid state")
    state = claim_payload
    set_trace_id(state.trace_id)
    ctx = _tool_context(state.student_id, actor_id, actor_role)
    try:
        if state.phase == "exit_ticket":
            is_correct, _correct_letter = _submit_exit_ticket_answer(state, answer)
            _finalize(state)
            state.revision = claimed_revision + 1
            result = _public_state(state)
            result["last_answer_correct"] = is_correct
            if not _complete_answer_transition(state, expected_revision=claimed_revision, idempotency_key=transition_key, response=result):
                latest = _load_persisted_session(session_id) or state
                stale = _public_state(latest)
                stale["stale_answer_ignored"] = True
                return stale
            result["runtime_checkpoint_saved"] = _checkpoint_runtime_transition(state)
            _store.cache(state)
            return result

        step = state.lesson_plan[state.current_step_index]
        step.attempts += 1

        is_correct, correct_letter = _judge(step, answer)
        _emit(
            state,
            "judge",
            "Judge · 判分",
            "judge",
            "success" if is_correct else "failed",
            metadata={
                "knowledge_point": step.knowledge_point,
                "answer": (answer or "")[:1].upper(),
                "correct": correct_letter,
                "is_correct": is_correct,
                "attempt": step.attempts,
                "result_summary": "答对，进入下一步" if is_correct else "答错，触发反思",
            },
        )
        state.step_history.append(
            {
                "step_index": state.current_step_index,
                "knowledge_point": step.knowledge_point,
                "answer": (answer or "")[:1].upper(),
                "is_correct": is_correct,
                "attempt": step.attempts,
            }
        )

        last_reflection: ReflectionRecord | None = None
        if is_correct:
            step.status = "mastered"
            state.mastery_delta[step.knowledge_point] = round(0.3 if step.replanned else 0.4, 2)
            _advance(state, ctx)
        else:
            if step.attempts < MAX_ATTEMPTS_PER_STEP and state.replans < MAX_REPLANS:
                last_reflection = _reflect_and_replan(state, step, answer, ctx)
            else:
                step.status = "struggling"
                state.mastery_delta[step.knowledge_point] = -0.2
                _emit(
                    state,
                    "give_up_step",
                    "Re-plan · 标记薄弱并前进",
                    "re_plan",
                    metadata={
                        "knowledge_point": step.knowledge_point,
                        "reason": "已达单步重试上限或全局重规划上限",
                        "result_summary": f"「{step.knowledge_point}」仍未掌握，记入错题本，继续下一步",
                    },
                )
                _advance(state, ctx)

        state.revision = claimed_revision + 1
        result = _public_state(state)
        if last_reflection is not None:
            result["reflection"] = last_reflection.model_dump()
        result["last_answer_correct"] = is_correct
        if not _complete_answer_transition(state, expected_revision=claimed_revision, idempotency_key=transition_key, response=result):
            latest = _load_persisted_session(session_id) or state
            stale = _public_state(latest)
            stale["stale_answer_ignored"] = True
            return stale
        result["runtime_checkpoint_saved"] = _checkpoint_runtime_transition(state)
        _store.cache(state)
        return result
    except Exception as exc:
        _fail_answer_transition(session_id, expected_revision=claimed_revision, idempotency_key=transition_key, error=exc)
        raise


def _advance(state: AutoTutorState, ctx: ToolExecutionContext) -> None:
    """进入下一步；若已无教学步骤则先进入退出票检验，再 finalize。"""
    next_index = state.current_step_index + 1
    if next_index >= len(state.lesson_plan) or next_index >= MAX_STEPS:
        if state.phase == "lesson" and state.exit_ticket is None:
            _start_exit_ticket(state, ctx)
        else:
            _finalize(state)
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
    _act(state, state.lesson_plan[next_index], ctx)


def get_session(session_id: str) -> dict[str, Any]:
    state = _store.get(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    return _public_state(state)


def get_learning_assistant_context(session_id: str) -> dict[str, Any]:
    """Return an allowlisted public teaching context; never expose answers."""
    state = _store.get(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    current = state.lesson_plan[state.current_step_index] if state.current_step_index < len(state.lesson_plan) else None
    if state.phase == "exit_ticket" and state.exit_ticket:
        return {
            "student_id": state.student_id,
            "autotutor_session_id": state.session_id,
            "phase": state.phase,
            "knowledge_point": state.exit_ticket.knowledge_point,
            "difficulty": state.exit_ticket.difficulty,
            "strategy": state.exit_ticket.strategy,
            "teaching": None,
            "question": state.exit_ticket.question.get("question"),
            "return_path": "/student/auto-tutor",
        }
    if current is None:
        raise LookupError("autotutor current step not found")
    return {
        "student_id": state.student_id,
        "autotutor_session_id": state.session_id,
        "phase": state.phase,
        "knowledge_point": current.knowledge_point,
        "difficulty": current.difficulty,
        "strategy": current.strategy,
        "teaching": current.teaching,
        "question": (current.question or {}).get("question"),
        "return_path": "/student/auto-tutor",
    }


def get_latest_session(student_id: str, *, include_completed: bool = False) -> dict[str, Any]:
    state = _load_latest_persisted_session(student_id, include_completed=include_completed)
    if state is None:
        raise LookupError("autotutor session not found")
    with _store._lock:
        _store._sessions[state.session_id] = state
        _store._timestamps[state.session_id] = time.time()
    return _public_state(state)
