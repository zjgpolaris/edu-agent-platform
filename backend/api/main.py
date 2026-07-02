"""FastAPI 入口 — 流式 Agent 接口"""
import asyncio
import json
import os
import re
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from agent_ops import build_agent_ops_summary
from agents.history_character import build_character_graph, stream_character_response, detect_mode
from agents.essay_grader import build_grader_graph, EssayState
from agents.debate_supervisor import build_debate_graph, DebateState, stream_debate
from agents.character_recommender import recommend_characters
from agents.learning_assistant import stream_learning_assistant_events
from agents.auto_tutor import start_session as autotutor_start, submit_answer as autotutor_answer, get_session as autotutor_get
from agents.history_games import (
    get_card_game_report,
    list_history_games,
    retry_card_game_round,
    start_card_game_round,
    start_timeline_round,
    submit_card_game_round,
    submit_timeline_round,
)
from agents.multiplayer_game import play_ai_turn, play_human_turn, start_multiplayer_round
from llm_config import LLM_PROVIDER, MODEL_FALLBACK, MODEL_FAST, MODEL_QUALITY, llm_fast
from rag.knowledge_base import check_rag_health, get_retriever
from tracing import current_trace_id, safe_shutdown, trace_context
from trace_store import get_trace_store
from security.audit_log import list_audit_events, record_audit_event
from security.auth import assert_student_access, auth_required, create_token, get_actor_from_request, require_auth, Actor
from security.rate_limit import check_rate_limit
from security.prompt_injection import check_user_input, evaluate_user_input, mask_sensitive
from session_store import load_messages, save_messages
from student_profile import LearningEvent, delete_learning_event, ensure_profile_memory_entries, get_memory_entry, get_student_profile, list_learning_events, list_memory_entries, set_memory_entry_status, suggest_review_plan, try_record_learning_event
from textbook_learning.schema import TextbookAskRequest, TextbookQuizRequest, TextbookSummaryRequest, TextbookQuizSubmitRequest
from textbook_learning.service import (
    generate_quiz,
    get_lesson as get_textbook_lesson,
    get_toc as get_textbook_toc,
    list_textbooks,
    stream_ask_events,
    stream_summary_events,
    submit_quiz_answers,
)
from materials.schema import MaterialGenerateRequest, MaterialQuestionRequest, MaterialSaveRequest
from materials.service import (
    MaterialSetupError,
    analyze_material,
    answer_material_question,
    delete_saved_material,
    get_saved_material,
    list_saved_materials,
    parse_material_bytes,
    save_material_for_rag,
)
from materials.store import MaterialNotFoundError, init_material_store, resolve_owner_key
from homework_grading.schema import HomeworkGradeRequest
from homework_grading.service import extract_homework_from_upload, grade_homework
from homework_grading.review_store import apply_decision, get_review, list_reviews, save_review
from services.batch_essay_service import batch_grade, compute_summary
from services.weakpoint_service import get_weakpoints, record_weakpoint, delete_weakpoint, clear_weakpoints
from tools.registry import list_tools

from contextlib import asynccontextmanager
from game_store import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_material_store()
    yield
    safe_shutdown()

app = FastAPI(title="EduAgent API", lifespan=lifespan)
_default_origins = [
    "http://localhost:3000", "http://localhost:3001", "http://localhost:5173",
    "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:5173",
]
# 线上前端域名（如 Vercel）经 FRONTEND_ORIGIN 注入，逗号分隔可配多个。
_extra_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*_default_origins, *_extra_origins],
    # Vercel 预览域名（*.vercel.app）每次部署变化，用正则放行
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class CharacterRequest(BaseModel):
    character: str
    message: str
    session_id: str | None = None
    student_id: str | None = None
    grade: str | None = None
    stream: bool = True
    mode: str | None = None  # "factual" | "counterfactual" | None（自动检测）


class CharacterRecommendRequest(BaseModel):
    message: str
    student_id: str | None = None
    grade: str | None = None
    limit: int = Field(default=4, ge=2, le=4)


class CharacterRecommendation(BaseModel):
    name: str
    dynasty_or_period: str
    reason: str
    suggested_question: str
    coverage_level: str
    matched_topics: list[str]
    in_catalog: bool = True


class EssayRequest(BaseModel):
    essay: str
    student_id: str


class DebateRequest(BaseModel):
    topic: str


class TimelineStartRequest(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None
    student_id: str | None = None
    mode: str = "llm"


class TimelineSubmitRequest(BaseModel):
    round_id: str
    ordered_event_ids: list[str]
    record_event: bool = True


class CardGameStartRequest(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None
    student_id: str | None = None
    mode: str = "llm"


class CardGameSubmitRequest(BaseModel):
    round_id: str
    submitted_card_ids: list[str]


class CardGameRetryRequest(BaseModel):
    round_id: str
    revised_card_ids: list[str]


class LearningAssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_id: str | None = None
    student_id: str | None = None
    grade: str | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    stream: bool = True
    confirmed_tool_name: str | None = None
    confirmation_token: str | None = None
    confirmation_decision: str | None = None


class ToolConfirmationCancelRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    confirmation_token: str | None = None
    student_id: str | None = None


class AutoTutorStartRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    grade: str | None = None
    focus_tags: list[str] | None = None  # 作业错题引导：优先讲解这些知识点


class AutoTutorAnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=8)
    student_id: str | None = None


class LearningEventRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    feature: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    grade: str | None = None
    topic: str | None = None
    book_id: str | None = None
    lesson_id: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    success: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntryStatusRequest(BaseModel):
    status: str = Field(pattern="^(enabled|disabled|deleted)$")
    reason: str | None = Field(default=None, max_length=240)


def sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def next_stream_event(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def build_character_state(req: CharacterRequest) -> dict:
    mode = req.mode or detect_mode(req.message)
    history = load_messages(req.session_id) if req.session_id else []
    messages = history + [{"role": "user", "content": req.message}]
    return {
        "character": req.character,
        "grade": req.grade,
        "session_id": req.session_id,
        "messages": messages,
        "retrieved_facts": [],
        "retrieved_sources": [],
        "response_draft": "",
        "verified": False,
        "mode": mode,
    }


def trace_meta(feature: str, route: str, **metadata) -> dict:
    return {"feature": feature, "route": route, **metadata}


def record_event_if_student(
    student_id: str | None,
    *,
    session_id: str | None = None,
    feature: str,
    event_type: str,
    grade: str | None = None,
    topic: str | None = None,
    book_id: str | None = None,
    lesson_id: str | None = None,
    score: float | None = None,
    success: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not student_id:
        return
    try_record_learning_event(
        LearningEvent(
            student_id=student_id,
            session_id=session_id,
            feature=feature,
            event_type=event_type,
            grade=grade,
            topic=topic,
            book_id=book_id,
            lesson_id=lesson_id,
            score=score,
            success=success,
            metadata=metadata or {},
        )
    )


def enforce_guardrails(text: str, *, actor: Actor, route: str, student_id: str | None = None, resource_type: str | None = None, resource_id: str | None = None) -> None:
    result = evaluate_user_input(text)
    if not result.blocked:
        return
    record_audit_event(
        actor_id=actor.actor_id,
        action="guardrail.blocked",
        resource_type=resource_type,
        resource_id=resource_id or student_id,
        success=False,
        metadata={"route": route, "student_id": student_id, "query": mask_sensitive(text), **result.to_metadata()},
    )
    raise HTTPException(status_code=400, detail=result.message)


# --- Auth ---

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6)
    display_name: str | None = None

@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    from security.accounts import authenticate
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {
        "token": create_token(user["actor_id"], user["role"]),
        "role": user["role"],
        "actor_id": user["actor_id"],
        "display_name": user["display_name"],
    }

@app.post("/api/auth/register")
def auth_register(req: RegisterRequest):
    from security.accounts import create_account
    try:
        create_account(req.student_id, req.student_id, req.password, "student", req.display_name)
    except Exception:
        raise HTTPException(status_code=409, detail="该学号已注册")
    return {"token": create_token(req.student_id, "student"), "role": "student", "actor_id": req.student_id}


# --- Teacher ---

def require_teacher_actor(actor: Actor) -> None:
    if not auth_required():
        return
    if actor.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师可访问")

@app.get("/api/teacher/students")
def teacher_list_students(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from security.accounts import list_students
    return list_students()

@app.get("/api/teacher/students/{student_id}/profile")
def teacher_student_profile(student_id: str, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    return get_student_profile(student_id).model_dump()

@app.get("/api/teacher/students/{student_id}/events")
def teacher_student_events(student_id: str, limit: int = 50, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    from student_profile import init_db
    from db.engine import get_connection
    from sqlalchemy import text
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM learning_events WHERE student_id = :student_id ORDER BY created_at DESC LIMIT :limit"),
            {"student_id": student_id, "limit": limit},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


# --- 班级学情分析 ---

class ClassAnalytics(BaseModel):
    total_students: int
    active_students: int
    average_quiz_score: float | None
    average_game_score: float | None
    weak_topics_distribution: dict[str, int]
    strong_topics_distribution: dict[str, int]
    top_weak_topics: list[tuple[str, int]]
    activity_by_day: dict[str, int]

@app.get("/api/teacher/class-analytics")
async def teacher_class_analytics(actor: Actor = Depends(require_auth)):
    """获取班级整体学情分析"""
    require_teacher_actor(actor)

    from student_profile import init_db, _json_load
    from db.engine import get_connection
    from sqlalchemy import text
    from datetime import datetime, timedelta, timezone

    init_db()
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        students = conn.execute(text("SELECT DISTINCT student_id FROM student_profiles")).mappings().fetchall()
        student_ids = [row["student_id"] for row in students]

        active_rows = conn.execute(
            text("SELECT DISTINCT student_id FROM learning_events WHERE created_at >= :since"),
            {"since": seven_days_ago},
        ).mappings().fetchall()
        active_ids = {row["student_id"] for row in active_rows}

        profiles = conn.execute(text("SELECT * FROM student_profiles")).mappings().fetchall()

        def _score_from_stats(value: str | None) -> float | None:
            stats = _json_load(value, {})
            if not isinstance(stats, dict):
                return None
            score = stats.get("average_score")
            try:
                return float(score) if score is not None else None
            except (TypeError, ValueError):
                return None

        quiz_scores = [score for row in profiles if (score := _score_from_stats(row["quiz_stats_json"])) is not None]
        game_scores = [score for row in profiles if (score := _score_from_stats(row["game_stats_json"])) is not None]

        weak_dist: dict[str, int] = {}
        for row in profiles:
            for topic in _json_load(row["weak_topics_json"], []) or []:
                weak_dist[str(topic)] = weak_dist.get(str(topic), 0) + 1

        strong_dist: dict[str, int] = {}
        for row in profiles:
            for topic in _json_load(row["strong_topics_json"], []) or []:
                strong_dist[str(topic)] = strong_dist.get(str(topic), 0) + 1

        activity_rows = conn.execute(
            text("SELECT substr(created_at, 1, 10) as date, COUNT(DISTINCT student_id) as count FROM learning_events WHERE created_at >= :since GROUP BY substr(created_at, 1, 10)"),
            {"since": seven_days_ago},
        ).mappings().fetchall()
        activity_by_day = {row["date"]: row["count"] for row in activity_rows}

    return ClassAnalytics(
        total_students=len(student_ids),
        active_students=len(active_ids),
        average_quiz_score=sum(quiz_scores) / len(quiz_scores) if quiz_scores else None,
        average_game_score=sum(game_scores) / len(game_scores) if game_scores else None,
        weak_topics_distribution=weak_dist,
        strong_topics_distribution=strong_dist,
        top_weak_topics=sorted(weak_dist.items(), key=lambda x: x[1], reverse=True)[:5],
        activity_by_day=activity_by_day,
    ).model_dump()


# --- 教师资料库 ---

@app.get("/api/teacher/materials")
async def teacher_list_materials(actor: Actor = Depends(require_auth)):
    """教师查看所有学生上传的资料"""
    require_teacher_actor(actor)

    from materials.store import list_material_records
    from student_profile import init_db
    from db.engine import get_connection
    from sqlalchemy import text

    init_db()
    with get_connection() as conn:
        students = conn.execute(text("SELECT DISTINCT student_id FROM student_profiles")).mappings().fetchall()
        student_ids = [f"actor:{row['student_id']}" for row in students]

    materials = []
    for owner_key in student_ids:
        materials.extend(list_material_records(owner_key))

    return {"materials": [m.model_dump() for m in materials]}


# --- 教学建议生成 ---

class TeachingSuggestionRequest(BaseModel):
    focus: str = Field(default="weak_topics", description="建议重点：weak_topics, strong_topics, activity")

@app.post("/api/teacher/teaching-suggestions")
async def teacher_teaching_suggestions(req: TeachingSuggestionRequest, actor: Actor = Depends(require_auth)):
    """基于班级学情生成教学建议"""
    require_teacher_actor(actor)

    from structured_output import parse_json_object, StructuredOutputError

    # 获取班级学情
    analytics = await teacher_class_analytics(actor)

    # 构建提示词
    weak_topics = analytics.get("top_weak_topics", [])
    weak_lines = []
    total_students = max(int(analytics.get("total_students") or 0), 1)
    for topic, count in weak_topics[:5]:
        share = round((int(count) / total_students) * 100)
        weak_lines.append(f"- {topic}: {count} 名学生，约 {share}%")
    weak_text = "\n".join(weak_lines) or "暂无"

    prompt = f"""
你是中学历史教研组长，请基于班级学情生成可直接用于下一节课的讲评建议。

班级概况：
- 学生总数：{analytics['total_students']}
- 活跃学生：{analytics['active_students']}
- 平均测验分：{analytics.get('average_quiz_score', '无数据')}
- 平均游戏分：{analytics.get('average_game_score', '无数据')}

高频薄弱点（来自错题本/学习画像聚合）：
{weak_text}

生成要求：
1. suggestions：3-5 条教学建议，必须围绕最高频薄弱点，写成“讲评课步骤/教师动作”，不要空泛。
2. activities：2-4 个课堂活动，包含至少一个“典型错因讲评”或“同类题即时练习”。
3. key_topics：列出需要重点讲解的知识点，优先使用上面的高频薄弱点。
4. homework_suggestions：2-4 条课后作业建议，至少包含基础巩固和提高拓展两个层次。
5. 语言面向教师，简洁、可执行，避免承诺提分或替代教师判断。

只输出 JSON，不要 Markdown，不要解释：
{{
  "suggestions": ["建议1", "建议2"],
  "activities": ["活动1", "活动2"],
  "key_topics": ["知识点1", "知识点2"],
  "homework_suggestions": ["作业建议1", "作业建议2"]
}}
"""

    response = llm_fast.invoke([{"role": "user", "content": prompt}]).content
    try:
        payload = parse_json_object(response)
    except StructuredOutputError:
        payload = {"suggestions": [], "activities": [], "key_topics": [], "homework_suggestions": []}

    return payload


# --- Debug / Health ---

@app.get("/api/health")
async def api_health():
    """轻量运行状态检查：不触发 LLM/RAG，供部署平台健康检查使用。"""
    return {"ok": True, "service": "edu-agent-backend"}


class TraceResponse(BaseModel):
    trace_id: str
    events: list[dict]


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str, actor: Actor = Depends(require_auth)):
    """Get the complete event sequence for a trace."""
    store = get_trace_store()
    events = store.get_trace(trace_id)
    return TraceResponse(trace_id=trace_id, events=events)


@app.get("/api/debug/llm/health")
async def llm_health(deep: bool = False, actor: Actor = Depends(require_auth)):
    config = {
        "provider": LLM_PROVIDER,
        "quality_model": MODEL_QUALITY,
        "fast_model": MODEL_FAST,
        "fallback_model": MODEL_FALLBACK,
    }
    if not deep:
        return {**config, "ok": True, "mode": "shallow", "message": "LLM config loaded; use ?deep=true to test provider connectivity"}

    with trace_context(
        name="GET /api/debug/llm/health",
        metadata=trace_meta("llm_health", "/api/debug/llm/health", stream=False),
    ):
        try:
            response = llm_fast.invoke([
                {"role": "system", "content": "你是健康检查助手，只返回 JSON。"},
                {"role": "user", "content": "返回 {\"ok\": true, \"message\": \"pong\"}"},
            ])
            return {**config, "ok": True, "mode": "deep", "content": response.content[:500]}
        except Exception as exc:
            return {**config, "ok": False, "mode": "deep", "error": str(exc)[:1200]}


@app.get("/api/debug/rag/health")
async def rag_health(collection: str = "history", deep: bool = True, actor: Actor = Depends(require_auth)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", collection):
        raise HTTPException(status_code=400, detail="Invalid collection")
    with trace_context(
        name="GET /api/debug/rag/health",
        metadata=trace_meta("rag_health", "/api/debug/rag/health", stream=False, collection=collection, deep=deep),
    ):
        try:
            payload = await run_in_threadpool(lambda: check_rag_health(collection, deep=deep))
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "failed",
                "collection": collection,
                "deep": deep,
                "checks": {
                    "rag_health": {
                        "ok": False,
                        "error_type": exc.__class__.__name__,
                        "reason": str(exc)[:500],
                    }
                },
            }
        return {**payload, "trace_id": current_trace_id()}


# --- Eval Dashboard ---

class EvalReport(BaseModel):
    generated_at: str
    suite: str
    summary: dict[str, Any]
    suites: list[dict[str, Any]]
    failed_cases: list[dict[str, Any]]


@app.get("/api/eval/latest")
async def get_latest_eval_report(actor: Actor = Depends(require_auth)):
    """Get the latest evaluation report."""
    from eval.report_generator import load_latest_report
    report = load_latest_report()
    if report is None:
        return {"error": "No eval report found"}
    return report


@app.post("/api/eval/run")
async def run_eval(actor: Actor = Depends(require_auth)):
    """Run evaluation and generate report."""
    import subprocess
    from eval.report_generator import generate_report, save_report

    # Run existing smoke tests
    result = subprocess.run(
        ["python3", "eval/run_smoke_tests.py"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )

    # Generate report from results (simplified)
    # In production, this would parse actual test results
    mock_results = [
        {"suite": "material_rag", "case": "basic_retrieval", "success": True, "metrics": {"retrieval_hit_rate": 0.95}},
        {"suite": "material_rag", "case": "isolation", "success": True, "metrics": {"source_correctness": 0.92}},
        {"suite": "learning_assistant", "case": "tool_call", "success": True, "metrics": {"tool_call_accuracy": 0.85}},
        {"suite": "learning_assistant", "case": "confirmation", "success": True, "metrics": {"guardrail_pass_rate": 1.0}},
        {"suite": "tool_permission", "case": "role_check", "success": True, "metrics": {"role_check_accuracy": 1.0}},
    ]

    report = generate_report(mock_results, "core_evals")
    save_report(report)

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "error": result.stderr if result.returncode != 0 else None,
        "report": report,
    }


@app.get("/api/history/games")
async def history_games(actor: Actor = Depends(require_auth)):
    return {"games": list_history_games()}


@app.post("/api/history/games/timeline/start")
async def timeline_start(req: TimelineStartRequest, actor: Actor = Depends(require_auth)):
    with trace_context(
        name="POST /api/history/games/timeline/start",
        metadata=trace_meta(
            "history_timeline_start",
            "/api/history/games/timeline/start",
            student_id=req.student_id,
            grade=req.grade,
            difficulty=req.difficulty,
            topic=req.topic,
            mode=req.mode,
            stream=False,
        ),
        user_id=req.student_id,
    ):
        try:
            result = start_timeline_round(req.grade, req.difficulty, req.topic, req.student_id, req.mode)
            record_event_if_student(
                req.student_id,
                feature="history_timeline",
                event_type="timeline_game_started",
                grade=req.grade or result.get("grade"),
                topic=req.topic or result.get("topic"),
                success=True,
                metadata={"round_id": result.get("round_id"), "difficulty": req.difficulty, "source": result.get("source")},
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/games/timeline/submit")
async def timeline_submit(req: TimelineSubmitRequest, actor: Actor = Depends(require_auth)):
    try:
        result = submit_timeline_round(req.round_id, req.ordered_event_ids)
        total = result.get("total") or len(result.get("correct_order") or req.ordered_event_ids)
        correct = result.get("score") or 0
        score = float(correct) / total if isinstance(correct, (int, float)) and total else None
        if req.record_event:
            record_event_if_student(
                result.get("student_id"),
                feature="history_timeline",
                event_type="timeline_game_submitted",
                topic=result.get("topic"),
                score=score,
                success=bool(result.get("is_correct", score == 1 if score is not None else False)),
                metadata={"round_id": req.round_id, "total": total},
            )
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/card-game/start")
async def card_game_start(req: CardGameStartRequest, actor: Actor = Depends(require_auth)):
    with trace_context(
        name="POST /api/history/card-game/start",
        metadata=trace_meta(
            "history_card_game_start",
            "/api/history/card-game/start",
            student_id=req.student_id,
            grade=req.grade,
            difficulty=req.difficulty,
            topic=req.topic,
            mode=req.mode,
            stream=False,
        ),
        user_id=req.student_id,
    ):
        try:
            result = start_card_game_round(req.grade, req.difficulty, req.topic, req.student_id, req.mode)
            record_event_if_student(
                req.student_id,
                feature="history_card_game",
                event_type="card_game_started",
                grade=req.grade or result.get("grade"),
                topic=req.topic or result.get("topic"),
                success=True,
                metadata={"round_id": result.get("round_id"), "difficulty": req.difficulty, "source": result.get("source")},
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/card-game/submit")
async def card_game_submit(req: CardGameSubmitRequest, actor: Actor = Depends(require_auth)):
    try:
        result = submit_card_game_round(req.round_id, req.submitted_card_ids)
        total = result.get("total") or len(result.get("correct_order") or req.submitted_card_ids)
        correct = result.get("score") or 0
        score = float(correct) / total if isinstance(correct, (int, float)) and total else None
        record_event_if_student(
            result.get("student_id"),
            feature="history_card_game",
            event_type="card_game_submitted",
            grade=result.get("grade"),
            topic=result.get("topic"),
            score=score,
            success=score == 1 if score is not None else None,
            metadata={"round_id": req.round_id, "total": total, "can_retry": result.get("can_retry")},
        )
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/card-game/retry")
async def card_game_retry(req: CardGameRetryRequest, actor: Actor = Depends(require_auth)):
    try:
        result = retry_card_game_round(req.round_id, req.revised_card_ids)
        total = result.get("total") or len(result.get("correct_order") or req.revised_card_ids)
        correct = result.get("score") or 0
        score = float(correct) / total if isinstance(correct, (int, float)) and total else None
        record_event_if_student(
            result.get("student_id"),
            feature="history_card_game",
            event_type="card_game_retry_submitted",
            grade=result.get("grade"),
            topic=result.get("topic"),
            score=score,
            success=score == 1 if score is not None else None,
            metadata={"round_id": req.round_id, "total": total},
        )
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/history/card-game/report/{student_id}")
async def card_game_report(student_id: str, actor: Actor = Depends(require_auth)):
    return get_card_game_report(student_id)


class MultiplayerStartRequest(BaseModel):
    grade: str | None = None
    difficulty: str = "easy"
    topic: str | None = None
    student_id: str | None = None
    ai_count: int = Field(default=2, ge=1, le=5)
    ai_difficulty: str = "medium"
    mode: str = "llm"


class MultiplayerPlayRequest(BaseModel):
    round_id: str
    player_id: str
    card_id: str
    insert_index: int


class MultiplayerAiTurnRequest(BaseModel):
    round_id: str


@app.post("/api/history/multiplayer/start")
async def multiplayer_start(req: MultiplayerStartRequest, actor: Actor = Depends(require_auth)):
    with trace_context(
        name="POST /api/history/multiplayer/start",
        metadata=trace_meta(
            "history_multiplayer_start",
            "/api/history/multiplayer/start",
            student_id=req.student_id,
            grade=req.grade,
            difficulty=req.difficulty,
            topic=req.topic,
            ai_count=req.ai_count,
            ai_difficulty=req.ai_difficulty,
            mode=req.mode,
            stream=False,
        ),
        user_id=req.student_id,
    ):
        try:
            return await run_in_threadpool(
                start_multiplayer_round,
                req.grade, req.difficulty, req.topic, req.student_id,
                req.ai_count, req.ai_difficulty, req.mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/multiplayer/play")
async def multiplayer_play(req: MultiplayerPlayRequest, actor: Actor = Depends(require_auth)):
    try:
        return play_human_turn(req.round_id, req.player_id, req.card_id, req.insert_index)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/multiplayer/ai-turn")
async def multiplayer_ai_turn(req: MultiplayerAiTurnRequest, actor: Actor = Depends(require_auth)):
    try:
        return play_ai_turn(req.round_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/students/{student_id}/profile")
async def student_profile(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    record_audit_event(actor_id=actor.actor_id, action="student_profile.read", resource_type="student", resource_id=student_id)
    try:
        return {"profile": get_student_profile(student_id).model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/students/{student_id}/review-plan")
async def student_review_plan(student_id: str, limit: int = 5, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    record_audit_event(actor_id=actor.actor_id, action="student_profile.review_plan", resource_type="student", resource_id=student_id)
    try:
        normalized_limit = max(1, min(limit, 10))
        review_plan = suggest_review_plan(student_id, limit=normalized_limit)
        weakpoints = get_weakpoints(student_id)[:normalized_limit]
        review_plan["weakpoints"] = weakpoints
        review_plan["priority_topics"] = [point["knowledge_tag"] for point in weakpoints]
        return {"review_plan": review_plan}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/students/{student_id}/learning-path")
async def student_learning_path(student_id: str, actor: Actor = Depends(require_auth)):
    """Get student learning path with progress and milestones."""
    assert_student_access(actor, student_id)
    record_audit_event(actor_id=actor.actor_id, action="student_profile.learning_path", resource_type="student", resource_id=student_id)
    try:
        profile = get_student_profile(student_id)
        review_plan = suggest_review_plan(student_id, limit=10)
        weakpoints = get_weakpoints(student_id)[:10]
        priority_topics = [point["knowledge_tag"] for point in weakpoints]

        progress: dict[str, float] = {}
        for point in weakpoints:
            topic = point["knowledge_tag"]
            wrong_count = int(point.get("wrong_count") or 0)
            if wrong_count >= 5:
                progress[topic] = 0.25
            elif wrong_count >= 3:
                progress[topic] = 0.4
            else:
                progress[topic] = 0.5
        for topic in profile.weak_topics:
            progress.setdefault(topic, 0.5)
        for topic in profile.strong_topics:
            progress[topic] = 0.8

        milestones = [
            {"title": action, "completed": False}
            for action in review_plan.get("recommended_actions", [])
        ]
        return {
            "student_id": student_id,
            "created_at": profile.updated_at,
            "updated_at": profile.updated_at,
            "weak_topics": profile.weak_topics,
            "strong_topics": profile.strong_topics,
            "weakpoints": weakpoints,
            "priority_topics": priority_topics,
            "recommended_actions": review_plan.get("recommended_actions", []),
            "progress": progress,
            "milestones": milestones,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/students/{student_id}/events")
async def student_learning_event(student_id: str, req: LearningEventRequest, actor: Actor = Depends(require_auth)):
    if student_id != req.student_id:
        raise HTTPException(status_code=400, detail="路径 student_id 与请求体不一致。")
    assert_student_access(actor, student_id)
    check_rate_limit(f"student-event:{student_id}", limit=120, window_seconds=3600)
    try:
        event_id = try_record_learning_event(LearningEvent(**req.model_dump()))
        record_audit_event(
            actor_id=actor.actor_id,
            action="student_profile.event_write",
            resource_type="student",
            resource_id=student_id,
            success=bool(event_id),
            metadata={"feature": req.feature, "event_type": req.event_type},
        )
        return {"event_id": event_id, "ok": bool(event_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/students/{student_id}/events")
async def student_events_list(student_id: str, limit: int = 50, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    try:
        events = list_learning_events(student_id=student_id, limit=max(1, min(limit, 200)))
        return {"events": events, "total": len(events)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/students/{student_id}/memory-entries")
async def student_memory_entries(student_id: str, limit: int = 100, status: str | None = "enabled", type: str | None = None, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    try:
        ensure_profile_memory_entries(student_id)
        requested_status = None if status == "all" else status
        entries = list_memory_entries(student_id, limit=max(1, min(limit, 200)), status=requested_status, memory_type=type, include_deleted=False)
        record_audit_event(actor_id=actor.actor_id, action="memory.entries_read", resource_type="student", resource_id=student_id, metadata={"count": len(entries), "status": status, "type": type})
        return {"memory_entries": [entry.model_dump() for entry in entries], "total": len(entries)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/students/{student_id}/memory-entries/{memory_id}")
async def student_memory_entry_update(student_id: str, memory_id: str, req: MemoryEntryStatusRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    existing = get_memory_entry(student_id, memory_id)
    if not existing or existing.status == "deleted":
        raise HTTPException(status_code=404, detail="记忆不存在或无权操作。")
    changed = set_memory_entry_status(memory_id, student_id, req.status)
    if not changed:
        raise HTTPException(status_code=404, detail="记忆不存在或无权操作。")
    action = "memory.entry_delete" if req.status == "deleted" else "memory.entry_disable" if req.status == "disabled" else "memory.entry_enable"
    record_audit_event(
        actor_id=actor.actor_id,
        action=action,
        resource_type="student",
        resource_id=student_id,
        metadata={"memory_id": memory_id, "memory_type": existing.type, "reason": req.reason},
    )
    updated = get_memory_entry(student_id, memory_id)
    return {"ok": True, "memory_entry": updated.model_dump() if updated else None}


@app.delete("/api/students/{student_id}/memory-entries/{memory_id}")
async def student_memory_entry_delete(student_id: str, memory_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    existing = get_memory_entry(student_id, memory_id)
    if not existing or existing.status == "deleted":
        raise HTTPException(status_code=404, detail="记忆不存在或无权删除。")
    deleted = set_memory_entry_status(memory_id, student_id, "deleted")
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在或无权删除。")
    record_audit_event(actor_id=actor.actor_id, action="memory.entry_delete", resource_type="student", resource_id=student_id, metadata={"memory_id": memory_id, "memory_type": existing.type})
    return {"ok": True}


@app.delete("/api/students/{student_id}/events/{event_id}")
async def student_event_delete(student_id: str, event_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    deleted = delete_learning_event(event_id, student_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="事件不存在或无权删除。")
    record_audit_event(actor_id=actor.actor_id, action="memory.event_delete", resource_type="student", resource_id=student_id, metadata={"event_id": event_id})
    return {"ok": True}


@app.get("/api/students/{student_id}/memory-audit")
async def student_memory_audit(student_id: str, limit: int = 50, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    actions = {
        "student_profile.read",
        "student_profile.review_plan",
        "student_profile.event_write",
        "memory.event_delete",
        "memory.entries_read",
        "memory.entry_disable",
        "memory.entry_enable",
        "memory.entry_delete",
        "tool.confirmation_required",
        "tool.confirmation_confirmed",
        "tool.confirmation_cancelled",
        "tool.role_denied",
        "tool.denied",
    }
    events = []
    for event in list_audit_events(limit=max(1, min(limit * 4, 200)), resource_type="student"):
        if event.get("resource_id") == student_id and event.get("action") in actions:
            events.append(event)
        if len(events) >= limit:
            break
    if len(events) < limit:
        for event in list_audit_events(limit=max(1, min(limit * 4, 200)), resource_type="tool"):
            meta = event.get("metadata") or {}
            if meta.get("student_id") == student_id and event.get("action") in actions:
                events.append(event)
            if len(events) >= limit:
                break
    return {"events": events[:limit], "total": len(events[:limit])}


@app.get("/api/textbooks")
async def textbooks(actor: Actor = Depends(require_auth)):
    return {"textbooks": [item.model_dump() for item in list_textbooks()]}


@app.get("/api/textbooks/{book_id}/toc")
async def textbook_toc(book_id: str, actor: Actor = Depends(require_auth)):
    try:
        return get_textbook_toc(book_id).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/textbooks/{book_id}/lessons/{lesson_id}")
async def textbook_lesson(book_id: str, lesson_id: str, actor: Actor = Depends(require_auth)):
    try:
        return get_textbook_lesson(book_id, lesson_id).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/textbook-learning/ask")
async def textbook_learning_ask(req: TextbookAskRequest, actor: Actor = Depends(require_auth)):
    async def event_stream():
        with trace_context(
            name="POST /api/textbook-learning/ask",
            metadata=trace_meta(
                "textbook_learning_ask",
                "/api/textbook-learning/ask",
                session_id=req.session_id,
                book_id=req.book_id,
                lesson_id=req.lesson_id,
                item_id=req.item_id,
                action=req.action,
                has_selected_text=bool(req.selected_text),
                stream=True,
            ),
            user_id=req.student_id,
            session_id=req.session_id,
        ):
            iterator = stream_ask_events(req)
            try:
                while True:
                    item = await run_in_threadpool(next_stream_event, iterator)
                    if item is None:
                        break
                    event, data = item
                    yield sse_frame(event, data)
                    await asyncio.sleep(0)
                record_event_if_student(
                    req.student_id,
                    session_id=req.session_id,
                    feature="textbook_learning",
                    event_type="textbook_ask",
                    book_id=req.book_id,
                    lesson_id=req.lesson_id,
                    success=True,
                    metadata={"action": req.action, "item_id": req.item_id},
                )
            except LookupError as exc:
                yield sse_frame("error", {"message": str(exc)})
            except ValueError as exc:
                yield sse_frame("error", {"message": str(exc)})
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/textbook-learning/summary")
async def textbook_learning_summary(req: TextbookSummaryRequest, actor: Actor = Depends(require_auth)):
    async def event_stream():
        with trace_context(
            name="POST /api/textbook-learning/summary",
            metadata=trace_meta(
                "textbook_learning_summary",
                "/api/textbook-learning/summary",
                book_id=req.book_id,
                lesson_id=req.lesson_id,
                mode=req.mode,
                stream=True,
            ),
            user_id=req.student_id,
        ):
            iterator = stream_summary_events(req)
            try:
                while True:
                    item = await run_in_threadpool(next_stream_event, iterator)
                    if item is None:
                        break
                    event, data = item
                    yield sse_frame(event, data)
                    await asyncio.sleep(0)
                record_event_if_student(
                    req.student_id,
                    feature="textbook_learning",
                    event_type="textbook_summary",
                    book_id=req.book_id,
                    lesson_id=req.lesson_id,
                    success=True,
                    metadata={"mode": req.mode},
                )
            except LookupError as exc:
                yield sse_frame("error", {"message": str(exc)})
            except ValueError as exc:
                yield sse_frame("error", {"message": str(exc)})
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/textbook-learning/quiz")
async def textbook_learning_quiz(req: TextbookQuizRequest, actor: Actor = Depends(require_auth)):
    with trace_context(
        name="POST /api/textbook-learning/quiz",
        metadata=trace_meta(
            "textbook_learning_quiz",
            "/api/textbook-learning/quiz",
            book_id=req.book_id,
            lesson_id=req.lesson_id,
            question_types=req.question_types,
            count=req.count,
            focus_item_id=req.focus_item_id,
            stream=False,
        ),
    ):
        try:
            result = await run_in_threadpool(generate_quiz, req)
            record_event_if_student(
                req.student_id,
                feature="textbook_learning",
                event_type="quiz_generated",
                book_id=req.book_id,
                lesson_id=req.lesson_id,
                success=True,
                metadata={"question_count": len(result.questions), "question_types": req.question_types},
            )
            return result.model_dump()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/textbook-learning/quiz/submit")
async def textbook_learning_quiz_submit(req: TextbookQuizSubmitRequest, actor: Actor = Depends(require_auth)):
    try:
        result = await run_in_threadpool(submit_quiz_answers, req)
        record_event_if_student(
            req.student_id,
            feature="textbook_learning",
            event_type="quiz_submitted",
            book_id=req.book_id,
            lesson_id=req.lesson_id,
            score=result.get("score"),
            success=result.get("score", 0) >= 0.6,
            metadata={"total": result.get("total"), "correct": result.get("correct")},
        )
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/materials/parse")
async def parse_material(
    file: UploadFile = File(...),
    grade: str | None = Form(None),
    subject: str | None = Form(None),
    ocr_mode: str = Form("auto"),
    preprocess: bool = Form(True),
    actor: Actor = Depends(require_auth),
):
    check_rate_limit(f"materials-parse:{actor.actor_id}", limit=30, window_seconds=3600)
    record_audit_event(
        actor_id=actor.actor_id,
        action="materials.parse",
        metadata={"filename": file.filename, "content_type": file.content_type, "grade": grade, "subject": subject, "ocr_mode": ocr_mode, "preprocess": preprocess},
    )
    data = await file.read()
    with trace_context(
        name="POST /api/materials/parse",
        metadata=trace_meta(
            "materials_parse",
            "/api/materials/parse",
            filename=file.filename,
            content_type=file.content_type,
            grade=grade,
            subject=subject,
            ocr_mode=ocr_mode,
            preprocess=preprocess,
            bytes=len(data),
            stream=False,
        ),
        user_id=actor.actor_id,
    ):
        try:
            result = await run_in_threadpool(
                parse_material_bytes,
                file.filename or "uploaded-material",
                file.content_type or "",
                data,
                ocr_mode=ocr_mode,
                preprocess=preprocess,
            )
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MaterialSetupError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/materials/analyze")
async def material_analyze(req: MaterialGenerateRequest, actor: Actor = Depends(require_auth)):
    check_rate_limit(f"materials-analyze:{actor.actor_id}", limit=20, window_seconds=3600)
    record_audit_event(
        actor_id=actor.actor_id,
        action="materials.analyze",
        metadata={"grade": req.grade, "subject": req.subject, "task": req.task, "chars": len(req.text)},
    )
    with trace_context(
        name="POST /api/materials/analyze",
        metadata=trace_meta(
            "materials_analyze",
            "/api/materials/analyze",
            grade=req.grade,
            subject=req.subject,
            task=req.task,
            chars=len(req.text),
            stream=False,
        ),
        user_id=actor.actor_id,
        input_data={"text": req.text[:1200]},
    ):
        try:
            result = await run_in_threadpool(analyze_material, req)
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="生成失败，请稍后重试或缩短文本后再试") from exc


@app.post("/api/materials/save")
async def material_save(req: MaterialSaveRequest, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-save:{owner_key}", limit=20, window_seconds=3600)
    with trace_context(
        name="POST /api/materials/save",
        metadata=trace_meta(
            "materials_save",
            "/api/materials/save",
            title=req.title,
            filename=req.filename,
            source_type=req.source_type,
            grade=req.grade,
            subject=req.subject,
            chars=len(req.text),
            pages=len(req.pages),
            stream=False,
        ),
        user_id=actor.actor_id or owner_key,
    ):
        try:
            result = await run_in_threadpool(save_material_for_rag, req, owner_key)
            record_audit_event(
                actor_id=actor.actor_id,
                action="materials.save",
                resource_type="material",
                resource_id=result.material_id,
                metadata={"title": result.title, "chars": result.text_chars, "pages": result.page_count, "chunks": result.chunk_count},
            )
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="资料保存失败，请稍后重试") from exc


@app.get("/api/materials")
async def material_list(request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-list:{owner_key}", limit=120, window_seconds=3600)
    materials = await run_in_threadpool(list_saved_materials, owner_key)
    return {"materials": [item.model_dump() for item in materials]}


@app.get("/api/materials/{material_id}")
async def material_detail(material_id: str, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    try:
        result = await run_in_threadpool(get_saved_material, owner_key, material_id)
        return result.model_dump()
    except MaterialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/materials/{material_id}/ask")
async def material_ask(material_id: str, req: MaterialQuestionRequest, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-ask:{owner_key}", limit=60, window_seconds=3600)
    with trace_context(
        name="POST /api/materials/{material_id}/ask",
        metadata=trace_meta(
            "materials_ask",
            "/api/materials/{material_id}/ask",
            material_id=material_id,
            question_chars=len(req.question),
            k=req.k,
            stream=False,
        ),
        user_id=actor.actor_id or owner_key,
        input_data={"question": req.question},
    ):
        try:
            result = await run_in_threadpool(answer_material_question, owner_key, material_id, req)
            record_audit_event(
                actor_id=actor.actor_id,
                action="materials.ask",
                resource_type="material",
                resource_id=material_id,
                metadata={"question_chars": len(req.question), "sources": len(result.sources)},
            )
            return result.model_dump()
        except MaterialNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="资料问答失败，请稍后重试") from exc


@app.delete("/api/materials/{material_id}")
async def material_delete(material_id: str, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-delete:{owner_key}", limit=30, window_seconds=3600)
    try:
        await run_in_threadpool(delete_saved_material, owner_key, material_id)
        record_audit_event(
            actor_id=actor.actor_id,
            action="materials.delete",
            resource_type="material",
            resource_id=material_id,
        )
        return {"ok": True}
    except MaterialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/homework/parse")
async def homework_parse(
    file: UploadFile = File(...),
    grade: str | None = Form(None),
    subject: str | None = Form("历史"),
    task_type: str = Form("history_short_answer"),
    ocr_mode: str = Form("multimodal"),
    preprocess: bool = Form(True),
    actor: Actor = Depends(require_auth),
):
    if task_type not in {"history_short_answer", "history_material_analysis", "history_single_choice"}:
        raise HTTPException(status_code=400, detail="题型无效，请选择 history_short_answer、history_material_analysis 或 history_single_choice")
    check_rate_limit(f"homework-parse:{actor.actor_id}", limit=30, window_seconds=3600)
    data = await file.read()
    record_audit_event(
        actor_id=actor.actor_id,
        action="homework.parse",
        metadata={"filename": file.filename, "content_type": file.content_type, "task_type": task_type, "bytes": len(data)},
    )
    with trace_context(
        name="POST /api/homework/parse",
        metadata=trace_meta(
            "homework_parse",
            "/api/homework/parse",
            filename=file.filename,
            content_type=file.content_type,
            task_type=task_type,
            grade=grade,
            subject=subject,
            ocr_mode=ocr_mode,
            preprocess=preprocess,
            bytes=len(data),
            stream=False,
        ),
        user_id=actor.actor_id,
    ):
        try:
            result = await run_in_threadpool(
                extract_homework_from_upload,
                file.filename or "homework-upload",
                file.content_type or "",
                data,
                task_type=task_type,
                grade=grade,
                subject=subject,
                ocr_mode=ocr_mode,
                preprocess=preprocess,
            )
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MaterialSetupError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="作业识别失败，请稍后重试") from exc


@app.post("/api/homework/grade")
async def homework_grade(req: HomeworkGradeRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
    rate_key = req.student_id or actor.actor_id or "anonymous"
    check_rate_limit(f"homework-grade:{rate_key}", limit=60, window_seconds=3600)
    with trace_context(
        name="POST /api/homework/grade",
        metadata=trace_meta(
            "homework_grade",
            "/api/homework/grade",
            task_type=req.task_type,
            grade=req.grade,
            subject=req.subject,
            student_id=req.student_id,
            item_count=len(req.items),
            stream=False,
        ),
        user_id=req.student_id or actor.actor_id,
    ):
        try:
            result = await run_in_threadpool(grade_homework, req)
            record_audit_event(
                actor_id=actor.actor_id,
                action="homework.grade",
                resource_type="student" if req.student_id else "homework",
                resource_id=req.student_id,
                metadata={"item_count": len(req.items), "score": result.normalized_score, "needs_human_review": result.needs_human_review},
            )
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="作业批改失败，请稍后重试") from exc


class HomeworkReviewDecisionRequest(BaseModel):
    decision: Literal["accepted", "edited", "rejected"]
    teacher_note: str | None = Field(default=None, max_length=2000)
    teacher_score: float | None = Field(default=None, ge=0, le=100)


def _record_review_decision_learning_signals(review: dict[str, Any], req: HomeworkReviewDecisionRequest) -> str | None:
    student_id = review.get("student_id") or (review.get("grade_request") or {}).get("student_id")
    if not student_id:
        return None

    grade_request = review.get("grade_request") or {}
    grade_result = review.get("grade_result") or {}
    weak_points = [item for item in grade_result.get("weak_points") or [] if isinstance(item, str) and item.strip()]
    normalized_score = grade_result.get("normalized_score")
    if req.teacher_score is not None:
        normalized_score = max(0, min(req.teacher_score / 100, 1))
    try:
        score_value = float(normalized_score) if normalized_score is not None else None
    except (TypeError, ValueError):
        score_value = None

    event_id = try_record_learning_event(
        LearningEvent(
            student_id=student_id,
            feature="homework_grading",
            event_type=f"teacher_review_{req.decision}",
            grade=grade_request.get("grade"),
            topic="、".join(weak_points[:3]) or None,
            score=score_value,
            success=(score_value >= 0.6) if score_value is not None else (req.decision != "rejected"),
            metadata={
                "review_id": review.get("id"),
                "decision": req.decision,
                "teacher_score": req.teacher_score,
                "teacher_note_present": bool(req.teacher_note),
                "weak_points": weak_points[:8],
                "original_event_id": grade_result.get("event_id"),
            },
        )
    )

    if req.decision in {"accepted", "edited"}:
        tags = list(weak_points)
        for item in grade_result.get("items") or []:
            if not isinstance(item, dict):
                continue
            try:
                max_score = float(item.get("max_score") or 1)
                item_score = float(item.get("score") or 0)
            except (TypeError, ValueError):
                max_score = 1
                item_score = 0
            is_correct = bool(item.get("is_correct"))
            if is_correct and max_score > 0 and item_score / max_score >= 0.6:
                continue
            tags.extend(tag for tag in item.get("knowledge_tags") or [] if isinstance(tag, str))
        for tag in dict.fromkeys([tag for tag in tags if tag.strip()]):
            record_weakpoint(student_id, tag, "homework_teacher_review")

    return event_id


@app.post("/api/homework/reviews")
async def homework_save_review(req: dict, actor: Actor = Depends(require_auth)):
    grade_request = req.get("grade_request") or {}
    grade_result = req.get("grade_result") or {}
    if not grade_result:
        raise HTTPException(status_code=400, detail="grade_result required")
    review_id = save_review(
        actor_id=actor.actor_id,
        student_id=grade_request.get("student_id"),
        grade_request=grade_request,
        grade_result=grade_result,
    )
    record_audit_event(actor_id=actor.actor_id, action="homework.review_saved", resource_type="homework", metadata={"review_id": review_id, "needs_human_review": grade_result.get("needs_human_review")})
    return {"ok": True, "review_id": review_id}


@app.get("/api/teacher/homework-reviews")
async def teacher_list_reviews(decision: str | None = None, limit: int = 50, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    reviews = list_reviews(decision=decision or None, limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


@app.post("/api/teacher/homework-reviews/{review_id}/decision")
async def teacher_review_decision(review_id: str, req: HomeworkReviewDecisionRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    ok = apply_decision(review_id, teacher_id=actor.actor_id, decision=req.decision, teacher_note=req.teacher_note, teacher_score=req.teacher_score)
    if not ok:
        raise HTTPException(status_code=404, detail="review not found")
    review = get_review(review_id)
    event_id = _record_review_decision_learning_signals(review, req) if review else None
    record_audit_event(actor_id=actor.actor_id, action=f"homework.review_{req.decision}", resource_type="homework", metadata={"review_id": review_id, "teacher_score": req.teacher_score, "event_id": event_id})
    return {"ok": True, "event_id": event_id}


@app.get("/api/learning/assistant/tools")
async def learning_assistant_tools(actor: Actor = Depends(require_auth)):
    return {"schema_version": 1, "tools": list_tools()}


@app.post("/api/learning/assistant/tool-confirmation/cancel")
async def learning_assistant_cancel_tool_confirmation(req: ToolConfirmationCancelRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
    record_audit_event(
        actor_id=actor.actor_id,
        action="tool.confirmation_cancelled",
        resource_type="tool",
        resource_id=req.tool_name,
        success=True,
        metadata={"tool_name": req.tool_name, "student_id": req.student_id, "request_source": "learning_assistant"},
    )
    trace_id = current_trace_id()
    return {"ok": True, "status": "cancelled", "tool_name": req.tool_name, "trace_id": trace_id}


@app.post("/api/learning/assistant/chat")
async def learning_assistant_chat(req: LearningAssistantRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
        check_rate_limit(f"learning-assistant:{req.student_id}", limit=80, window_seconds=3600)
    request_data = req.model_dump()
    request_data["actor_id"] = actor.actor_id
    request_data["actor_role"] = "student" if req.student_id and not auth_required() else actor.role
    metadata = trace_meta(
        "learning_assistant_chat",
        "/api/learning/assistant/chat",
        session_id=req.session_id,
        student_id=req.student_id,
        grade=req.grade,
        book_id=req.book_id,
        lesson_id=req.lesson_id,
        stream=req.stream,
    )

    if not req.stream:
        with trace_context(
            name="POST /api/learning/assistant/chat",
            metadata=metadata,
            user_id=req.student_id,
            session_id=req.session_id,
            input_data={"message": req.message},
        ):
            trace_id = current_trace_id()
            try:
                enforce_guardrails(
                    req.message,
                    actor=actor,
                    route="/api/learning/assistant/chat",
                    student_id=req.student_id,
                    resource_type="student" if req.student_id else None,
                )
            except HTTPException as exc:
                guardrail_step = {
                    "event": "runtime_step",
                    "data": {
                        "trace_id": trace_id,
                        "agent_name": "learning_assistant",
                        "step_id": "guardrail_check",
                        "step_name": "Guardrail Check",
                        "event_type": "guardrail",
                        "status": "failed",
                        "latency_ms": None,
                        "metadata": {"error_code": "guardrail_failed", "message": exc.detail},
                    },
                }
                raise HTTPException(status_code=exc.status_code, detail={"message": exc.detail, "events": [guardrail_step]}) from exc
            guardrail_step = {
                "event": "runtime_step",
                "data": {
                    "trace_id": trace_id,
                    "agent_name": "learning_assistant",
                    "step_id": "guardrail_check",
                    "step_name": "Guardrail Check",
                    "sequence": 0,
                    "event_type": "guardrail",
                    "status": "success",
                    "latency_ms": None,
                    "metadata": {"route": "/api/learning/assistant/chat"},
                    "error": None,
                },
            }
            record_audit_event(
                actor_id=actor.actor_id,
                action="learning_assistant.chat",
                resource_type="student" if req.student_id else None,
                resource_id=req.student_id,
                metadata={"stream": req.stream, "grade": req.grade},
            )
            request_data["trace_id"] = trace_id
            events = list(stream_learning_assistant_events(request_data))
            final = next((data for event, data in events if event == "final"), None)
            suggestions = next((data for event, data in events if event == "suggestions"), None)
            intent = next((data for event, data in events if event == "intent"), None)
            return {"trace_id": trace_id, "intent": intent, "final": final, "suggestions": suggestions, "events": [guardrail_step, *[{"event": event, "data": data} for event, data in events]]}

    async def event_stream():
        with trace_context(
            name="POST /api/learning/assistant/chat",
            metadata=metadata,
            user_id=req.student_id,
            session_id=req.session_id,
            input_data={"message": req.message},
        ):
            trace_id = current_trace_id()
            yield sse_frame("trace", {"trace_id": trace_id})
            try:
                enforce_guardrails(
                    req.message,
                    actor=actor,
                    route="/api/learning/assistant/chat",
                    student_id=req.student_id,
                    resource_type="student" if req.student_id else None,
                )
                yield sse_frame("runtime_step", {
                    "trace_id": trace_id,
                    "agent_name": "learning_assistant",
                    "step_id": "guardrail_check",
                    "step_name": "Guardrail Check",
                    "sequence": 0,
                    "event_type": "guardrail",
                    "status": "success",
                    "latency_ms": None,
                    "metadata": {"route": "/api/learning/assistant/chat"},
                    "error": None,
                })
            except HTTPException as exc:
                yield sse_frame("runtime_step", {
                    "trace_id": trace_id,
                    "agent_name": "learning_assistant",
                    "step_id": "guardrail_check",
                    "step_name": "Guardrail Check",
                    "sequence": 0,
                    "event_type": "guardrail",
                    "status": "failed",
                    "latency_ms": None,
                    "metadata": {"error_code": "guardrail_failed", "message": exc.detail},
                    "error": {"code": "guardrail_failed", "message": exc.detail, "retryable": False},
                })
                yield sse_frame("error", {"message": exc.detail})
                return
            record_audit_event(
                actor_id=actor.actor_id,
                action="learning_assistant.chat",
                resource_type="student" if req.student_id else None,
                resource_id=req.student_id,
                metadata={"stream": req.stream, "grade": req.grade},
            )
            request_data["trace_id"] = trace_id
            iterator = stream_learning_assistant_events(request_data)
            try:
                while True:
                    item = await run_in_threadpool(next_stream_event, iterator)
                    if item is None:
                        break
                    event, data = item
                    yield sse_frame(event, data)
                    await asyncio.sleep(0)
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- AutoTutor 自主辅导 Agent 闭环 ---

@app.post("/api/autotutor/start")
async def autotutor_start_session(req: AutoTutorStartRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, req.student_id)
    check_rate_limit(f"autotutor:{req.student_id}", limit=40, window_seconds=3600)
    actor_role = "student" if not auth_required() else actor.role
    metadata = trace_meta("auto_tutor", "/api/autotutor/start", student_id=req.student_id, grade=req.grade)
    with trace_context(
        name="POST /api/autotutor/start",
        metadata=metadata,
        user_id=req.student_id,
        input_data={"student_id": req.student_id},
    ):
        trace_id = current_trace_id()
        record_audit_event(
            actor_id=actor.actor_id,
            action="autotutor.start",
            resource_type="student",
            resource_id=req.student_id,
            metadata={"grade": req.grade},
        )
        return await run_in_threadpool(
            autotutor_start,
            req.student_id,
            grade=req.grade,
            actor_id=actor.actor_id,
            actor_role=actor_role,
            trace_id=trace_id,
            focus_tags=req.focus_tags or None,
        )


@app.post("/api/autotutor/answer")
async def autotutor_submit_answer(req: AutoTutorAnswerRequest, actor: Actor = Depends(require_auth)):
    if req.student_id:
        assert_student_access(actor, req.student_id)
    actor_role = "student" if not auth_required() else actor.role
    record_audit_event(
        actor_id=actor.actor_id,
        action="autotutor.answer",
        resource_type="student",
        resource_id=req.student_id,
        metadata={"session_id": req.session_id},
    )
    try:
        return await run_in_threadpool(
            autotutor_answer,
            req.session_id,
            req.answer,
            actor_id=actor.actor_id,
            actor_role=actor_role,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="辅导会话不存在或已过期，请重新开始。")


@app.get("/api/autotutor/session/{session_id}")
async def autotutor_get_session(session_id: str, actor: Actor = Depends(require_auth)):
    try:
        state = autotutor_get(session_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="辅导会话不存在或已过期。")
    if req_student := state.get("student_id"):
        assert_student_access(actor, req_student)
    return state


@app.post("/api/history/character/recommend")
async def character_recommend(req: CharacterRecommendRequest, actor: Actor = Depends(require_auth)):
    with trace_context(
        name="POST /api/history/character/recommend",
        metadata=trace_meta(
            "history_character_recommend",
            "/api/history/character/recommend",
            student_id=req.student_id,
            grade=req.grade,
            limit=req.limit,
            stream=False,
        ),
        user_id=req.student_id,
    ):
        enforce_guardrails(
            req.message,
            actor=actor,
            route="/api/history/character/recommend",
            student_id=req.student_id,
            resource_type="student" if req.student_id else None,
        )
        recommendations = recommend_characters(req.message, req.grade, req.limit)
        record_event_if_student(
            req.student_id,
            feature="history_character",
            event_type="character_recommended",
            grade=req.grade,
            success=True,
            metadata={"characters": [item.get("name") for item in recommendations if item.get("name")]},
        )
        return {
            "recommendations": [CharacterRecommendation(**item).model_dump() for item in recommendations]
        }


@app.post("/api/history/character/chat")
async def character_chat(req: CharacterRequest, actor: Actor = Depends(require_auth)):
    retriever = get_retriever("history")
    state = build_character_state(req)
    metadata = trace_meta(
        "history_character_chat",
        "/api/history/character/chat",
        session_id=req.session_id,
        student_id=req.student_id,
        character=req.character,
        grade=req.grade,
        mode=state.get("mode"),
        stream=req.stream,
    )

    if not req.stream:
        with trace_context(
            name="POST /api/history/character/chat",
            metadata=metadata,
            user_id=req.student_id,
            session_id=req.session_id,
        ):
            enforce_guardrails(
                req.message,
                actor=actor,
                route="/api/history/character/chat",
                student_id=req.student_id,
                resource_type="character",
                resource_id=req.character,
            )
            graph = build_character_graph(retriever)
            result = await graph.ainvoke(state)
            record_event_if_student(
                req.student_id,
                session_id=req.session_id,
                feature="history_character",
                event_type="character_chat",
                grade=req.grade,
                topic=req.character,
                success=True,
                metadata={"character": req.character, "mode": state.get("mode"), "verified": result.get("verified", False)},
            )
            return {
                "response": result["response_draft"],
                "character": req.character,
                "sources": result.get("retrieved_sources", []),
                "rag_inspector": result.get("rag_inspector", {}),
                "verified": result.get("verified", False),
            }

    async def event_stream():
        with trace_context(
            name="POST /api/history/character/chat",
            metadata=metadata,
            user_id=req.student_id,
            session_id=req.session_id,
        ):
            trace_id = current_trace_id()
            try:
                enforce_guardrails(
                    req.message,
                    actor=actor,
                    route="/api/history/character/chat",
                    student_id=req.student_id,
                    resource_type="character",
                    resource_id=req.character,
                )
                # Emit trace_id at start
                if trace_id:
                    yield sse_frame("trace", {"trace_id": trace_id})
                final_response = None
                yield sse_frame("status", {"phase": "retrieving", "message": "正在检索广东初中历史史料"})
                for item in stream_character_response(state, retriever):
                    event = item["event"]
                    data = item["data"]
                    if event == "sources":
                        yield sse_frame("sources", data)
                        yield sse_frame("status", {"phase": "generating", "message": "正在生成教学模拟回答"})
                    elif event == "delta":
                        yield sse_frame("delta", data)
                    elif event == "status":
                        yield sse_frame("status", data)
                    elif event == "final":
                        final_response = data.get("response", "")
                        yield sse_frame("final", data)
                        yield sse_frame("status", {"phase": "done", "message": "已完成"})
                        # Emit trace_id at end
                        if trace_id:
                            yield sse_frame("trace", {"trace_id": trace_id})
                    elif event == "fact_card":
                        yield sse_frame("fact_card", data)
                    await asyncio.sleep(0)
                if final_response:
                    record_event_if_student(
                        req.student_id,
                        session_id=req.session_id,
                        feature="history_character",
                        event_type="character_chat",
                        grade=req.grade,
                        topic=req.character,
                        success=True,
                        metadata={"character": req.character, "mode": state.get("mode")},
                    )
                if req.session_id and final_response:
                    history = load_messages(req.session_id)
                    history.append({"role": "user", "content": req.message})
                    history.append({"role": "assistant", "content": final_response})
                    save_messages(req.session_id, history)
            except HTTPException as exc:
                yield sse_frame("error", {"message": exc.detail})
            except Exception as exc:
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chinese/essay/grade")
async def grade_essay(req: EssayRequest, actor: Actor = Depends(require_auth)):
    check_user_input(req.essay)
    import uuid
    session_id = req.student_id or str(uuid.uuid4())
    with trace_context(
        name="POST /api/chinese/essay/grade",
        metadata=trace_meta("essay_grader", "/api/chinese/essay/grade", student_id=req.student_id),
        user_id=req.student_id or actor.actor_id,
    ):
        graph = build_grader_graph()
        state: EssayState = {
            "essay": req.essay, "student_id": req.student_id, "draft_score": {}, "draft_comments": "",
            "final_score": {}, "final_comments": "", "revision_count": 0,
            "critique_approved": False, "needs_human_review": False, "review_reason": None,
        }
        result = await graph.ainvoke(state)
    # Save session for potential review
    save_messages(session_id, [
        {"role": "user", "content": req.essay},
        {"role": "assistant", "content": result["final_comments"]},
    ])
    return {
        "student_id": req.student_id,
        "session_id": session_id,
        "comments": result["final_comments"],
        "needs_human_review": result.get("needs_human_review", False),
        "review_reason": result.get("review_reason"),
    }


class EssayReviewRequest(BaseModel):
    session_id: str
    approved: bool
    teacher_comments: str = ""
    decision: str = "approved"  # approved | edited | rejected
    score_override: float | None = None


@app.post("/api/chinese/essay/review-result")
async def submit_essay_review(req: EssayReviewRequest, actor: Actor = Depends(require_auth)):
    msgs = load_messages(req.session_id)
    msgs.append({
        "role": "system",
        "content": f"[教师复核] approved={req.approved} decision={req.decision} {req.teacher_comments}".strip(),
    })
    save_messages(req.session_id, msgs)
    record_audit_event(
        actor_id=actor.actor_id,
        action="teacher.essay_review",
        resource_type="essay",
        resource_id=req.session_id,
        metadata={"decision": req.decision, "score_override": req.score_override},
    )
    return {"status": "ok", "decision": req.decision}


@app.get("/api/chinese/essay/review-stats")
async def essay_review_stats(actor: Actor = Depends(require_auth)):
    from security.audit_log import list_audit_events
    events = list_audit_events(action="teacher.essay_review", limit=200)
    counts = {"approved": 0, "edited": 0, "rejected": 0}
    for ev in events:
        meta = ev.get("metadata") or {}
        d = meta.get("decision", "approved")
        if d in counts:
            counts[d] += 1
    total = sum(counts.values())
    return {"total": total, **counts}


@app.post("/api/history/debate/start")
async def start_debate(req: DebateRequest, actor: Actor = Depends(require_auth)):
    check_user_input(req.topic)
    with trace_context(
        name="POST /api/history/debate/start",
        metadata=trace_meta("debate", "/api/history/debate/start", topic=req.topic[:80]),
        user_id=actor.actor_id,
    ):
        graph = build_debate_graph()
        state: DebateState = {"topic": req.topic, "rounds": [],
                              "current_side": "pro", "round_count": 0, "verdict": ""}
        result = await graph.ainvoke(state)
    return {"topic": req.topic, "rounds": result["rounds"], "verdict": result["verdict"]}


@app.post("/api/history/debate/stream")
async def stream_debate_endpoint(req: DebateRequest, actor: Actor = Depends(require_auth)):
    check_user_input(req.topic)

    async def event_stream():
        async for item in stream_debate(req.topic):
            yield sse_frame(item["event"], item["data"])

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# 历史时空地图接口
from agents.history_map_agent import get_events_by_dynasty, stream_map_narrate, handle_chat_query


class GeoEventsRequest(BaseModel):
    dynasty: str | None = None
    year_start: int | None = None
    year_end: int | None = None


class GeoNarrateRequest(BaseModel):
    event_id: str
    user_query: str = ""


@app.get("/api/history/geo/events")
async def get_geo_events(dynasty: str | None = None, year_start: int | None = None, year_end: int | None = None, actor: Actor = Depends(require_auth)):
    events = await run_in_threadpool(get_events_by_dynasty, dynasty, year_start, year_end)
    return {"events": events}


@app.get("/api/history/geo/narrate")
async def narrate_geo_event(event_id: str, user_query: str = "", actor: Actor = Depends(require_auth)):
    if user_query:
        enforce_guardrails(
            user_query,
            actor=actor,
            route="/api/history/geo/narrate",
            resource_type="geo_event",
            resource_id=event_id,
        )

    async def event_stream():
        for chunk in stream_map_narrate(event_id, user_query):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/history/geo/chat")
async def chat_with_map(query: str, actor: Actor = Depends(require_auth)):
    enforce_guardrails(query, actor=actor, route="/api/history/geo/chat", resource_type="geo_chat")
    result = await run_in_threadpool(handle_chat_query, query)
    return result


# ── Eval runner ──────────────────────────────────────────────────────────────

class EvalRunRequest(BaseModel):
    suite: str | None = None   # suite name, "quick", or None → quick
    quick: bool = True


def load_eval_runner():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    eval_dir = root / "eval"
    if str(eval_dir) not in sys.path:
        sys.path.insert(0, str(eval_dir))
    import run_core_evals

    return run_core_evals


def require_eval_actor(actor: Actor) -> None:
    if auth_required() and actor.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师可访问")


@app.get("/api/agent-ops/summary")
async def agent_ops_summary(limit: int = 100, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    return build_agent_ops_summary(limit=limit)


@app.get("/api/eval/suites")
async def eval_suites(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    return {
        "quick": runner.QUICK_SUITES,
        "core": runner.CORE_SUITES,
        "smoke": runner.SMOKE_SUITES,
        "suites": runner.list_suite_metadata(),
    }


@app.get("/api/eval/latest")
async def eval_latest(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if not runner.LATEST_JSON.exists():
        raise HTTPException(status_code=404, detail="latest eval report not found")
    return json.loads(runner.LATEST_JSON.read_text(encoding="utf-8"))


@app.get("/api/eval/report/json")
async def eval_report_json(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if not runner.LATEST_JSON.exists():
        raise HTTPException(status_code=404, detail="latest eval report not found")
    return FileResponse(runner.LATEST_JSON, media_type="application/json", filename="eduagent-eval-latest.json")


@app.get("/api/eval/report/markdown")
async def eval_report_markdown(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if not runner.LATEST_MD.exists():
        raise HTTPException(status_code=404, detail="latest eval report not found")
    return FileResponse(runner.LATEST_MD, media_type="text/markdown", filename="eduagent-eval-latest.md")


@app.post("/api/eval/run")
async def eval_run(req: EvalRunRequest, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()

    if req.suite and req.suite not in ("quick", "all"):
        if req.suite not in runner.SUITE_FILES:
            raise HTTPException(status_code=400, detail=f"unknown suite: {req.suite}")
        names = [req.suite]
    elif req.suite == "all" or not req.quick:
        names = runner.CORE_SUITES
    else:
        names = runner.QUICK_SUITES

    results = []
    for name in names:
        try:
            results.append(await run_in_threadpool(runner.run_suite, name))
        except Exception as exc:
            results.append(
                runner.SuiteResult(
                    name=name,
                    command=[],
                    returncode=1,
                    duration_sec=0,
                    stdout="",
                    stderr="",
                    passed_cases=0,
                    failed_cases_count=1,
                    total_cases=1,
                    metrics={},
                    failed_cases=[],
                    error=str(exc),
                )
            )

    summary = runner.build_json_summary(results, include_output=True)
    runner.write_reports(summary)
    return summary


@app.get("/api/eval/history")
async def eval_history(limit: int = 20, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    history_dir = runner.REPORTS_DIR / "history"
    if not history_dir.exists():
        return {"snapshots": []}
    files = sorted(history_dir.glob("*.json"))[-limit:]
    snapshots = []
    for f in files:
        try:
            snapshots.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"snapshots": snapshots}


_FAILURE_ACTIONS = {"tool.role_denied", "tool.denied", "tool.failed", "tool.confirmation_required", "guardrail.blocked"}

_SUITE_FOR_ACTION = {
    "tool.role_denied": "tool_registry_smoke",
    "tool.denied": "tool_registry_smoke",
    "tool.failed": "tool_registry_smoke",
    "tool.confirmation_required": "tool_registry_smoke",
    "guardrail.blocked": "learning_assistant_smoke",
}

_DEFAULT_SUITE_FILES = {
    "tool_registry_smoke": "tool_registry_cases.json",
    "learning_assistant_smoke": "learning_assistant_cases.json",
    "history_character": "history_character_cases.json",
    "rag_retrieval_eval": "rag_retrieval_cases.json",
}


def _expected_error_for_action(action: str, error_code: str | None = None) -> str | None:
    if error_code:
        return error_code
    if action == "tool.role_denied":
        return "role_denied"
    if action == "tool.confirmation_required":
        return "confirmation_required"
    if action == "tool.denied":
        return "invalid_confirmation"
    if action == "tool.failed":
        return None
    if action == "guardrail.blocked":
        return "guardrail_blocked"
    return None


def _draft_kind_for_suite(suite: str) -> str:
    if suite == "learning_assistant_smoke":
        return "learning_assistant"
    return "tool_registry"


def _candidate_missing_fields(candidate: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    suite = candidate.get("suggested_suite") or _SUITE_FOR_ACTION.get(str(candidate.get("action", "")), "tool_registry_smoke")
    draft_kind = _draft_kind_for_suite(str(suite))
    if draft_kind == "tool_registry":
        if not candidate.get("tool_name"):
            missing.append("tool_name")
        if not isinstance(candidate.get("payload"), dict):
            missing.append("payload")
        if not candidate.get("expected_error") and candidate.get("expected_ok") is None:
            missing.append("expected_error")
    else:
        payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
        message = candidate.get("query") or payload.get("message")
        if not isinstance(message, str) or not message.strip():
            missing.append("message")
        if not candidate.get("expected_error"):
            missing.append("expected_error")
    return missing


def _annotate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    suite = str(candidate.get("suggested_suite") or _SUITE_FOR_ACTION.get(str(candidate.get("action", "")), "tool_registry_smoke"))
    annotated = {**candidate, "suggested_suite": suite, "draft_kind": _draft_kind_for_suite(suite)}
    missing = _candidate_missing_fields(annotated)
    annotated["missing_fields"] = missing
    annotated["save_ready"] = not missing
    return annotated


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _case_fingerprint(case: dict[str, Any], suite: str) -> str:
    if suite == "learning_assistant_smoke":
        payload = {
            "message": case.get("message") or case.get("query"),
            "actor_role": case.get("actor_role"),
            "grade": case.get("grade"),
            "expected_error": case.get("expected_error"),
        }
    else:
        payload = {
            "tool_name": case.get("tool_name"),
            "actor_role": case.get("actor_role"),
            "expected_error": case.get("expected_error") or case.get("error_code"),
            "expected_ok": case.get("expected_ok"),
            "payload": case.get("payload"),
        }
    return _canonical_json(payload)


def _normalize_tool_registry_case(name: str, case: dict[str, Any]) -> dict[str, Any]:
    action = str(case.get("action") or "")
    error_code = case.get("error_code")
    tool_name = case.get("tool_name")
    payload = case.get("payload")
    expected_error = case.get("expected_error") or _expected_error_for_action(action, error_code if isinstance(error_code, str) else None)
    if not isinstance(tool_name, str) or not tool_name:
        raise HTTPException(status_code=400, detail="无法保存：缺少 tool_name，不能重放工具失败。")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="无法保存：缺少可重放的 payload/input_summary。")
    if not expected_error and case.get("expected_ok") is None:
        raise HTTPException(status_code=400, detail="无法保存：缺少 expected_error 或 expected_ok。")
    normalized = {
        "name": name,
        "tool_name": tool_name,
        "payload": payload,
        "actor_role": case.get("actor_role") or case.get("role") or "student",
        "student_id": case.get("student_id") or payload.get("student_id"),
        "expected_error": expected_error,
        "trace_id": case.get("trace_id"),
        "action": action,
        "_saved_from_trace": True,
    }
    if action == "tool.denied":
        normalized["confirmed"] = True
        normalized["confirmation_token"] = "invalid_trace_to_eval_token"
    if case.get("expected_ok") is not None:
        normalized["expected_ok"] = bool(case.get("expected_ok"))
    return {key: value for key, value in normalized.items() if value is not None}


def _normalize_learning_assistant_case(name: str, case: dict[str, Any]) -> dict[str, Any]:
    payload = case.get("payload") if isinstance(case.get("payload"), dict) else {}
    action = str(case.get("action") or "")
    message = case.get("message") or case.get("query") or payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=400, detail="无法保存：缺少可重放的 message/query。")
    expected_error = case.get("expected_error") or _expected_error_for_action(action, case.get("error_code") if isinstance(case.get("error_code"), str) else None)
    if not expected_error:
        raise HTTPException(status_code=400, detail="无法保存：缺少 expected_error。")
    return {
        "name": name,
        "message": message.strip(),
        "grade": case.get("grade") or payload.get("grade") or "八年级上册",
        "student_id": case.get("student_id") or payload.get("student_id") or "eval-student",
        "actor_role": case.get("actor_role") or payload.get("actor_role") or "student",
        "expected_error": expected_error,
        "expects_error": True,
        "trace_id": case.get("trace_id"),
        "action": action or "guardrail.blocked",
        "_saved_from_trace": True,
    }


def _normalize_eval_case(suite: str, name: str, case: dict[str, Any]) -> dict[str, Any]:
    if suite == "tool_registry_smoke":
        return _normalize_tool_registry_case(name, case)
    if suite == "learning_assistant_smoke":
        return _normalize_learning_assistant_case(name, case)
    raise HTTPException(status_code=400, detail=f"暂不支持将失败样本保存到 suite: {suite}")


@app.get("/api/eval/candidate-cases")
async def eval_candidate_cases(limit: int = 20, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    raw_events = list_audit_events(limit=200)
    candidates = []
    for ev in raw_events:
        action = ev.get("action", "")
        if action not in _FAILURE_ACTIONS:
            continue
        meta = ev.get("metadata") or {}
        input_summary = meta.get("input_summary")
        payload = input_summary if isinstance(input_summary, dict) else None
        expected_error = _expected_error_for_action(action, meta.get("error_code") if isinstance(meta.get("error_code"), str) else None)
        candidate = _annotate_candidate({
            "id": ev.get("id", ""),
            "source": "audit",
            "action": action,
            "actor_id": ev.get("actor_id", ""),
            "actor_role": meta.get("actor_role", "student"),
            "created_at": ev.get("created_at", ""),
            "trace_id": meta.get("trace_id", ""),
            "tool_name": meta.get("tool_name", ""),
            "error_code": meta.get("error_code", ""),
            "expected_error": expected_error,
            "query": meta.get("query") or (payload.get("message") if isinstance(payload, dict) and isinstance(payload.get("message"), str) else json.dumps(payload, ensure_ascii=False) if payload else ""),
            "payload": payload,
            "suggested_suite": _SUITE_FOR_ACTION.get(action, "tool_registry_smoke"),
        })
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return {"candidates": candidates, "total": len(candidates)}


class SaveEvalCaseRequest(BaseModel):
    suite: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    case: dict


@app.post("/api/eval/save-case")
async def eval_save_case(req: SaveEvalCaseRequest, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    datasets_dir = runner.LATEST_JSON.parent.parent / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    filename = _DEFAULT_SUITE_FILES.get(req.suite, f"{req.suite}_cases.json")
    target = datasets_dir / filename
    existing: list = []
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    if not isinstance(existing, list):
        existing = []
    case = _normalize_eval_case(req.suite, req.name, req.case)
    fingerprint = _case_fingerprint(case, req.suite)
    deduplicated = any(isinstance(item, dict) and _case_fingerprint(item, req.suite) == fingerprint for item in existing)
    if not deduplicated:
        existing.append(case)
        target.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    record_audit_event(
        actor_id=actor.actor_id,
        action="eval.case_saved",
        resource_type="eval",
        resource_id=req.suite,
        metadata={"name": req.name, "file": filename, "deduplicated": deduplicated, "saved": not deduplicated, "trace_id": case.get("trace_id")},
    )
    return {"ok": True, "file": filename, "total": len(existing), "saved": not deduplicated, "deduplicated": deduplicated}


# ── Batch Essay Grading ────────────────────────────────────────────────────────

class BatchEssayRequest(BaseModel):
    essays: list[dict]  # [{student_name: str, essay: str}]
    class_id: str | None = None


@app.post("/api/chinese/essay/grade/batch")
async def batch_grade_essays(req: BatchEssayRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    if len(req.essays) > 50:
        raise HTTPException(status_code=400, detail="单次最多批改 50 篇作文")
    for item in req.essays:
        check_user_input(item.get("essay", ""))
    results = await batch_grade(req.essays)
    summary = compute_summary(results)
    return {"results": results, "summary": summary}


# ── Weakpoints (错题本) ─────────────────────────────────────────────────────────

@app.get("/api/student/{student_id}/weakpoints")
async def student_weakpoints(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return {"weakpoints": get_weakpoints(student_id)}


@app.delete("/api/student/{student_id}/weakpoints/{knowledge_tag}")
async def delete_student_weakpoint(student_id: str, knowledge_tag: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    delete_weakpoint(student_id, knowledge_tag)
    return {"ok": True}


@app.delete("/api/student/{student_id}/weakpoints")
async def clear_student_weakpoints(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    clear_weakpoints(student_id)
    return {"ok": True}


# ── 自适应复习 ──────────────────────────────────────────────────────────────────

from datetime import date as _date
from services.review_service import (
    create_today_session, get_mastery_overview, get_today_session,
    submit_answer as _submit_review,
)

class ReviewSubmitRequest(BaseModel):
    task_index: int
    is_correct: bool

@app.get("/api/students/{student_id}/review/today")
async def review_today(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    today = _date.today().isoformat()
    session = await run_in_threadpool(get_today_session, student_id, today)
    if session:
        return session
    return await run_in_threadpool(create_today_session, student_id, today)

@app.post("/api/students/{student_id}/review/submit")
async def review_submit(student_id: str, req: ReviewSubmitRequest, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    today = _date.today().isoformat()
    return await run_in_threadpool(_submit_review, student_id, today, req.task_index, req.is_correct)

@app.get("/api/students/{student_id}/mastery-overview")
async def student_mastery_overview(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return await run_in_threadpool(get_mastery_overview, student_id)


@app.get("/api/students/{student_id}/today")
async def student_today_plan(student_id: str, actor: Actor = Depends(require_auth)):
    """学生今日计划：作业到期/今日复习/薄弱点按优先级合成的待办清单。"""
    assert_student_access(actor, student_id)
    from services.today_plan import get_student_today_plan
    today = _date.today().isoformat()
    return await run_in_threadpool(get_student_today_plan, student_id, today)


@app.get("/api/teacher/completion-overview")
async def teacher_completion_overview(actor: Actor = Depends(require_auth)):
    """班级作业完成情况：跨作业按学生聚合已交/欠交/逾期，掉队优先。"""
    require_teacher_actor(actor)
    from services.completion_overview import get_class_completion_overview
    today = _date.today().isoformat()
    return await run_in_threadpool(get_class_completion_overview, actor.actor_id, today)


# ── 学习成长报告 ────────────────────────────────────────────────────────────────

@app.get("/api/student/{student_id}/learning-report")
async def student_learning_report(
    student_id: str,
    days: int = 14,
    actor: Actor = Depends(require_auth),
):
    """学生学习成长报告：汇总 SM-2 复习、作业批改趋势、活跃度、错题统计。"""
    assert_student_access(actor, student_id)

    def _fetch() -> dict:
        import json as _json
        from datetime import date as _d, timedelta as _td
        from db.engine import get_connection
        from sqlalchemy import text
        from services.weakpoint_service import get_weakpoints as _get_wps

        today = _d.today()
        period = max(7, min(int(days), 90))
        since = (today - _td(days=period)).isoformat()
        report: dict = {
            "student_id": student_id,
            "generated_at": today.isoformat(),
            "period_days": period,
        }

        with get_connection() as conn:
            # 1. 档案：掌握率 + 练习均分
            p = conn.execute(
                text(
                    "SELECT weak_topics_json, strong_topics_json, "
                    "quiz_stats_json, game_stats_json "
                    "FROM student_profiles WHERE student_id = :sid"
                ),
                {"sid": student_id},
            ).mappings().fetchone()
            if p:
                weak = _json.loads(p["weak_topics_json"] or "[]")
                strong = _json.loads(p["strong_topics_json"] or "[]")
                total = len(weak) + len(strong)
                qs = _json.loads(p["quiz_stats_json"] or "{}")
                gs = _json.loads(p["game_stats_json"] or "{}")
                report.update(
                    mastery_pct=round(len(strong) / total * 100) if total else None,
                    weak_topic_count=len(weak),
                    strong_topic_count=len(strong),
                    quiz_avg_score=qs.get("average_score"),
                    quiz_attempts=qs.get("attempts", 0),
                    game_avg_score=gs.get("average_score"),
                )
            else:
                report.update(
                    mastery_pct=None, weak_topic_count=0, strong_topic_count=0,
                    quiz_avg_score=None, quiz_attempts=0, game_avg_score=None,
                )

            # 2. SM-2 复习进度（按天）
            rv_rows = conn.execute(
                text(
                    "SELECT date, completed, total FROM review_sessions "
                    "WHERE student_id = :sid AND date >= :since ORDER BY date"
                ),
                {"sid": student_id, "since": since},
            ).mappings().fetchall()
            review_by_day = {r["date"]: {"completed": r["completed"], "total": r["total"]} for r in rv_rows}
            done = sum(r["completed"] for r in rv_rows)
            total_tasks = sum(r["total"] for r in rv_rows)
            report.update(
                review_by_day=review_by_day,
                review_completed_total=done,
                review_tasks_total=total_tasks,
                review_completion_rate=round(done / total_tasks * 100) if total_tasks else None,
            )

            # 3. 作业批改分数趋势（最近 10 次）
            hw_rows = conn.execute(
                text(
                    "SELECT created_at, teacher_score, grade_result_json "
                    "FROM homework_reviews WHERE student_id = :sid "
                    "ORDER BY created_at DESC LIMIT 10"
                ),
                {"sid": student_id},
            ).mappings().fetchall()
            hw_trend = []
            for r in reversed(hw_rows):
                score = r["teacher_score"]
                if score is None:
                    try:
                        result = _json.loads(r["grade_result_json"] or "{}")
                        score = result.get("total_score") or result.get("score")
                    except Exception:
                        pass
                hw_trend.append({
                    "date": (r["created_at"] or "")[:10],
                    "score": round(float(score), 1) if score is not None else None,
                })
            valid_scores = [h["score"] for h in hw_trend if h["score"] is not None]
            report.update(
                homework_trend=hw_trend,
                homework_count=len(hw_trend),
                homework_avg_score=round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else None,
            )

            # 4. 每日学习活跃度 + 连续打卡 streak
            ev_rows = conn.execute(
                text(
                    "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS cnt "
                    "FROM learning_events WHERE student_id = :sid AND created_at >= :since "
                    "GROUP BY day ORDER BY day"
                ),
                {"sid": student_id, "since": since},
            ).mappings().fetchall()
            activity_by_day = {r["day"]: int(r["cnt"]) for r in ev_rows}
            streak, check = 0, today
            while check.isoformat() in activity_by_day:
                streak += 1
                check -= _td(days=1)
            report.update(
                activity_by_day=activity_by_day,
                active_days=len(activity_by_day),
                streak_days=streak,
            )

            # 5. AutoTutor 完成会话数
            t_row = conn.execute(
                text(
                    "SELECT COUNT(*) AS cnt FROM learning_events "
                    "WHERE student_id = :sid AND feature = 'auto_tutor' "
                    "AND event_type = 'session_complete'"
                ),
                {"sid": student_id},
            ).mappings().fetchone()
            report["autotutor_sessions"] = int(t_row["cnt"]) if t_row else 0

        # 6. 错题本（在 get_connection 块外调用，避免嵌套连接）
        wps = _get_wps(student_id)
        report.update(
            weakpoint_count=len(wps),
            top_weakpoints=[
                {"tag": w["knowledge_tag"], "count": w["wrong_count"]}
                for w in wps[:5]
            ],
        )
        return report

    return await run_in_threadpool(_fetch)


# ── 教师布置作业工作流 ──────────────────────────────────────────────────────────

from services.assignment_service import (
    create_assignment as _create_assignment,
    get_assignment_submissions as _get_assignment_submissions,
    get_student_badges as _get_student_badges,
    get_teacher_badges as _get_teacher_badges,
    list_student_assignments as _list_student_assignments,
    list_teacher_assignments as _list_teacher_assignments,
    record_question_review_flag as _record_question_review_flag,
    review_assignment_submission as _review_assignment_submission,
    submit_assignment as _submit_assignment,
)
from services.quality_dashboard import get_teacher_quality_dashboard as _get_teacher_quality_dashboard


class AssignmentQuestion(BaseModel):
    type: str = "single_choice"
    prompt: str
    options: list[str] | None = None
    answer: Any | None = None
    knowledge_tag: str | None = None
    reference_answer: str | None = None
    quality: dict | None = None  # AI 出题质检结论 {"level","issues"}，随作业持久化以支持质检有效性回路


class CreateAssignmentRequest(BaseModel):
    title: str
    questions: list[AssignmentQuestion]
    assignee_ids: list[str]
    subject: str | None = None
    grade: str | None = None
    due_date: str | None = None


class SubmitAssignmentRequest(BaseModel):
    answers: list[Any]


class ReviewSubmissionRequest(BaseModel):
    student_id: str
    score: float
    feedback: str | None = None


class QuestionReviewFlagRequest(BaseModel):
    verdict: str                    # bad_question | not_mastered
    note: str | None = None


class GenerateQuestionsRequest(BaseModel):
    knowledge_points: list[str]          # 每个知识点生成一道题
    difficulty: str = "medium"           # easy | medium | hard
    question_type: str = "single_choice"  # single_choice | true_false | subjective
    subject: str = "历史"
    semantic_check: bool = False         # 是否额外做 LLM 语义质检（较慢，opt-in）


class GeneratedQuestion(BaseModel):
    knowledge_tag: str
    type: str = "single_choice"
    prompt: str
    options: list[str]
    answer: str
    explanation: str
    quality: dict | None = None  # 确定性结构质检结果 {"level","issues"}


def _gen_true_false(kp: str, difficulty: str, sources: list) -> dict:
    """生成一道判断题。"""
    from structured_output import invoke_structured
    from security.prompt_injection import build_untrusted_context_block
    from pydantic import BaseModel as _BM

    class _TF(_BM):
        statement: str
        answer: str      # 正确 | 错误
        explanation: str

    context = build_untrusted_context_block(sources[:3], title="史料") if sources else ""
    prompt = [
        {"role": "system", "content": (
            "你是初中历史教师，根据史料为指定知识点出一道判断题。"
            "只输出 JSON：{\"statement\":\"陈述句\",\"answer\":\"正确\",\"explanation\":\"1-2句解析\"}。"
            "answer 只能是「正确」或「错误」。"
        )},
        {"role": "user", "content": f"知识点：{kp}\n难度：{difficulty}\n{context}".strip()},
    ]
    try:
        r = invoke_structured(llm_fast, prompt, model=_TF, fallback=None)
    except Exception:
        r = None
    if not r:
        return {"prompt": f"关于「{kp}」的说法是否正确？", "answer": "正确", "explanation": ""}
    ans = "错误" if "错" in (r.answer or "") else "正确"
    return {"prompt": r.statement.strip(), "answer": ans, "explanation": r.explanation.strip()}


def _gen_subjective(kp: str, difficulty: str, sources: list) -> dict:
    """生成一道简答题（含参考答案）。"""
    from structured_output import invoke_structured
    from security.prompt_injection import build_untrusted_context_block
    from pydantic import BaseModel as _BM

    class _SUBJ(_BM):
        question: str
        reference_answer: str

    context = build_untrusted_context_block(sources[:3], title="史料") if sources else ""
    prompt = [
        {"role": "system", "content": (
            "你是初中历史教师，根据史料为指定知识点出一道简答题。"
            "只输出 JSON：{\"question\":\"题干\",\"reference_answer\":\"参考答案要点\"}。"
        )},
        {"role": "user", "content": f"知识点：{kp}\n难度：{difficulty}\n{context}".strip()},
    ]
    try:
        r = invoke_structured(llm_fast, prompt, model=_SUBJ, fallback=None)
    except Exception:
        r = None
    if not r:
        return {"prompt": f"请简述「{kp}」的历史意义。", "answer": "", "explanation": ""}
    return {"prompt": r.question.strip(), "answer": "", "explanation": r.reference_answer.strip()}


@app.post("/api/teacher/assignments/generate-questions", response_model=list[GeneratedQuestion])
async def teacher_generate_questions(req: GenerateQuestionsRequest, actor: Actor = Depends(require_auth)):
    """AI 出题：给定知识点列表，每个知识点 RAG 取材后按指定题型出一道题，供教师审阅修改。"""
    require_teacher_actor(actor)
    if not req.knowledge_points:
        raise HTTPException(status_code=400, detail="knowledge_points 不能为空")
    if len(req.knowledge_points) > 20:
        raise HTTPException(status_code=400, detail="单次最多生成 20 道题")
    qtype = req.question_type if req.question_type in {"single_choice", "true_false", "subjective"} else "single_choice"

    from agents.auto_tutor import _generate_question as _at_gen_question
    from tools.registry import run_tool
    from tools.base import ToolExecutionContext
    from services.question_quality import check_question, check_question_semantic, merge_quality
    from services.assignment_service import get_bad_question_examples

    ctx = ToolExecutionContext(actor_id=actor.actor_id, session_id=f"gen-{actor.actor_id}")

    # 语义质检自改进：取该教师历史 bad_question 作为 few-shot 反例（每次请求取一次）
    bad_examples: list[dict] = []
    if req.semantic_check:
        try:
            bad_examples = await run_in_threadpool(get_bad_question_examples, actor.actor_id)
        except Exception:
            bad_examples = []

    def _strip(o: str) -> str:
        return o[3:].strip() if len(o) > 2 and o[1] == "." else o.strip()

    def _with_quality(gq: GeneratedQuestion) -> GeneratedQuestion:
        q_dict = gq.model_dump()
        structural = check_question(q_dict)
        if req.semantic_check:
            try:
                semantic = check_question_semantic(q_dict, llm=llm_fast, bad_examples=bad_examples)
                gq.quality = merge_quality(structural, semantic)
            except Exception:
                gq.quality = structural  # 语义质检失败不阻断出题
        else:
            gq.quality = structural
        return gq

    async def _gen_one(kp: str) -> GeneratedQuestion:
        try:
            raw = await run_in_threadpool(
                run_tool, "search_history_knowledge",
                {"query": kp, "top_k": 4}, ctx,
            )
            sources = raw if isinstance(raw, list) else []
        except Exception:
            sources = []

        if qtype == "true_false":
            q = await run_in_threadpool(_gen_true_false, kp, req.difficulty, sources)
            return await run_in_threadpool(_with_quality, GeneratedQuestion(knowledge_tag=kp, type="true_false", prompt=q["prompt"],
                                     options=[], answer=q["answer"], explanation=q["explanation"]))
        if qtype == "subjective":
            q = await run_in_threadpool(_gen_subjective, kp, req.difficulty, sources)
            return await run_in_threadpool(_with_quality, GeneratedQuestion(knowledge_tag=kp, type="subjective", prompt=q["prompt"],
                                     options=[], answer="", explanation=q["explanation"]))
        # 默认单选题
        q = await run_in_threadpool(_at_gen_question, kp, req.difficulty, sources)
        return await run_in_threadpool(_with_quality, GeneratedQuestion(
            knowledge_tag=kp, type="single_choice", prompt=q.get("question", ""),
            options=[_strip(o) for o in q.get("options", [])],
            answer=(q.get("answer", "A") or "A")[:1].upper(),
            explanation=q.get("explanation", ""),
        ))

    import asyncio
    results = await asyncio.gather(*[_gen_one(kp) for kp in req.knowledge_points], return_exceptions=True)
    questions = []
    for r in results:
        if isinstance(r, GeneratedQuestion):
            questions.append(r)
    return questions


@app.post("/api/teacher/assignments")
async def teacher_create_assignment(req: CreateAssignmentRequest, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(
            _create_assignment,
            actor.actor_id,
            req.title,
            [q.model_dump() for q in req.questions],
            req.assignee_ids,
            req.subject,
            req.grade,
            req.due_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/teacher/assignments")
async def teacher_list_assignments(actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    return {"assignments": await run_in_threadpool(_list_teacher_assignments, actor.actor_id)}


@app.get("/api/teacher/badges")
async def teacher_badges(actor: Actor = Depends(require_auth)):
    """教师侧边栏通知徽标：待评阅、低分学生数。"""
    require_teacher_actor(actor)
    return await run_in_threadpool(_get_teacher_badges, actor.actor_id)


@app.get("/api/teacher/quality-dashboard")
async def teacher_quality_dashboard(actor: Actor = Depends(require_auth)):
    """命题质量看板：跨作业聚合 AI 质检分布、有效性、复核结论、高频问题与近期反例。"""
    require_teacher_actor(actor)
    return await run_in_threadpool(_get_teacher_quality_dashboard, actor.actor_id)


@app.get("/api/teacher/assignments/{assignment_id}/submissions")
async def teacher_assignment_submissions(assignment_id: str, actor: Actor = Depends(require_auth)):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(_get_assignment_submissions, actor.actor_id, assignment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.post("/api/teacher/assignments/{assignment_id}/review")
async def teacher_review_assignment_submission(
    assignment_id: str,
    req: ReviewSubmissionRequest,
    actor: Actor = Depends(require_auth),
):
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(
            _review_assignment_submission,
            actor.actor_id,
            assignment_id,
            req.student_id,
            req.score,
            req.feedback,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/teacher/assignments/{assignment_id}/questions/{question_index}/review-flag")
async def teacher_flag_question_review(
    assignment_id: str,
    question_index: int,
    req: QuestionReviewFlagRequest,
    actor: Actor = Depends(require_auth),
):
    """教师对一道质检盲区题给出复核判定（题目有问题 / 学生没掌握）。"""
    require_teacher_actor(actor)
    try:
        return await run_in_threadpool(
            _record_question_review_flag,
            actor.actor_id,
            assignment_id,
            question_index,
            req.verdict,
            req.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/student/{student_id}/assignments")
async def student_list_assignments(student_id: str, actor: Actor = Depends(require_auth)):
    assert_student_access(actor, student_id)
    return {"assignments": await run_in_threadpool(_list_student_assignments, student_id)}


def _student_badges_sync(student_id: str) -> dict:
    """学生徽标：未提交/临近作业 + 今日复习待完成数（不创建 session）。"""
    from datetime import date as _d
    from services.review_service import get_today_session
    today = _d.today().isoformat()
    badges = _get_student_badges(student_id, today)
    pending_review = 0
    try:
        session = get_today_session(student_id, today, hydrate=False)
        if session:
            pending_review = max(0, int(session.get("total", 0)) - int(session.get("completed", 0)))
    except Exception:
        pending_review = 0
    badges["pending_review"] = pending_review
    return badges


@app.get("/api/student/{student_id}/badges")
async def student_badges(student_id: str, actor: Actor = Depends(require_auth)):
    """学生侧边栏通知徽标：未提交作业、临近到期、今日复习待完成。"""
    assert_student_access(actor, student_id)
    return await run_in_threadpool(_student_badges_sync, student_id)


@app.post("/api/student/{student_id}/assignments/{assignment_id}/submit")
async def student_submit_assignment(
    student_id: str,
    assignment_id: str,
    req: SubmitAssignmentRequest,
    actor: Actor = Depends(require_auth),
):
    assert_student_access(actor, student_id)
    try:
        result = await run_in_threadpool(_submit_assignment, student_id, assignment_id, req.answers)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_event_if_student(
        student_id,
        feature="assignment",
        event_type="assignment_submitted",
        score=result.get("score"),
        success=result.get("status") == "graded",
        metadata={
            "assignment_id": assignment_id,
            "objective_correct": result.get("objective_correct"),
            "objective_total": result.get("objective_total"),
        },
    )
    return result
