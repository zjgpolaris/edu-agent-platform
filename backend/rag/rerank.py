"""RAG Rerank module using cross-encoder for result reordering."""
from __future__ import annotations

import os

_reranker = None


def get_reranker():
    """Get or initialize the reranker model."""
    global _reranker
    if _reranker is None:
        model_path = os.getenv("RERANK_MODEL_PATH", "")
        if model_path:
            try:
                from langchain_community.cross_encoders import HuggingFaceCrossEncoder
                _reranker = HuggingFaceCrossEncoder(model_name=model_path)
            except ImportError:
                pass
    return _reranker


def _with_rank(scored_docs: list, top_k: int) -> list:
    ranked = []
    for index, item in enumerate(scored_docs[:top_k], start=1):
        final_score = float(item.get("final_score", item.get("score", 0)))
        ranked.append({**item, "final_score": final_score, "score": final_score, "rank": index})
    return ranked


def rerank(query: str, scored_docs: list, top_k: int = 5) -> list:
    """
    Rerank ScoredDocument items using cross-encoder while preserving retrieval provenance.
    """
    reranker = get_reranker()
    if not reranker:
        ordered = sorted(scored_docs, key=lambda item: float(item.get("final_score", item.get("score", 0))), reverse=True)
        return _with_rank(ordered, top_k)

    pairs = [(query, item["document"].page_content) for item in scored_docs]
    scores = reranker.score(pairs)
    reranked = []
    for cross_score, item in zip(scores, scored_docs):
        retrieval_score = float(item.get("retrieval_score", item.get("final_score", item.get("score", 0))))
        rerank_score = float(cross_score)
        final_score = 0.7 * rerank_score + 0.3 * retrieval_score
        reranked.append({**item, "rerank_score": rerank_score, "final_score": final_score, "score": final_score})
    ordered = sorted(reranked, key=lambda item: float(item.get("final_score", item.get("score", 0))), reverse=True)
    return _with_rank(ordered, top_k)
