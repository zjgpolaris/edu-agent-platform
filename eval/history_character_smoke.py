import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))


CASES = [
    ("商鞅", "你为什么要变法？", "商鞅"),
    ("秦始皇", "统一文字为什么重要？", "秦"),
    ("林则徐", "虎门销烟有什么历史意义？", "鸦片"),
]


async def run_case(character: str, message: str, expected_source_keyword: str) -> None:
    from agents.history_character import build_character_graph
    from rag.knowledge_base import get_retriever

    retriever = get_retriever("history")
    graph = build_character_graph(retriever)
    state = {
        "character": character,
        "messages": [{"role": "user", "content": message}],
        "retrieved_facts": [],
        "retrieved_sources": [],
        "response_draft": "",
        "verified": False,
    }
    result = await graph.ainvoke(state)
    response = result["response_draft"]
    sources = result.get("retrieved_sources", [])

    assert result.get("verified") is True
    assert "【回答】" in response
    assert "【史料依据】" in response
    assert "【学习提示】" in response
    assert sources
    assert any(
        expected_source_keyword in source.get("content", "")
        or expected_source_keyword in source.get("topic", "")
        for source in sources
    )

    print(f"OK {character}: {message}")
    print(response[:160].replace("\n", " "))
    print("sources:", [source.get("topic", "") for source in sources[:3]])


async def main() -> None:
    has_key = any(os.getenv(k) for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "BAILIAN_API_KEY", "DASHSCOPE_API_KEY"))
    if not has_key:
        print("SKIP history_character_smoke: no LLM API key set")
        return
    try:
        from rag.knowledge_base import get_embed_model, search_with_scores
        get_embed_model()
        probe = search_with_scores("history", "鸦片战争", k=1, mode="hybrid")
        if not probe:
            print("SKIP history_character_smoke: RAG sources unavailable")
            return
    except Exception as e:
        print(f"SKIP history_character_smoke: embedding/RAG unavailable ({e})")
        return
    for case in CASES:
        await run_case(*case)


if __name__ == "__main__":
    asyncio.run(main())
