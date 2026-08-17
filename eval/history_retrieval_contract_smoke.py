"""Smoke: RRF provenance and evidence sufficiency remain deterministic."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.documents import Document

from rag.knowledge_base import reciprocal_rank_fusion
from tools import history_search


def _doc(topic: str, text: str, *, tier: str = "L1_TEXTBOOK_DIRECT", aspect: str = "fact") -> Document:
    return Document(page_content=text, metadata={
        "topic": topic,
        "entity": "赤壁之战" if "赤壁" in topic else topic,
        "source": "《中国历史七年级上册》",
        "source_tier": tier,
        "document_type": "textbook_fact" if tier != "L3_CURATED_REFERENCE" else "curated_event_fact",
        "aspect": aspect,
        "reviewed": tier == "L1_TEXTBOOK_DIRECT",
    })


def main() -> None:
    exact = _doc("赤壁之战", "赤壁之战奠定了三国鼎立局面。", aspect="significance")
    broad = _doc("三国鼎立", "东汉末年形成多个割据势力。")
    semantic = _doc("官渡之战", "官渡之战是以少胜多的战役。")
    fused = reciprocal_rank_fusion({
        "entity": [exact],
        "bm25": [broad, exact],
        "vector": [semantic, exact],
    }, weights={"entity": 1.4, "bm25": 1.0, "vector": 1.0})
    assert fused[0]["document"] is exact, fused
    assert fused[0]["channel_ranks"] == {"entity": 1, "bm25": 2, "vector": 2}, fused[0]

    original = history_search.search_with_scores_and_diagnostics
    original_curated_loader = history_search._load_curated_history_events
    try:
        history_search._load_curated_history_events = lambda: ()
        history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: ([
            {
                "document": exact,
                "rank": 1,
                "score": 0.05,
                "final_score": 0.05,
                "retrieval_score": 0.05,
                "rrf_score": 0.05,
                "channel_ranks": {"entity": 1},
                "source_mode": "entity",
            },
        ], {"fusion": "rrf", "reranker": {"status": "skipped"}})
        sufficient = history_search.search_history_knowledge({
            "query": "赤壁之战有什么意义",
            "topic": "赤壁之战",
        }).model_dump()
        assert sufficient["data"]["retrieval_status"] == "sufficient", sufficient

        curated = _doc(
            "赤壁之战",
            "赤壁之战奠定了三国鼎立局面。",
            tier="L3_CURATED_REFERENCE",
            aspect="significance",
        )
        history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: ([
            {
                "document": curated,
                "rank": 1,
                "score": 0.05,
                "final_score": 0.05,
                "retrieval_score": 0.05,
                "rrf_score": 0.05,
                "channel_ranks": {"entity": 1},
                "source_mode": "entity",
            },
        ], {"fusion": "rrf", "reranker": {"status": "skipped"}})
        partial = history_search.search_history_knowledge({
            "query": "赤壁之战有什么意义",
            "topic": "赤壁之战",
        }).model_dump()
        assert partial["data"]["retrieval_status"] == "partial", partial
        assert "retrieval_curated_only" in partial["data"]["evidence_sufficiency"]["reason_codes"], partial

        history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: ([], {"fusion": "rrf", "reranker": {"status": "skipped"}})
        missing = history_search.search_history_knowledge({
            "query": "赤壁之战有什么意义",
            "topic": "赤壁之战",
        }).model_dump()
        assert missing["ok"] is True and missing["data"]["retrieval_status"] == "none", missing

        history_search._load_curated_history_events = lambda: ({
            "title": "长平之战",
            "summary": "秦赵之间规模最大的野战，赵军大败，白起坑杀降卒四十万，赵国元气大伤。",
            "location_name": "长平（今山西高平）",
            "dynasty": "战国",
            "character": "白起",
        },)
        curated_fallback = history_search.search_history_knowledge({
            "query": "长平之战的结果是什么",
            "topic": "长平之战",
        }).model_dump()
        assert curated_fallback["data"]["retrieval_status"] == "partial", curated_fallback
        assert curated_fallback["data"]["sources"][0]["source_tier"] == "L3_CURATED_REFERENCE", curated_fallback
        assert curated_fallback["data"]["sources"][0]["answer_bearing"] is True, curated_fallback
        assert curated_fallback["metadata"]["curated_fallback_added"] is True, curated_fallback
        assert "retrieval_curated_only" in curated_fallback["data"]["evidence_sufficiency"]["reason_codes"], curated_fallback

        unsupported_curated = history_search.search_history_knowledge({
            "query": "长平之战的主要原因是什么",
            "topic": "长平之战",
        }).model_dump()
        assert unsupported_curated["data"]["retrieval_status"] == "partial", unsupported_curated
        assert unsupported_curated["data"]["sources"][0]["answer_bearing"] is False, unsupported_curated
        assert "retrieval_aspect_not_supported" in unsupported_curated["data"]["evidence_sufficiency"]["reason_codes"], unsupported_curated

        unverifiable_detail = history_search.search_history_knowledge({
            "query": "请根据教材说明长平之战的逐日行军路线",
            "topic": "长平之战",
        }).model_dump()
        assert unverifiable_detail["data"]["retrieval_status"] == "none", unverifiable_detail
        assert unverifiable_detail["metadata"]["curated_fallback_added"] is False, unverifiable_detail
    finally:
        history_search.search_with_scores_and_diagnostics = original
        history_search._load_curated_history_events = original_curated_loader
    print("history_retrieval_contract_smoke=PASS")


if __name__ == "__main__":
    main()
