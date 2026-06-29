from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rag.knowledge_base import MetadataHints, search_with_scores
from tracing import truncate_text
from tools.base import ToolResult


class SearchHistoryKnowledgeInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    grade: str | None = None
    topic: str | None = None
    k: int = Field(default=4, ge=1, le=8)


def _rounded(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _source_from_scored_doc(item: dict[str, Any]) -> dict[str, Any]:
    doc = item["document"]
    metadata = doc.metadata or {}
    final_score = float(item.get("final_score", item.get("score", 0)))
    return {
        "rank": item.get("rank"),
        "topic": metadata.get("topic", ""),
        "source": metadata.get("source", ""),
        "grade": metadata.get("grade", ""),
        "unit": metadata.get("unit", ""),
        "lesson": metadata.get("lesson", ""),
        "page": metadata.get("page", ""),
        "type": metadata.get("type", ""),
        "score": round(final_score, 3),
        "final_score": round(final_score, 3),
        "retrieval_score": _rounded(item.get("retrieval_score")),
        "keyword_score": _rounded(item.get("keyword_score")),
        "vector_rank": item.get("vector_rank"),
        "vector_rank_score": _rounded(item.get("vector_rank_score")),
        "rerank_score": _rounded(item.get("rerank_score")),
        "source_mode": item.get("source_mode", ""),
        "snippet": truncate_text(doc.page_content, max_chars=360),
    }


def search_history_knowledge(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, SearchHistoryKnowledgeInput) else SearchHistoryKnowledgeInput.model_validate(payload)
    hints: MetadataHints = {
        "topic": [part for part in [req.topic, req.query] if part],
        "keywords": [req.query],
    }
    if req.grade:
        hints["grade"] = req.grade
    scored_docs = search_with_scores("history", req.query, k=req.k, mode="hybrid", metadata_hints=hints, fetch_k=max(30, req.k * 6))
    sources = [_source_from_scored_doc(item) for item in scored_docs]
    return ToolResult(
        tool_name="search_history_knowledge",
        ok=True,
        data={"sources": sources},
        metadata={"source_count": len(sources), "query": truncate_text(req.query, max_chars=160)},
    )
