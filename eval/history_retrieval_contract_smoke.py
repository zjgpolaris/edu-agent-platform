"""Smoke: RRF provenance and evidence sufficiency remain deterministic."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.documents import Document

from agents import learning_assistant
from agents.answer_verifier import verify_answer_evidence
from agents.learning_assistant_planner import PlanStep
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
    original_corpus_loader = history_search._load_history_corpus_rows
    original_llm_invoke = learning_assistant.llm_fast.invoke

    def offline_invoke(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("offline collection regression")
    try:
        learning_assistant.llm_fast.invoke = offline_invoke
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

        collection_query = history_search.parse_history_query(
            "中国历史以少胜多的战役有哪些",
            topic="中国以少胜多的战役有哪些",
        )
        assert collection_query.entity is None, collection_query
        assert collection_query.retrieval_query == "中国古代以少胜多的战役", collection_query
        assert "collection_query" in collection_query.reason_codes, collection_query
        assert "entity_not_in_catalog" not in collection_query.reason_codes, collection_query
        assert "collection_query" not in history_search.parse_history_query(
            "官渡之战为什么能以少胜多",
            topic="官渡之战",
        ).reason_codes
        assert "collection_query" not in history_search.parse_history_query(
            "世界历史上以少胜多的战役有哪些",
            topic="世界历史上以少胜多的战役有哪些",
        ).reason_codes

        history_search._load_curated_history_events = lambda: (
            {"title": "巨鹿之战", "summary": "项羽率楚军以少胜多大败秦军主力。"},
            {"title": "官渡之战", "summary": "曹操以少胜多大败袁绍。"},
            {"title": "赤壁之战", "summary": "孙刘联军以少胜多大败曹军。"},
            {"title": "淝水之战", "summary": "东晋以少胜多大败前秦。"},
        )
        history_search._load_history_corpus_rows = lambda: (
            {
                "text": "项羽在巨鹿之战中以少胜多歼灭秦军主力。",
                "meta": {"topic": "巨鹿之战", "source": "《中国历史七年级上册》", "lesson": "秦末农民大起义", "page": 57},
            },
            {
                "text": "官渡之战和赤壁之战都是中国古代以少胜多的著名战役。",
                "meta": {"topic": "三国鼎立", "source": "《中国历史七年级上册》", "lesson": "三国鼎立", "page": 89},
            },
            {
                "text": "淝水之战是中国古代又一次以少胜多的著名战役。",
                "meta": {"topic": "淝水之战", "source": "《中国历史七年级上册》", "lesson": "北魏政治和北方民族大交融", "page": 98},
            },
        )
        collection = history_search.search_history_knowledge({
            "query": "中国历史以少胜多的战役有哪些",
            "topic": "中国以少胜多的战役有哪些",
        }).model_dump()
        collection_text = " ".join(source["snippet"] for source in collection["data"]["sources"])
        assert collection["data"]["retrieval_status"] == "sufficient", collection
        assert collection["metadata"]["collection_exact_source_count"] == 3, collection
        assert collection["metadata"]["collection_member_count"] == 4, collection
        assert all(source["source_tier"] == "L1_TEXTBOOK_DIRECT" for source in collection["data"]["sources"]), collection
        assert all(source["answer_bearing"] is True for source in collection["data"]["sources"]), collection
        assert all(title in collection_text for title in ("巨鹿之战", "官渡之战", "赤壁之战", "淝水之战")), collection
        generated = learning_assistant._run_generation_operation(
            "answer_from_sources",
            PlanStep(
                step_id="step_2",
                title="生成史料解释",
                kind="generation",
                operation="answer_from_sources",
                input={"message": "中国历史以少胜多的战役有哪些", "topic": "中国以少胜多的战役有哪些"},
                depends_on=["step_1"],
            ),
            {"step_1": {"payload": collection}},
            req={"message": "中国历史以少胜多的战役有哪些"},
            history=[],
            source_context={},
        )
        assert all(title in generated["response"] for title in ("巨鹿之战", "官渡之战", "赤壁之战", "淝水之战")), generated
        verification = verify_answer_evidence(
            intents=["history_search"],
            execution={
                "tool_results": [collection],
                "generation_results": [{**generated, "operation": "answer_from_sources", "step_id": "step_2"}],
            },
        )
        assert verification.status == "verified" and verification.completion_allowed is True, verification
        assert verification.supported_claim_count == 3, verification

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
        history_search._load_history_corpus_rows = original_corpus_loader
        learning_assistant.llm_fast.invoke = original_llm_invoke
    print("history_retrieval_contract_smoke=PASS")


if __name__ == "__main__":
    main()
