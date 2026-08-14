from __future__ import annotations

import re
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


def _trim_excerpt(value: str, max_chars: int = 280) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip(" ，。！？；,") + "..."


_QUESTION_ASPECTS = ("原因", "背景", "经过", "结果", "影响", "意义", "作用", "特点", "贡献", "目的", "内容", "措施", "导火索")


def _query_aspects(query: str) -> list[str]:
    compact = _compact(query)
    return [aspect for aspect in _QUESTION_ASPECTS if aspect in compact]


def _focused_snippet(content: str, topic: str | None, aspects: list[str] | None = None) -> str:
    cleaned = re.sub(r"\s+", " ", str(content or "")).strip()
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
    if not topic:
        return _trim_excerpt(cleaned)
    needle = _compact(topic)
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[。！？；])", cleaned) if sentence.strip()]
    focused = [sentence for sentence in sentences if needle in _compact(sentence)]
    if focused:
        focused.sort(key=lambda sentence: any(aspect in _compact(sentence) for aspect in (aspects or [])), reverse=True)
        if aspects:
            for sentence in focused:
                clauses = [clause for clause in re.split(r"(?<=[，,；;])", sentence) if clause.strip()]
                for index, clause in enumerate(clauses):
                    if any(aspect in _compact(clause) for aspect in aspects):
                        return _trim_excerpt("".join(clauses[index : index + 2]).strip())
        return _trim_excerpt("".join(focused[:2]))
    return _trim_excerpt(sentences[0] if sentences else cleaned)


def _source_from_scored_doc(item: dict[str, Any], focus_topic: str | None = None, query: str = "") -> dict[str, Any]:
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
        "snippet": _focused_snippet(doc.page_content, focus_topic, _query_aspects(query)),
    }


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _topic_anchor(topic: str | None) -> str | None:
    if not topic:
        return None
    raw_topic = topic.strip(" ，。！？,.!?")
    anchor = re.sub(
        r"(?:(?:失败|成功)的?)?(?:的)?(?:主要)?(?:原因|背景|经过|结果|影响|意义|作用|特点|贡献|目的|内容|措施|导火索)(?:是什么|有哪些|如何|怎么样|有多大)?$",
        "",
        raw_topic,
    ).strip(" ，。！？,.!?的")
    return anchor or raw_topic


def _aspect_match_count(query: str, item: dict[str, Any]) -> int:
    content = _compact(item["document"].page_content)
    return sum(1 for aspect in _query_aspects(query) if aspect in content)


def _topic_matches_scored_doc(topic: str, item: dict[str, Any]) -> bool:
    needle = _compact(topic)
    if not needle:
        return True
    doc = item["document"]
    metadata = doc.metadata or {}
    metadata_text = " ".join(
        " ".join(str(part) for part in value) if isinstance(value, list) else str(value or "")
        for key in ("topic", "lesson", "event", "entities", "keywords", "tags")
        for value in [metadata.get(key)]
    )
    return needle in _compact(f"{metadata_text} {doc.page_content}")


def search_history_knowledge(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, SearchHistoryKnowledgeInput) else SearchHistoryKnowledgeInput.model_validate(payload)
    topic = _topic_anchor(req.topic)
    hints: MetadataHints = {"keywords": [req.query]}
    if topic:
        hints["topic"] = [topic]
    if req.grade:
        hints["grade"] = req.grade
    candidate_k = max(12, req.k * 3) if topic else req.k
    candidates = search_with_scores("history", req.query, k=candidate_k, mode="hybrid", metadata_hints=hints, fetch_k=max(30, candidate_k * 3))
    matching_candidates = [item for item in candidates if not topic or _topic_matches_scored_doc(topic, item)]
    if _query_aspects(req.query):
        matching_candidates.sort(
            key=lambda item: (_aspect_match_count(req.query, item), float(item.get("final_score", item.get("score", 0)))),
            reverse=True,
        )
    scored_docs = matching_candidates[:req.k]
    sources = [_source_from_scored_doc(item, topic, req.query) for item in scored_docs]
    return ToolResult(
        tool_name="search_history_knowledge",
        ok=True,
        data={"sources": sources},
        metadata={
            "source_count": len(sources),
            "candidate_count": len(candidates),
            "rejected_irrelevant_count": len(candidates) - len(matching_candidates),
            "query": truncate_text(req.query, max_chars=160),
            "topic": topic,
        },
    )
