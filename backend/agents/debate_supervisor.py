"""历史辩论 Agent — Supervisor-Worker 多 Agent 模式。"""
import asyncio
import os
from time import perf_counter
from typing import AsyncIterator, Callable, Literal, TypedDict

from fastapi.concurrency import run_in_threadpool
from langgraph.graph import END, StateGraph

from llm_config import llm_fast as llm, llm_quality as llm_judge
from trace_store import create_trace_id, emit_trace_event, trace_context as runtime_trace_context


class DebateState(TypedDict):
    topic: str
    rounds: list[dict]
    current_side: Literal["pro", "con"]
    round_count: int
    verdict: str


MAX_ROUNDS = 3


def _role_timeout_seconds() -> float:
    try:
        value = float(os.getenv("DEBATE_ROLE_TIMEOUT_SECONDS", "30"))
    except ValueError:
        value = 30.0
    return min(max(value, 1.0), 120.0)


def pro_agent(state: DebateState) -> DebateState:
    history = "\n".join(f"{r['side']}: {r['argument']}" for r in state["rounds"])
    resp = llm.invoke(
        f"辩题：{state['topic']}\n你持正方立场，基于历史史实论证。\n辩论记录：{history}\n请发言："
    )
    return {"rounds": state["rounds"] + [{"side": "pro", "argument": resp.content}],
            "current_side": "con"}


def con_agent(state: DebateState) -> DebateState:
    history = "\n".join(f"{r['side']}: {r['argument']}" for r in state["rounds"])
    resp = llm.invoke(
        f"辩题：{state['topic']}\n你持反方立场，基于历史史实反驳。\n辩论记录：{history}\n请发言："
    )
    return {"rounds": state["rounds"] + [{"side": "con", "argument": resp.content}],
            "current_side": "pro", "round_count": state["round_count"] + 1}


def judge(state: DebateState) -> DebateState:
    history = "\n".join(f"{r['side']}: {r['argument']}" for r in state["rounds"])
    resp = llm_judge.invoke(
        f"辩题：{state['topic']}\n辩论记录：{history}\n"
        "从论点、论据、逻辑三维度评判双方，给出总结性裁决："
    )
    return {"verdict": resp.content}


def route(state: DebateState) -> str:
    if state["round_count"] >= MAX_ROUNDS:
        return "judge"
    return "pro" if state["current_side"] == "pro" else "con"


def build_debate_graph() -> StateGraph:
    g = StateGraph(DebateState)
    g.add_node("pro", pro_agent)
    g.add_node("con", con_agent)
    g.add_node("judge", judge)
    g.set_entry_point("pro")
    g.add_edge("pro", "con")
    g.add_conditional_edges("con", route, {"pro": "pro", "con": "con", "judge": "judge"})
    g.add_edge("judge", END)
    return g.compile()


async def _invoke_role(
    agent_name: str,
    step_name: str,
    model,
    prompt: str,
    *,
    fallback: str | None = None,
    on_fallback: Callable[[str], None] | None = None,
    force_fallback: bool = False,
    timeout_seconds: float | None = None,
    **metadata,
) -> str:
    started = perf_counter()
    if force_fallback and fallback is not None:
        content = fallback.strip()
        if on_fallback:
            on_fallback(agent_name)
        emit_trace_event(
            agent_name=agent_name,
            step_name=step_name,
            event_type="llm",
            status="success",
            latency_ms=0,
            metadata={
                **metadata,
                "configured_model": getattr(model, "model", None),
                "response_chars": len(content),
                "generation_mode": "fallback",
                "degraded": True,
                "degraded_reason": "CircuitOpen",
            },
        )
        return content
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(model.invoke, prompt),
            timeout=timeout_seconds or _role_timeout_seconds(),
        )
        content = str(response.content).strip()
        if not content:
            raise RuntimeError(f"{agent_name} returned empty content")
        emit_trace_event(
            agent_name=agent_name,
            step_name=step_name,
            event_type="llm",
            status="success",
            latency_ms=round((perf_counter() - started) * 1000),
            metadata={
                **metadata,
                "configured_model": getattr(model, "model", None),
                "response_chars": len(content),
            },
        )
        return content
    except Exception as exc:
        if fallback is not None:
            content = fallback.strip()
            if on_fallback:
                on_fallback(agent_name)
            emit_trace_event(
                agent_name=agent_name,
                step_name=step_name,
                event_type="llm",
                status="success",
                latency_ms=round((perf_counter() - started) * 1000),
                metadata={
                    **metadata,
                    "configured_model": getattr(model, "model", None),
                    "response_chars": len(content),
                    "generation_mode": "fallback",
                    "degraded": True,
                    "degraded_reason": exc.__class__.__name__,
                },
            )
            return content
        emit_trace_event(
            agent_name=agent_name,
            step_name=step_name,
            event_type="llm",
            status="error",
            latency_ms=round((perf_counter() - started) * 1000),
            metadata={**metadata, "error_type": exc.__class__.__name__},
        )
        raise


def _search_history_sources(topic: str) -> tuple[list[dict], str]:
    try:
        from rag.knowledge_base import search_with_scores

        rag_docs = search_with_scores("history", topic, k=4, mode="hybrid")
    except Exception:
        rag_docs = []

    sources = []
    snippets = []
    for index, item in enumerate(rag_docs[:3], start=1):
        document = item["document"]
        label = f"[史料{index}]"
        snippet = document.page_content[:200]
        sources.append({
            "citation_label": label,
            "topic": document.metadata.get("topic", ""),
            "source": document.metadata.get("source", ""),
            "snippet": snippet,
            "score": round(float(item.get("score", 0)), 3),
        })
        snippets.append(f"{label} {snippet}")
    return sources, "\n".join(snippets)


def _fallback_argument(topic: str, side: Literal["pro", "con"], round_number: int, sources: list[dict]) -> str:
    if not sources:
        position = "正方" if side == "pro" else "反方"
        return (
            f"{position}第{round_number}轮：当前没有检索到可核验史料，因此不能对“{topic}”作确定结论。"
            "本轮只提出论证要求：先明确评价标准，再补充教材史料后判断。"
        )
    source = sources[(round_number - 1) % len(sources)]
    label = str(source.get("citation_label") or "[史料]")
    snippet = str(source.get("snippet") or source.get("topic") or "该材料").strip()[:140]
    if side == "pro":
        return (
            f"正方第{round_number}轮依据{label}：{snippet}。"
            f"这条材料可以作为讨论“{topic}”的事实起点；正方主张评价时应重视它呈现的历史作用，但不把材料未说明的内容当作史实。"
        )[:200]
    return (
        f"反方第{round_number}轮回应{label}：{snippet}。"
        "同一材料只能支持其明确记载的事实，不能单凭一条材料概括全部利弊；还应比较代价、影响范围和不同群体的处境。"
    )[:200]


def _fallback_fact_check(sources: list[dict]) -> str:
    if not sources:
        return "当前未检索到可引用史料，无法核验具体史实；本场发言只能作为论证框架，不能作为史实结论。"
    lines = []
    for source in sources[:3]:
        label = str(source.get("citation_label") or "[史料]")
        snippet = str(source.get("snippet") or source.get("topic") or "").strip()[:180]
        lines.append(f"{label} 可核验内容：{snippet}；超出该材料的价值判断仍需更多史料交叉验证。")
    return "\n".join(lines)


def _fallback_verdict(topic: str, sources: list[dict]) -> str:
    evidence_note = "双方都引用了共享史料" if sources else "双方都没有足够史料"
    return (
        f"裁判结论：围绕“{topic}”，{evidence_note}。正方给出了评价起点，反方提醒不能由单一材料推出全部利弊。"
        "由于模型服务暂不可用，本裁决只评价论证结构，不判定具体史实或胜负；请以事实核查和教材证据为准。"
    )


def _fallback_coach_summary(topic: str, sources: list[dict]) -> str:
    source_tip = "逐条核对上方史料标签" if sources else "先从教材补充至少两条史料"
    return (
        f"1. 讨论“{topic}”要先区分史实与评价。\n"
        "2. 一个历史结论通常要同时比较作用、代价和影响范围。\n"
        f"3. 不把材料没有写出的内容当成事实。\n学习建议：{source_tip}，再形成自己的结论。"
    )


async def stream_debate(topic: str, *, trace_id: str | None = None) -> AsyncIterator[dict]:
    """逐轮生成辩论，并为每个角色记录可聚合的 runtime trace。"""
    runtime_trace_id = trace_id or create_trace_id()
    with runtime_trace_context(runtime_trace_id):
        rounds: list[dict] = []
        fallback_roles: set[str] = set()
        sources, rag_snippets = await run_in_threadpool(_search_history_sources, topic)
        shared_evidence = f"\n共享参考史料（只能引用这些标签）：\n{rag_snippets}\n" if rag_snippets else "\n当前没有可用史料，禁止编造具体史实。\n"
        yield {"event": "trace", "data": {"trace_id": runtime_trace_id}}

        for round_number in range(1, MAX_ROUNDS + 1):
            history = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
            pro_argument = await _invoke_role(
                "pro_debater",
                f"round_{round_number}",
                llm,
                f"辩题：{topic}{shared_evidence}\n你持正方立场，用2-3个可核验史实论证。\n辩论记录：{history}\n请发言（200字以内）：",
                fallback=_fallback_argument(topic, "pro", round_number, sources),
                on_fallback=fallback_roles.add,
                force_fallback=bool(fallback_roles),
                role="pro",
                round=round_number,
            )
            rounds.append({"side": "pro", "argument": pro_argument})
            yield {"event": "round", "data": {"side": "pro", "argument": pro_argument, "round": round_number, "generation_mode": "fallback" if "pro_debater" in fallback_roles else "llm"}}

            history = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
            con_argument = await _invoke_role(
                "con_debater",
                f"round_{round_number}",
                llm,
                f"辩题：{topic}{shared_evidence}\n你持反方立场，用2-3个可核验史实反驳正方。\n辩论记录：{history}\n请发言（200字以内）：",
                fallback=_fallback_argument(topic, "con", round_number, sources),
                on_fallback=fallback_roles.add,
                force_fallback=bool(fallback_roles),
                role="con",
                round=round_number,
            )
            rounds.append({"side": "con", "argument": con_argument})
            yield {"event": "round", "data": {"side": "con", "argument": con_argument, "round": round_number, "generation_mode": "fallback" if "con_debater" in fallback_roles else "llm"}}

        history_text = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
        fact_prompt = (
            f"辩题：{topic}\n辩论记录：\n{history_text}\n"
            + (f"\n参考史料：\n{rag_snippets}\n" if rag_snippets else "")
            + "作为历史事实核查员，指出哪些史实准确、哪些有误或夸大。"
            "有参考史料时必须使用[史料N]标注依据；先总结1-2句，再列出2-4条核查点。"
        )
        fact_result = await _invoke_role(
            "fact_checker",
            "fact_check",
            llm_judge,
            fact_prompt,
            fallback=_fallback_fact_check(sources),
            on_fallback=fallback_roles.add,
            force_fallback=bool(fallback_roles),
            source_count=len(sources),
        )
        known_labels = {str(source.get("citation_label")) for source in sources if source.get("citation_label")}
        claims = []
        for index, line in enumerate((item.strip() for item in fact_result.splitlines()), start=1):
            if not line:
                continue
            cited = sorted(label for label in known_labels if label in line)
            claims.append({
                "claim_id": f"fact_{index}",
                "text": line[:500],
                "source_ids": cited,
                "supported": bool(cited),
            })
        yield {"event": "fact_check", "data": {"result": fact_result, "sources": sources, "claims": claims, "generation_mode": "fallback" if "fact_checker" in fallback_roles else "llm"}}

        verdict = await _invoke_role(
            "judge",
            "verdict",
            llm_judge,
            f"辩题：{topic}\n辩论记录：\n{history_text}\n\n事实核查：\n{fact_result}\n\n"
            "从【论点清晰度】【史实准确性】【逻辑严密性】评判双方；不得把核查为错误、夸大或无来源的事实作为获胜依据。给出优劣、获胜方和理由（300字以内）：",
            fallback=_fallback_verdict(topic, sources),
            on_fallback=fallback_roles.add,
            force_fallback=bool(fallback_roles),
        )
        yield {"event": "verdict", "data": {"verdict": verdict, "generation_mode": "fallback" if "judge" in fallback_roles else "llm"}}

        coach_summary = await _invoke_role(
            "learning_coach",
            "coach_summary",
            llm,
            f"辩题：{topic}\n裁判结论：{verdict[:300]}\n"
            "用初中生能理解的语言总结3个关键历史知识点，并给出1条学习建议：",
            fallback=_fallback_coach_summary(topic, sources),
            on_fallback=fallback_roles.add,
            force_fallback=bool(fallback_roles),
        )
        yield {"event": "coach_summary", "data": {"summary": coach_summary, "generation_mode": "fallback" if "learning_coach" in fallback_roles else "llm"}}

        emit_trace_event(
            agent_name="debate_supervisor",
            step_name="complete",
            event_type="end",
            status="success",
            metadata={"round_count": MAX_ROUNDS, "source_count": len(sources), "worker_count": 5, "degraded": bool(fallback_roles), "fallback_roles": sorted(fallback_roles)},
        )
        yield {
            "event": "done",
            "data": {"trace_id": runtime_trace_id, "round_count": MAX_ROUNDS, "source_count": len(sources), "degraded": bool(fallback_roles), "fallback_roles": sorted(fallback_roles)},
        }


async def run_debate(topic: str, *, trace_id: str | None = None) -> dict:
    """Non-stream consumer of the exact same execution source as SSE."""
    result: dict = {
        "topic": topic,
        "rounds": [],
        "sources": [],
        "fact_check": None,
        "verdict": "",
        "coach_summary": "",
        "completion_status": "failed",
    }
    async for item in stream_debate(topic, trace_id=trace_id):
        event = item["event"]
        data = item["data"]
        if event == "trace":
            result["trace_id"] = data.get("trace_id")
        elif event == "round":
            result["rounds"].append(data)
        elif event == "fact_check":
            result["fact_check"] = data
            result["sources"] = data.get("sources") or []
        elif event == "verdict":
            result["verdict"] = data.get("verdict", "")
        elif event == "coach_summary":
            result["coach_summary"] = data.get("summary", "")
        elif event == "done":
            result["completion_status"] = "completed"
            result["round_count"] = data.get("round_count")
            result["generation_mode"] = "fallback" if data.get("degraded") else "llm"
            result["fallback_roles"] = data.get("fallback_roles") or []
    return result
