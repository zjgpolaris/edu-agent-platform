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

import threading
import time
from time import perf_counter
from typing import Any, Iterator, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_config import llm_fast, llm_quality
from security.prompt_injection import build_untrusted_context_block
from structured_output import invoke_structured
from student_profile import LearningEvent, get_student_profile, try_record_learning_event
from services.weakpoint_service import delete_weakpoint, get_weakpoints, record_weakpoint
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


class AutoTutorState(BaseModel):
    session_id: str
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
    summary: str | None = None
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
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def save(self, state: AutoTutorState) -> None:
        with self._lock:
            self._cleanup_locked()
            self._sessions[state.session_id] = state
            self._timestamps[state.session_id] = time.time()

    def get(self, session_id: str) -> AutoTutorState | None:
        with self._lock:
            self._cleanup_locked()
            return self._sessions.get(session_id)

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, ts in self._timestamps.items() if now - ts > self._ttl]
        for sid in expired:
            self._sessions.pop(sid, None)
            self._timestamps.pop(sid, None)


_store = _SessionStore()


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


def _generate_plan(state: AutoTutorState, weakpoints: list[dict[str, Any]], profile: Any) -> list[LessonStep]:
    weak_topics = list(getattr(profile, "weak_topics", []) or [])
    recent_topics = list(getattr(profile, "recent_topics", []) or [])
    fallback_steps = _fallback_plan(weakpoints, weak_topics, recent_topics)

    weak_summary = "、".join(
        f"{w['knowledge_tag']}(错{w['wrong_count']}次)" for w in weakpoints[:8]
    ) or "（错题本为空）"
    prompt = [
        {
            "role": "system",
            "content": (
                "你是初中历史辅导 agent，需要为一个学生规划本节课。根据学生的薄弱知识点和近期主题，"
                f"产出最多 {MAX_STEPS} 个教学步骤的计划，按优先级排序（最薄弱的先教）。\n"
                "每步包含：knowledge_point（知识点）、difficulty（easy/medium/hard，错得多的从 easy 起）、"
                "strategy（一句话教学策略）、rationale（为何把它排在这个位置，要引用学情）。\n"
                "只输出 JSON：{\"lesson_plan\": [{\"knowledge_point\":\"\",\"difficulty\":\"easy\",\"strategy\":\"\",\"rationale\":\"\"}]}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"年级：{state.grade or '未知'}\n"
                f"错题本薄弱点：{weak_summary}\n"
                f"画像薄弱主题：{('、'.join(weak_topics[:6]) or '无')}\n"
                f"近期学习主题：{('、'.join(recent_topics[:6]) or '无')}\n"
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
# act：取材 + 出题
# --------------------------------------------------------------------------- #
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
    """对当前步骤取材（走工具治理）并出题。"""
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

    # 2) 出题
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

    step.strategy = f"先补讲：{reflection.explanation}" if reflection.adjustment == "reteach" else step.strategy
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
# finalize：落 memory + 错题进 SM-2 复习池
# --------------------------------------------------------------------------- #
def _finalize(state: AutoTutorState) -> None:
    finalize_started = perf_counter()
    mastered = [s.knowledge_point for s in state.lesson_plan if s.status == "mastered"]
    struggling = [s.knowledge_point for s in state.lesson_plan if s.status == "struggling"]

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
                # 已掌握 → 从错题本移除（接入 SM-2：下次复习不再出现）
                delete_weakpoint(state.student_id, tag)
            else:
                # 仍薄弱 → 记入/强化错题本，自动进入今日复习池
                record_weakpoint(state.student_id, tag, source="auto_tutor")
        except Exception:
            pass

    summary = (
        f"AutoTutor 本节课：掌握 {('、'.join(mastered) or '无')}；"
        f"仍需巩固 {('、'.join(struggling) or '无')}；触发 {state.replans} 次重规划。"
    )
    state.summary = summary
    # 课后记忆：本节课目标 + 结果
    record_typed_memory(
        state.student_id,
        memory_type="review_goal",
        content={"mastered": mastered, "struggling": struggling, "session_id": state.session_id},
        source_feature="auto_tutor",
        confidence=0.8,
        reason="AutoTutor 自主辅导课后小结，用于排下一次复习。",
        metadata={"replans": state.replans},
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
            "wrote_memory": True,
            "scheduled_review_tags": struggling,
            "result_summary": summary,
        },
    )
    state.status = "completed"


# --------------------------------------------------------------------------- #
# 对外 API：start / answer / get
# --------------------------------------------------------------------------- #
def _public_state(state: AutoTutorState) -> dict[str, Any]:
    current = state.lesson_plan[state.current_step_index] if state.current_step_index < len(state.lesson_plan) else None
    current_question = None
    if current and current.question and state.status == "awaiting_answer":
        # 不向前端泄露答案
        current_question = {
            "knowledge_point": current.knowledge_point,
            "difficulty": current.difficulty,
            "strategy": current.strategy,
            "question": current.question.get("question"),
            "options": current.question.get("options"),
            "step_index": state.current_step_index,
            "replanned": current.replanned,
        }
    return {
        "session_id": state.session_id,
        "trace_id": state.trace_id,
        "student_id": state.student_id,
        "grade": state.grade,
        "status": state.status,
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
        "runtime_steps": [s.model_dump() for s in state.runtime_steps],
    }


def start_session(
    student_id: str,
    *,
    grade: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    trace_id = trace_id or current_trace_id() or uuid4().hex
    set_trace_id(trace_id)
    now = time.time()
    state = AutoTutorState(
        session_id=f"at_{uuid4().hex[:12]}",
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
    if not state.grade:
        state.grade = getattr(profile, "grade", None)
    state.lesson_plan = _generate_plan(state, weakpoints, profile)
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
    _store.save(state)
    return _public_state(state)


def submit_answer(
    session_id: str,
    answer: str,
    *,
    actor_id: str | None = None,
    actor_role: str | None = None,
) -> dict[str, Any]:
    state = _store.get(session_id)
    if state is None:
        raise LookupError("autotutor session not found")
    if state.status == "completed":
        return _public_state(state)
    set_trace_id(state.trace_id)
    ctx = _tool_context(state.student_id, actor_id, actor_role)

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
        # 反思 + 重规划（带护栏）
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

    state.updated_at = time.time()
    _store.save(state)
    result = _public_state(state)
    if last_reflection is not None:
        result["reflection"] = last_reflection.model_dump()
    result["last_answer_correct"] = is_correct
    return result


def _advance(state: AutoTutorState, ctx: ToolExecutionContext) -> None:
    """进入下一步；若已无步骤则 finalize。"""
    next_index = state.current_step_index + 1
    if next_index >= len(state.lesson_plan) or next_index >= MAX_STEPS:
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
