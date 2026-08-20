"""历史功能路由：/api/history/*（人物、游戏、地图、辩论）"""
import asyncio
import logging
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from agent_runtime.event_store import get_run
from security.auth import Actor, assert_student_access, assert_teacher_student_access, require_auth
from tracing import current_trace_id, trace_context
from ._shared import sse_frame, record_event_if_student, enforce_guardrails, trace_meta

router = APIRouter(tags=["history"])
logger = logging.getLogger(__name__)


# ── Request models ────────────────────────────────────────────────────────────

class CharacterRequest(BaseModel):
    character: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    student_id: str | None = None
    grade: str | None = None
    stream: bool = True
    mode: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)

class CharacterRecommendRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
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

class DebateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


# ── Character routes ──────────────────────────────────────────────────────────

def _next(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _history_session_key(actor: Actor, session_id: str | None, student_id: str | None) -> str | None:
    if not session_id:
        return None
    owner = actor.actor_id or "anonymous"
    subject = student_id or owner
    return f"history-character:{owner}:{subject}:{session_id}"


def _assert_history_student_access(actor: Actor, student_id: str) -> None:
    if actor.role == "teacher":
        assert_teacher_student_access(actor, student_id)
        return
    assert_student_access(actor, student_id)


def _assert_round_access(actor: Actor, round_id: str) -> None:
    from game_store import load_round

    record = load_round(round_id)
    if not record:
        return
    student_id = record.get("student_id")
    if student_id:
        _assert_history_student_access(actor, str(student_id))


def _observable_subgraph_run(
    *,
    agent_type: str,
    operation: str,
    actor: Actor,
    student_id: str | None,
    session_id: str | None,
    trace_id: str,
    objective: str,
    idempotency_key: str | None,
):
    from agent_runtime.models import AgentPlan, AgentStep
    from agent_runtime.product_runtime import ObservableProductRun

    plan = AgentPlan(
        plan_id=f"plan_{uuid4().hex}",
        objective=objective,
        strategy="subgraph",
        steps=[AgentStep(step_id="execute", kind="subgraph", operation=operation, side_effect="external_call", risk_level="low", timeout_seconds=120)],
        generated_by="template",
        planner_version=f"{agent_type}-v1.33",
    )
    return ObservableProductRun.start(
        agent_type=agent_type,
        actor_id=actor.actor_id,
        actor_role=actor.role,
        student_id=student_id,
        session_id=session_id,
        trace_id=trace_id,
        objective=objective,
        plan=plan,
        idempotency_key=idempotency_key,
    )


def _source_ids(sources: list[dict]) -> list[str]:
    return [
        str(source.get("source_id") or source.get("citation_label"))
        for source in sources
        if source.get("source_id") or source.get("citation_label")
    ]


def _debate_claims_grounded(result: dict) -> bool:
    sources = result.get("sources") or []
    known_sources = set(_source_ids(sources))
    claims = ((result.get("fact_check") or {}).get("claims") or [])
    return bool(known_sources) and bool(claims) and result.get("completion_status", "completed") == "completed" and all(
        bool(claim.get("supported"))
        and bool(claim.get("source_ids"))
        and set(map(str, claim.get("source_ids") or [])) <= known_sources
        for claim in claims
    )


@router.post("/api/history/character/recommend")
async def character_recommend(req: CharacterRecommendRequest, actor: Actor = Depends(require_auth)):
    from agents.character_recommender import recommend_characters
    if req.student_id:
        _assert_history_student_access(actor, req.student_id)
    with trace_context(name="POST /api/history/character/recommend", metadata=trace_meta("history_character_recommend", "/api/history/character/recommend", student_id=req.student_id, grade=req.grade, limit=req.limit, stream=False), user_id=req.student_id):
        enforce_guardrails(req.message, actor=actor, route="/api/history/character/recommend", student_id=req.student_id, resource_type="student" if req.student_id else None)
        recommendations = recommend_characters(req.message, req.grade, req.limit)
        record_event_if_student(req.student_id, feature="history_character", event_type="character_recommended", grade=req.grade, success=True, metadata={"characters": [item.get("name") for item in recommendations if item.get("name")]})
        return {"recommendations": [CharacterRecommendation(**item).model_dump() for item in recommendations]}


@router.post("/api/history/character/chat")
async def character_chat(req: CharacterRequest, actor: Actor = Depends(require_auth)):
    from agents.history_character import stream_character_response, detect_mode
    from rag.knowledge_base import get_retriever
    from session_store import load_messages, save_messages

    if req.student_id:
        _assert_history_student_access(actor, req.student_id)
    retriever = get_retriever("history")
    mode = req.mode or detect_mode(req.message)
    session_key = _history_session_key(actor, req.session_id, req.student_id)
    history = load_messages(session_key) if session_key else []
    state = {
        "character": req.character, "grade": req.grade, "session_id": req.session_id,
        "student_id": req.student_id,
        "messages": history + [{"role": "user", "content": req.message}],
        "retrieved_facts": [], "retrieved_sources": [], "response_draft": "",
        "verified": False, "mode": mode,
    }
    metadata = trace_meta("history_character_chat", "/api/history/character/chat", session_id=req.session_id, student_id=req.student_id, character=req.character, grade=req.grade, mode=mode, stream=req.stream)

    if not req.stream:
        with trace_context(name="POST /api/history/character/chat", metadata=metadata, user_id=req.student_id, session_id=req.session_id):
            enforce_guardrails(req.message, actor=actor, route="/api/history/character/chat", student_id=req.student_id, resource_type="character", resource_id=req.character)
            runtime = _observable_subgraph_run(
                agent_type="history_character",
                operation="history_character.answer",
                actor=actor,
                student_id=req.student_id,
                session_id=req.session_id,
                trace_id=current_trace_id(),
                objective="历史人物有据回答",
                idempotency_key=req.idempotency_key,
            )
            replay = runtime.replay_output() if runtime and runtime.replay else None
            if replay is not None:
                return replay
            try:
                events = await run_in_threadpool(lambda: list(stream_character_response(state, retriever)))
                final = next((item["data"] for item in events if item["event"] == "final"), None)
                if final is None:
                    raise HTTPException(status_code=502, detail="历史人物回答未产生终态")
                fact_card = next((item["data"].get("card") for item in events if item["event"] == "fact_card"), None)
                final = {**final, "fact_card": fact_card, "memory_updated": bool(state.get("memory_updated"))}
                if runtime:
                    verified = bool(final.get("verified"))
                    final = runtime.finish(
                        final,
                        status="completed" if verified else "partial",
                        verification_status="verified" if verified else "failed",
                        reason_codes=["history_character_verified" if verified else str(final.get("verification_reason") or "history_character_verification_failed")],
                        source_ids=_source_ids(final.get("sources") or []),
                    )
            except Exception as exc:
                if runtime:
                    runtime.fail(exc)
                raise
            if session_key and final.get("response"):
                save_messages(session_key, history + [
                    {"role": "user", "content": req.message},
                    {"role": "assistant", "content": final["response"]},
                ])
            record_event_if_student(req.student_id, session_id=req.session_id, feature="history_character", event_type="character_chat", grade=req.grade, topic=req.character, success=bool(final.get("verified")), metadata={"character": req.character, "mode": mode, "verified": final.get("verified", False)})
            return final

    async def event_stream():
        with trace_context(name="POST /api/history/character/chat", metadata=metadata, user_id=req.student_id, session_id=req.session_id):
            trace_id = current_trace_id()
            runtime = None
            try:
                enforce_guardrails(req.message, actor=actor, route="/api/history/character/chat", student_id=req.student_id, resource_type="character", resource_id=req.character)
                if trace_id:
                    yield sse_frame("trace", {"trace_id": trace_id})
                runtime = _observable_subgraph_run(
                    agent_type="history_character",
                    operation="history_character.answer",
                    actor=actor,
                    student_id=req.student_id,
                    session_id=req.session_id,
                    trace_id=trace_id,
                    objective="历史人物有据回答",
                    idempotency_key=req.idempotency_key,
                )
                replay = runtime.replay_output() if runtime and runtime.replay else None
                if replay is not None:
                    yield sse_frame("final", replay)
                    return
                if runtime:
                    yield sse_frame("run_started", {"run_id": runtime.run_id, "event_cursor": runtime.milestone("tool_started", {"operation": "history.retrieve"})})
                final_response = None
                final_data = None
                fact_card = None
                yield sse_frame("status", {"phase": "retrieving", "message": "正在检索广东初中历史史料"})
                for item in stream_character_response(state, retriever):
                    event, data = item["event"], item["data"]
                    if event == "sources":
                        yield sse_frame("sources", data)
                        yield sse_frame("status", {"phase": "generating", "message": "正在生成教学模拟回答"})
                    elif event in ("delta", "status", "fact_card"):
                        if event == "fact_card":
                            fact_card = data.get("card")
                        yield sse_frame(event, data)
                    elif event == "final":
                        final_response = data.get("response", "")
                        final_data = dict(data)
                        if runtime:
                            data = {**data, "run_id": runtime.run_id, "event_cursor": get_run(runtime.run_id)["last_event_sequence"]}
                        yield sse_frame("final", data)
                        yield sse_frame("status", {"phase": "done", "message": "已完成"})
                        if trace_id:
                            yield sse_frame("trace", {"trace_id": trace_id})
                    await asyncio.sleep(0)
                if runtime and final_data is not None:
                    verified = bool(final_data.get("verified"))
                    terminal = runtime.finish(
                        {**final_data, "fact_card": fact_card, "memory_updated": bool(state.get("memory_updated"))},
                        status="completed" if verified else "partial",
                        verification_status="verified" if verified else "failed",
                        reason_codes=["history_character_verified" if verified else str(final_data.get("verification_reason") or "history_character_verification_failed")],
                        source_ids=_source_ids(final_data.get("sources") or []),
                    )
                    yield sse_frame("runtime_terminal", terminal)
                if final_response:
                    record_event_if_student(req.student_id, session_id=req.session_id, feature="history_character", event_type="character_chat", grade=req.grade, topic=req.character, success=bool(state.get("verified")), metadata={"character": req.character, "mode": mode, "verified": bool(state.get("verified"))})
                if session_key and final_response:
                    history2 = load_messages(session_key)
                    history2.append({"role": "user", "content": req.message})
                    history2.append({"role": "assistant", "content": final_response})
                    save_messages(session_key, history2)
            except HTTPException as exc:
                yield sse_frame("error", {"message": exc.detail})
            except Exception as exc:
                if runtime:
                    runtime.fail(exc)
                yield sse_frame("error", {"message": str(exc) or "stream failed"})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Games ─────────────────────────────────────────────────────────────────────

@router.get("/api/history/games")
async def history_games(actor: Actor = Depends(require_auth)):
    from agents.history_games import list_history_games
    return {"games": list_history_games()}


@router.post("/api/history/games/timeline/start")
async def timeline_start(req: TimelineStartRequest, actor: Actor = Depends(require_auth)):
    from agents.history_games import start_timeline_round
    if req.student_id:
        _assert_history_student_access(actor, req.student_id)
    with trace_context(name="POST /api/history/games/timeline/start", metadata=trace_meta("history_timeline_start", "/api/history/games/timeline/start", student_id=req.student_id, grade=req.grade, difficulty=req.difficulty, topic=req.topic, mode=req.mode, stream=False), user_id=req.student_id):
        try:
            result = start_timeline_round(req.grade, req.difficulty, req.topic, req.student_id, req.mode)
            record_event_if_student(req.student_id, feature="history_timeline", event_type="timeline_game_started", grade=req.grade or result.get("grade"), topic=req.topic or result.get("topic"), success=True, metadata={"round_id": result.get("round_id"), "difficulty": req.difficulty, "source": result.get("source")})
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/history/games/timeline/submit")
async def timeline_submit(req: TimelineSubmitRequest, actor: Actor = Depends(require_auth)):
    from agents.history_games import submit_timeline_round
    _assert_round_access(actor, req.round_id)
    try:
        result = submit_timeline_round(req.round_id, req.ordered_event_ids)
        total = result.get("total") or len(result.get("correct_order") or req.ordered_event_ids)
        correct = result.get("score") or 0
        score = float(correct) / total if isinstance(correct, (int, float)) and total else None
        if req.record_event:
            record_event_if_student(result.get("student_id"), feature="history_timeline", event_type="timeline_game_submitted", topic=result.get("topic"), score=score, success=bool(result.get("is_correct", score == 1 if score is not None else False)), metadata={"round_id": req.round_id, "total": total})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/history/card-game/start")
async def card_game_start(req: CardGameStartRequest, actor: Actor = Depends(require_auth)):
    from agents.history_games import start_card_game_round
    if req.student_id:
        _assert_history_student_access(actor, req.student_id)
    with trace_context(name="POST /api/history/card-game/start", metadata=trace_meta("history_card_game_start", "/api/history/card-game/start", student_id=req.student_id, grade=req.grade, difficulty=req.difficulty, topic=req.topic, mode=req.mode, stream=False), user_id=req.student_id):
        try:
            result = start_card_game_round(req.grade, req.difficulty, req.topic, req.student_id, req.mode)
            record_event_if_student(req.student_id, feature="history_card_game", event_type="card_game_started", grade=req.grade or result.get("grade"), topic=req.topic or result.get("topic"), success=True, metadata={"round_id": result.get("round_id"), "difficulty": req.difficulty, "source": result.get("source")})
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/history/card-game/submit")
async def card_game_submit(req: CardGameSubmitRequest, actor: Actor = Depends(require_auth)):
    from agents.history_games import submit_card_game_round
    _assert_round_access(actor, req.round_id)
    try:
        result = submit_card_game_round(req.round_id, req.submitted_card_ids)
        total = result.get("total") or len(result.get("correct_order") or req.submitted_card_ids)
        correct = result.get("score") or 0
        score = float(correct) / total if isinstance(correct, (int, float)) and total else None
        record_event_if_student(result.get("student_id"), feature="history_card_game", event_type="card_game_submitted", grade=result.get("grade"), topic=result.get("topic"), score=score, success=score == 1 if score is not None else None, metadata={"round_id": req.round_id, "total": total, "can_retry": result.get("can_retry")})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/history/card-game/retry")
async def card_game_retry(req: CardGameRetryRequest, actor: Actor = Depends(require_auth)):
    from agents.history_games import retry_card_game_round
    _assert_round_access(actor, req.round_id)
    try:
        result = retry_card_game_round(req.round_id, req.revised_card_ids)
        total = result.get("total") or len(result.get("correct_order") or req.revised_card_ids)
        correct = result.get("score") or 0
        score = float(correct) / total if isinstance(correct, (int, float)) and total else None
        record_event_if_student(result.get("student_id"), feature="history_card_game", event_type="card_game_retry_submitted", grade=result.get("grade"), topic=result.get("topic"), score=score, success=score == 1 if score is not None else None, metadata={"round_id": req.round_id, "total": total})
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/history/card-game/report/{student_id}")
async def card_game_report(student_id: str, actor: Actor = Depends(require_auth)):
    from agents.history_games import get_card_game_report
    _assert_history_student_access(actor, student_id)
    return get_card_game_report(student_id)


@router.post("/api/history/multiplayer/start")
async def multiplayer_start(req: MultiplayerStartRequest, actor: Actor = Depends(require_auth)):
    from agents.multiplayer_game import start_multiplayer_round
    if req.student_id:
        _assert_history_student_access(actor, req.student_id)
    with trace_context(name="POST /api/history/multiplayer/start", metadata=trace_meta("history_multiplayer_start", "/api/history/multiplayer/start", student_id=req.student_id, grade=req.grade, difficulty=req.difficulty, topic=req.topic, ai_count=req.ai_count, ai_difficulty=req.ai_difficulty, mode=req.mode, stream=False), user_id=req.student_id):
        try:
            return await run_in_threadpool(start_multiplayer_round, req.grade, req.difficulty, req.topic, req.student_id, req.ai_count, req.ai_difficulty, req.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/history/multiplayer/play")
async def multiplayer_play(req: MultiplayerPlayRequest, actor: Actor = Depends(require_auth)):
    from agents.multiplayer_game import play_human_turn
    _assert_round_access(actor, req.round_id)
    try:
        return play_human_turn(req.round_id, req.player_id, req.card_id, req.insert_index)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/history/multiplayer/ai-turn")
async def multiplayer_ai_turn(req: MultiplayerAiTurnRequest, actor: Actor = Depends(require_auth)):
    from agents.multiplayer_game import play_ai_turn
    _assert_round_access(actor, req.round_id)
    try:
        return play_ai_turn(req.round_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Geo / Map ─────────────────────────────────────────────────────────────────

@router.get("/api/history/geo/events")
async def get_geo_events(dynasty: str | None = None, year_start: int | None = None, year_end: int | None = None, actor: Actor = Depends(require_auth)):
    from agents.history_map_agent import get_events_by_dynasty
    events = await run_in_threadpool(get_events_by_dynasty, dynasty, year_start, year_end)
    return {"events": events}


@router.get("/api/history/geo/narrate")
async def narrate_geo_event(event_id: str, user_query: str = "", actor: Actor = Depends(require_auth)):
    from agents.history_map_agent import stream_map_narrate
    import json
    if user_query:
        enforce_guardrails(user_query, actor=actor, route="/api/history/geo/narrate", resource_type="geo_event", resource_id=event_id)
    async def event_stream():
        try:
            iterator = stream_map_narrate(event_id, user_query)
            while True:
                chunk = await run_in_threadpool(_next, iterator)
                if chunk is None:
                    break
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
        except Exception:
            logger.exception("history_geo_narration_stream_failed event_id=%s", event_id)
            error = {"event": "error", "data": {"message": "地图讲解暂不可用，请稍后重试。"}}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/history/geo/chat")
async def chat_with_map(query: str, actor: Actor = Depends(require_auth)):
    from agents.history_map_agent import handle_chat_query
    enforce_guardrails(query, actor=actor, route="/api/history/geo/chat", resource_type="geo_chat")
    return await run_in_threadpool(handle_chat_query, query)


# ── Debate ────────────────────────────────────────────────────────────────────

@router.post("/api/history/debate/start")
async def start_debate(req: DebateRequest, actor: Actor = Depends(require_auth)):
    from agents.debate_supervisor import run_debate
    from security.prompt_injection import check_user_input
    check_user_input(req.topic)
    with trace_context(name="POST /api/history/debate/start", metadata=trace_meta("debate", "/api/history/debate/start", topic_chars=len(req.topic)), user_id=actor.actor_id):
        runtime = _observable_subgraph_run(
            agent_type="debate",
            operation="debate.run",
            actor=actor,
            student_id=None,
            session_id=None,
            trace_id=current_trace_id(),
            objective="历史辩论固定三轮有据执行",
            idempotency_key=req.idempotency_key,
        )
        replay = runtime.replay_output() if runtime and runtime.replay else None
        if replay is not None:
            return replay
        try:
            result = await run_debate(req.topic, trace_id=current_trace_id())
            if runtime:
                sources = result.get("sources") or []
                grounded = _debate_claims_grounded(result)
                result = runtime.finish(
                    result,
                    status="completed" if grounded else "partial",
                    verification_status="verified" if grounded else "failed",
                    reason_codes=["debate_fact_claims_grounded" if grounded else "debate_evidence_incomplete"],
                    source_ids=_source_ids(sources),
                )
        except Exception as exc:
            if runtime:
                runtime.fail(exc)
            raise
    return result


@router.post("/api/history/debate/stream")
async def stream_debate_endpoint(req: DebateRequest, actor: Actor = Depends(require_auth)):
    from agents.debate_supervisor import stream_debate
    from security.prompt_injection import check_user_input
    import json
    check_user_input(req.topic)
    async def event_stream():
        with trace_context(name="POST /api/history/debate/stream", metadata=trace_meta("debate", "/api/history/debate/stream", topic_chars=len(req.topic)), user_id=actor.actor_id):
            trace_id = current_trace_id()
            runtime = _observable_subgraph_run(
                agent_type="debate",
                operation="debate.run",
                actor=actor,
                student_id=None,
                session_id=None,
                trace_id=trace_id,
                objective="历史辩论固定三轮有据执行",
                idempotency_key=req.idempotency_key,
            )
            replay = runtime.replay_output() if runtime and runtime.replay else None
            if replay is not None:
                yield sse_frame("done", replay)
                return
            result = {"topic": req.topic, "rounds": [], "sources": [], "fact_check": None, "verdict": "", "coach_summary": ""}
            try:
                if runtime:
                    yield sse_frame("run_started", {"run_id": runtime.run_id, "event_cursor": get_run(runtime.run_id)["last_event_sequence"]})
                async for item in stream_debate(req.topic, trace_id=trace_id):
                    event, data = item["event"], item["data"]
                    if event == "round":
                        result["rounds"].append(data)
                    elif event == "fact_check":
                        result["fact_check"] = data
                        result["sources"] = data.get("sources") or []
                    elif event == "verdict":
                        result["verdict"] = data.get("verdict", "")
                    elif event == "coach_summary":
                        result["coach_summary"] = data.get("summary", "")
                    yield sse_frame(event, data)
                if runtime:
                    grounded = _debate_claims_grounded(result)
                    terminal = runtime.finish(
                        result,
                        status="completed" if grounded else "partial",
                        verification_status="verified" if grounded else "failed",
                        reason_codes=["debate_fact_claims_grounded" if grounded else "debate_evidence_incomplete"],
                        source_ids=_source_ids(result["sources"]),
                    )
                    yield sse_frame("runtime_terminal", terminal)
            except Exception as exc:
                if runtime:
                    runtime.fail(exc)
                yield sse_frame("error", {"message": str(exc) or "debate stream failed"})
    return StreamingResponse(event_stream(), media_type="text/event-stream")
