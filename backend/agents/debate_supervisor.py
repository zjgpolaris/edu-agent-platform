"""历史辩论 Agent — Supervisor-Worker 多 Agent 模式。"""
from time import perf_counter
from typing import AsyncIterator, Literal, TypedDict

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


async def _invoke_role(agent_name: str, step_name: str, model, prompt: str, **metadata) -> str:
    started = perf_counter()
    try:
        response = await run_in_threadpool(model.invoke, prompt)
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


async def stream_debate(topic: str, *, trace_id: str | None = None) -> AsyncIterator[dict]:
    """逐轮生成辩论，并为每个角色记录可聚合的 runtime trace。"""
    runtime_trace_id = trace_id or create_trace_id()
    with runtime_trace_context(runtime_trace_id):
        rounds: list[dict] = []
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
                role="pro",
                round=round_number,
            )
            rounds.append({"side": "pro", "argument": pro_argument})
            yield {"event": "round", "data": {"side": "pro", "argument": pro_argument, "round": round_number}}

            history = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
            con_argument = await _invoke_role(
                "con_debater",
                f"round_{round_number}",
                llm,
                f"辩题：{topic}{shared_evidence}\n你持反方立场，用2-3个可核验史实反驳正方。\n辩论记录：{history}\n请发言（200字以内）：",
                role="con",
                round=round_number,
            )
            rounds.append({"side": "con", "argument": con_argument})
            yield {"event": "round", "data": {"side": "con", "argument": con_argument, "round": round_number}}

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
        yield {"event": "fact_check", "data": {"result": fact_result, "sources": sources, "claims": claims}}

        verdict = await _invoke_role(
            "judge",
            "verdict",
            llm_judge,
            f"辩题：{topic}\n辩论记录：\n{history_text}\n\n事实核查：\n{fact_result}\n\n"
            "从【论点清晰度】【史实准确性】【逻辑严密性】评判双方；不得把核查为错误、夸大或无来源的事实作为获胜依据。给出优劣、获胜方和理由（300字以内）：",
        )
        yield {"event": "verdict", "data": {"verdict": verdict}}

        coach_summary = await _invoke_role(
            "learning_coach",
            "coach_summary",
            llm,
            f"辩题：{topic}\n裁判结论：{verdict[:300]}\n"
            "用初中生能理解的语言总结3个关键历史知识点，并给出1条学习建议：",
        )
        yield {"event": "coach_summary", "data": {"summary": coach_summary}}

        emit_trace_event(
            agent_name="debate_supervisor",
            step_name="complete",
            event_type="end",
            status="success",
            metadata={"round_count": MAX_ROUNDS, "source_count": len(sources), "worker_count": 5},
        )
        yield {
            "event": "done",
            "data": {"trace_id": runtime_trace_id, "round_count": MAX_ROUNDS, "source_count": len(sources)},
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
    return result
