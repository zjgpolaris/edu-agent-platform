"""RAG Rerank module using cross-encoder for result reordering."""
from __future__ import annotations

import os
from time import perf_counter
from typing import Any

_reranker = None
_reranker_error: str | None = None


def get_reranker():
    """Get or initialize the reranker model."""
    global _reranker, _reranker_error
    if _reranker is None:
        model_path = os.getenv("RERANK_MODEL_PATH", "")
        if model_path:
            try:
                from langchain_community.cross_encoders import HuggingFaceCrossEncoder
                _reranker = HuggingFaceCrossEncoder(model_name=model_path)
                _reranker_error = None
            except Exception as exc:
                _reranker_error = str(exc)[:240]
    return _reranker


def _with_rank(scored_docs: list, top_k: int) -> list:
    ranked = []
    for index, item in enumerate(scored_docs[:top_k], start=1):
        final_score = float(item.get("final_score", item.get("score", 0)))
        ranked.append({**item, "final_score": final_score, "score": final_score, "rank": index})
    return ranked


def rerank_with_diagnostics(
    query: str,
    scored_docs: list,
    top_k: int = 5,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[list, dict[str, Any]]:
    started = perf_counter()
    model_path = os.getenv("RERANK_MODEL_PATH", "").strip()
    reranker = get_reranker()
    if not reranker:
        ordered = sorted(scored_docs, key=lambda item: float(item.get("final_score", item.get("score", 0))), reverse=True)
        return _with_rank(ordered, top_k), {
            "status": "failed" if model_path and _reranker_error else "skipped",
            "model": model_path or None,
            "candidate_count": len(scored_docs),
            "output_count": min(len(scored_docs), top_k),
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "reason_code": "model_load_failed" if model_path and _reranker_error else "model_not_configured",
            "error": _reranker_error,
        }

    context = context or {}
    contextual_query = " | ".join(
        part
        for part in (
            query,
            f"实体：{context.get('entity')}" if context.get("entity") else "",
            f"问答维度：{context.get('aspect')}" if context.get("aspect") else "",
        )
        if part
    )
    try:
        pairs = [(contextual_query, item["document"].page_content) for item in scored_docs]
        scores = reranker.score(pairs)
        reranked = []
        for cross_score, item in zip(scores, scored_docs):
            retrieval_score = float(item.get("retrieval_score", item.get("final_score", item.get("score", 0))))
            rerank_score = float(cross_score)
            final_score = 0.7 * rerank_score + 0.3 * retrieval_score
            reranked.append({**item, "rerank_score": rerank_score, "final_score": final_score, "score": final_score})
        ordered = sorted(reranked, key=lambda item: float(item.get("final_score", item.get("score", 0))), reverse=True)
        results = _with_rank(ordered, top_k)
        return results, {
            "status": "enabled",
            "model": model_path or type(reranker).__name__,
            "candidate_count": len(scored_docs),
            "output_count": len(results),
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "reason_code": None,
        }
    except Exception as exc:
        ordered = sorted(scored_docs, key=lambda item: float(item.get("final_score", item.get("score", 0))), reverse=True)
        return _with_rank(ordered, top_k), {
            "status": "failed",
            "model": model_path or type(reranker).__name__,
            "candidate_count": len(scored_docs),
            "output_count": min(len(scored_docs), top_k),
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "reason_code": "rerank_execution_failed",
            "error": str(exc)[:240],
        }


def rerank(query: str, scored_docs: list, top_k: int = 5) -> list:
    """Backward-compatible rerank API."""
    results, _ = rerank_with_diagnostics(query, scored_docs, top_k=top_k)
    return results
