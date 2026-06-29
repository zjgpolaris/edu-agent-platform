"""历史辩论 Agent — Supervisor-Worker 多 Agent 模式"""
from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal, AsyncIterator
from llm_config import llm_fast as llm, llm_quality as llm_judge


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


async def stream_debate(topic: str) -> AsyncIterator[dict]:
    """逐轮生成辩论，完成后依次运行 fact_checker、judge、learning_coach。"""
    from fastapi.concurrency import run_in_threadpool
    rounds: list[dict] = []
    round_count = 0

    while round_count < MAX_ROUNDS:
        history = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
        pro_resp = await run_in_threadpool(
            llm.invoke,
            f"辩题：{topic}\n你持正方立场，用2-3个历史史实论证。\n辩论记录：{history}\n请发言（200字以内）："
        )
        rounds.append({"side": "pro", "argument": pro_resp.content})
        yield {"event": "round", "data": {"side": "pro", "argument": pro_resp.content, "round": round_count + 1}}

        history = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
        con_resp = await run_in_threadpool(
            llm.invoke,
            f"辩题：{topic}\n你持反方立场，用2-3个历史史实反驳正方。\n辩论记录：{history}\n请发言（200字以内）："
        )
        rounds.append({"side": "con", "argument": con_resp.content})
        yield {"event": "round", "data": {"side": "con", "argument": con_resp.content, "round": round_count + 1}}

        round_count += 1

    # Fact Checker — 验证辩论中的历史事实
    history_text = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
    fact_resp = await run_in_threadpool(
        llm.invoke,
        f"辩题：{topic}\n辩论内容：\n{history_text}\n\n"
        "作为历史事实核查员，指出辩论中哪些史实准确，哪些有误或夸大。"
        "输出格式：先总结1-2句，再列出2-4条具体核查点（史实名称：是否准确，简要说明）："
    )
    yield {"event": "fact_check", "data": {"result": fact_resp.content, "sources": []}}

    # Judge — 结构化评分
    judge_resp = await run_in_threadpool(
        llm_judge.invoke,
        f"辩题：{topic}\n辩论记录：\n{history_text}\n\n"
        "你是历史辩论裁判。从【论点清晰度】【史实准确性】【逻辑严密性】三个维度评判双方。"
        "给出双方各自优劣分析，并宣布获胜方，说明理由（300字以内）："
    )
    yield {"event": "verdict", "data": {"verdict": judge_resp.content}}

    # Learning Coach — 转化为学习建议
    coach_resp = await run_in_threadpool(
        llm.invoke,
        f"辩题：{topic}\n辩论记录：\n{history_text}\n\n"
        "作为历史学习教练，把这场辩论转化为3条可操作的学习建议："
        "1）本次辩论涉及的核心知识点；2）建议重点复习的内容；3）一个值得深入探究的问题："
    )
    yield {"event": "coach_summary", "data": {"summary": coach_resp.content}}
    yield {"event": "done", "data": {}}

    # Fact Checker
    all_claims = "\n".join(f"第{i+1}轮 {r['side']}: {r['argument'][:200]}" for i, r in enumerate(rounds))
    try:
        from rag.knowledge_base import search_with_scores
        from tracing import truncate_text
        rag_docs = search_with_scores("history", topic, k=4, mode="hybrid")
        rag_snippets = "\n".join(
            f"- {d['document'].page_content[:200]}" for d in rag_docs[:3]
        )
    except Exception:
        rag_snippets = ""
        rag_docs = []

    fact_prompt = (
        f"辩题：{topic}\n辩论摘要：\n{all_claims}\n"
        + (f"\n参考史料：\n{rag_snippets}\n" if rag_snippets else "")
        + "请以「事实核查员」身份，指出辩论中哪些史实陈述有误或需商榷，哪些论据得到史料支持。简明列举，每条不超过50字。"
    )
    fact_resp = await run_in_threadpool(llm_judge.invoke, fact_prompt)
    sources = [
        {"topic": d["document"].metadata.get("topic", ""), "score": round(float(d["score"]), 3)}
        for d in rag_docs[:3]
    ]
    yield {"event": "fact_check", "data": {"result": fact_resp.content, "sources": sources}}

    # verdict
    history_text = "\n".join(f"{r['side']}: {r['argument']}" for r in rounds)
    verdict_resp = await run_in_threadpool(
        llm_judge.invoke,
        f"辩题：{topic}\n辩论记录：{history_text}\n从论点、论据、逻辑三维度评判双方，给出总结性裁决："
    )
    yield {"event": "verdict", "data": {"verdict": verdict_resp.content}}

    # Learning Coach
    coach_prompt = (
        f"辩题：{topic}\n裁判结论：{verdict_resp.content[:300]}\n"
        "请以「学习教练」身份，用初中生能理解的语言，总结这场辩论的3个关键历史知识点，并给出1条学习建议。"
    )
    coach_resp = await run_in_threadpool(llm.invoke, coach_prompt)
    yield {"event": "coach_summary", "data": {"summary": coach_resp.content}}

    yield {"event": "done", "data": {}}
