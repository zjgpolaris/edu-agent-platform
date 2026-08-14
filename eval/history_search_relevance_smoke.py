"""Smoke: explicit history topics reject unrelated retrieval results."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.documents import Document

from agents.learning_assistant import _fallback_history_answer
from rag.knowledge_base import keyword_score
from tools import history_search


def _scored(topic: str, text: str, score: float) -> dict:
    return {
        "document": Document(page_content=text, metadata={
            "topic": topic,
            "source": "《中国历史七年级下册（人教版）》正文",
            "lesson": "第12课 宋代的词",
            "page": 62,
        }),
        "rank": 1,
        "score": score,
        "final_score": score,
        "retrieval_score": score,
        "keyword_score": score,
        "source_mode": "keyword",
    }


def main() -> None:
    relevant = _scored("苏轼词的特点", "北宋文学家苏轼改进了词的创作，词风豪迈而飘逸。", 12.0)
    broad_but_relevant = _scored(
        "宋元时期的都市和文化",
        "女词人李清照的词风委婉细腻。南宋辛弃疾继承了苏轼以来的豪放词风和报国情怀，进一步提高了词的社会功能。元曲包括散曲、杂剧和南戏等。",
        10.0,
    )
    unrelated = _scored("开元盛世", "唐玄宗前期政治稳定、经济繁荣。", 8.0)
    original_search = history_search.search_with_scores_and_diagnostics
    history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: ([relevant, broad_but_relevant, unrelated], {"fusion": "rrf", "reranker": {"status": "skipped"}})
    try:
        result = history_search.search_history_knowledge({"query": "苏轼做了什么", "topic": "苏轼", "k": 4})
    finally:
        history_search.search_with_scores_and_diagnostics = original_search

    payload = result.model_dump()
    sources = payload["data"]["sources"]
    assert len(sources) == 2, payload
    assert sources[0]["topic"] == "苏轼词的特点", payload
    assert "辛弃疾继承了苏轼" in sources[1]["snippet"], payload
    assert "李清照" not in sources[1]["snippet"] and "元曲" not in sources[1]["snippet"], payload
    assert "[truncated" not in sources[1]["snippet"], payload
    assert payload["metadata"]["rejected_irrelevant_count"] == 1, payload

    history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: ([
        _scored("赤壁之战经过", "赤壁之战中孙刘联军使用火攻击败曹军。", 14.0),
        _scored("赤壁之战", "赤壁之战产生关键影响，为三国鼎立局面的形成奠定了基础。", 12.0),
        unrelated,
    ], {"fusion": "rrf", "reranker": {"status": "skipped"}})
    try:
        battle_result = history_search.search_history_knowledge({"query": "赤壁之战的影响是什么", "topic": "赤壁之战的影响", "k": 4}).model_dump()
    finally:
        history_search.search_with_scores_and_diagnostics = original_search
    assert battle_result["metadata"]["topic"] == "赤壁之战", battle_result
    assert [source["topic"] for source in battle_result["data"]["sources"]][:2] == ["赤壁之战", "赤壁之战经过"], battle_result
    assert "影响" in battle_result["data"]["sources"][0]["snippet"], battle_result
    battle_answer = _fallback_history_answer(battle_result["data"]["sources"], "赤壁之战", "赤壁之战的影响是什么")
    assert "三国鼎立" in battle_answer and "使用火攻" not in battle_answer, battle_answer

    guandu_direct = _scored(
        "官渡之战",
        "东汉末年，曹操挟天子以令诸侯，招揽各种人才，在经济上采用屯田的措施。曹操与袁绍在官渡展开决战，曹操采取声东击西的战术，迅速歼灭袁军主力，为以后统一北方打下基础。",
        16.0,
    )
    guandu_duplicate = _scored(
        "三国鼎立",
        "东汉末年，曹操挟天子以令诸侯，招揽各种人才，在经济上采用屯田的措施。曹操与袁绍在官渡展开决战，曹操采取声东击西的战术，迅速歼灭袁军主力，为以后统一北方打下基础。",
        14.0,
    )
    guandu_process = _scored("官渡之战经过", "官渡之战中，曹操采取声东击西的战术击败袁军。", 12.0)
    history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: ([
        guandu_direct,
        guandu_duplicate,
        guandu_process,
    ], {"fusion": "rrf", "reranker": {"status": "skipped"}})
    try:
        guandu_result = history_search.search_history_knowledge({"query": "分析下官渡之战的意义", "k": 4}).model_dump()
    finally:
        history_search.search_with_scores_and_diagnostics = original_search
    guandu_sources = guandu_result["data"]["sources"]
    assert guandu_result["data"]["retrieval_status"] == "sufficient", guandu_result
    assert guandu_result["data"]["evidence_sufficiency"]["answer_bearing_source_count"] == 1, guandu_result
    assert "统一北方打下基础" in guandu_sources[0]["snippet"], guandu_result
    assert "挟天子以令诸侯" not in guandu_sources[0]["snippet"], guandu_result
    assert "屯田" not in guandu_sources[0]["snippet"] and "声东击西" not in guandu_sources[0]["snippet"], guandu_result
    guandu_answer = _fallback_history_answer(guandu_sources, "官渡之战", "分析下官渡之战的意义", aspect="significance")
    assert "统一北方打下基础" in guandu_answer, guandu_answer
    assert "挟天子以令诸侯" not in guandu_answer and "声东击西" not in guandu_answer, guandu_answer

    missing_metadata = Document(page_content="与问题无关的普通材料", metadata={})
    assert keyword_score("苏轼", missing_metadata, {"topic": ["苏轼"], "keywords": ["苏轼"]}) == 0

    answer = _fallback_history_answer(sources, "苏轼", "苏轼做了什么")
    assert "改进了词的创作" in answer, answer
    assert "第12课 宋代的词" in answer and "第62页" in answer, answer
    assert "开元盛世" not in answer, answer
    print("history_search_relevance_smoke=PASS")


if __name__ == "__main__":
    main()
