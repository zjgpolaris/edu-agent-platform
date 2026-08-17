from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from rag.history_documents import history_source_fields, stable_history_source_id
from rag.history_query import HistoryQuery, aspect_query_label, detect_history_aspect, parse_history_query, topic_anchor
from rag.knowledge_base import MetadataHints, search_with_scores_and_diagnostics
from tracing import truncate_text
from tools.base import ToolResult


ROOT = Path(__file__).resolve().parents[2]
GEO_EVENTS_PATH = ROOT / "knowledge_base" / "history" / "geo_events.json"


@lru_cache(maxsize=2)
def _load_curated_history_events_cached(path: str, mtime_ns: int) -> tuple[dict[str, Any], ...]:
    del mtime_ns
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()
    return tuple(row for row in payload if isinstance(row, dict)) if isinstance(payload, list) else ()


def _load_curated_history_events(path: Path = GEO_EVENTS_PATH) -> tuple[dict[str, Any], ...]:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return ()
    return _load_curated_history_events_cached(str(path), mtime_ns)


class SearchHistoryKnowledgeInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    history_query: HistoryQuery | None = None
    grade: str | None = None
    lesson: str | None = None
    topic: str | None = None
    k: int = Field(default=6, ge=1, le=8)


class EvidenceSufficiency(BaseModel):
    status: Literal["sufficient", "partial", "none"]
    source_count: int = 0
    answer_bearing_source_count: int = 0
    entity_match: bool = False
    aspect_match: bool = False
    reason_codes: list[str] = Field(default_factory=list)


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


def _split_clauses(sentence: str) -> list[str]:
    return [clause.strip() for clause in re.findall(r"[^，,；;。！？]+[，,；;。！？]?", sentence) if clause.strip()]


def _aspect_evidence_excerpt(
    content: str,
    topic: str | None,
    target_aspect: str,
    *,
    metadata_topic: str = "",
    source_aspect: str = "",
) -> str | None:
    if target_aspect in {"", "unknown", "fact", "definition", "contribution"}:
        return None
    cleaned = re.sub(r"\s+", " ", str(content or "")).strip()
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
    if not cleaned:
        return None
    terms = tuple(_compact(term) for term in _ASPECT_COMPATIBLE_TERMS.get(target_aspect, (aspect_query_label(target_aspect),)))
    topic_key = _compact(topic)
    metadata_has_topic = bool(topic_key and topic_key in _compact(metadata_topic))
    candidates: list[tuple[int, str]] = []
    for sentence in [part.strip() for part in re.split(r"(?<=[。！？；])", cleaned) if part.strip()]:
        sentence_key = _compact(sentence)
        sentence_has_topic = not topic_key or topic_key in sentence_key
        if not sentence_has_topic and not metadata_has_topic:
            continue
        clauses = _split_clauses(sentence)
        matching_indexes = [
            index
            for index, clause in enumerate(clauses)
            if any(term and term in _compact(clause) for term in terms)
        ]
        if not matching_indexes:
            if source_aspect == target_aspect and sentence_has_topic:
                candidates.append((4, _trim_excerpt(sentence)))
            continue
        first = matching_indexes[0]
        last = matching_indexes[-1]
        selected = clauses[first : last + 1]
        if first > 0:
            previous = clauses[first - 1]
            previous_key = _compact(previous)
            result_context = ("胜", "败", "歼灭", "消灭", "结束", "灭亡", "统一", "主力", "元气大伤")
            if len(previous_key) <= 36 and any(marker in previous_key for marker in result_context):
                selected.insert(0, previous)
        excerpt = "".join(selected).strip(" ，,；;")
        if excerpt and excerpt[-1] not in "。！？":
            excerpt += "。"
        score = 8 + len(matching_indexes) * 2 + (4 if sentence_has_topic else 0) + (2 if source_aspect == target_aspect else 0)
        candidates.append((score, _trim_excerpt(excerpt)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]


def _source_from_scored_doc(
    item: dict[str, Any],
    focus_topic: str | None = None,
    query: str = "",
    *,
    target_aspect: str = "fact",
) -> dict[str, Any]:
    doc = item["document"]
    metadata = doc.metadata or {}
    final_score = float(item.get("final_score", item.get("score", 0)))
    history_fields = history_source_fields(doc.page_content, metadata)
    focused_snippet = _focused_snippet(doc.page_content, focus_topic, _query_aspects(query))
    aspect_excerpt = _aspect_evidence_excerpt(
        doc.page_content,
        focus_topic,
        target_aspect,
        metadata_topic=" ".join(str(metadata.get(key) or "") for key in ("topic", "entity", "event")),
        source_aspect=str(history_fields.get("aspect") or ""),
    )
    source = {
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
        "rrf_score": _rounded(item.get("rrf_score")),
        "channel_ranks": item.get("channel_ranks") or {},
        "source_mode": item.get("source_mode", ""),
        "snippet": aspect_excerpt or focused_snippet,
        **history_fields,
    }
    source["entity_match"] = bool(focus_topic and _topic_matches_scored_doc(focus_topic, item))
    source["aspect_match"] = bool(aspect_excerpt) if target_aspect not in {"", "unknown", "fact", "definition", "contribution"} else _source_matches_aspect(source, target_aspect, focus_topic)
    source["answer_bearing"] = bool(source["entity_match"] and source["aspect_match"])
    return source


def _curated_event_source(topic: str, query: str, target_aspect: str) -> dict[str, Any] | None:
    event = next(
        (row for row in _load_curated_history_events() if _compact(row.get("title")) == _compact(topic)),
        None,
    )
    if not event:
        return None
    title = str(event.get("title") or "").strip()
    summary = str(event.get("summary") or "").strip()
    if not title or not summary:
        return None
    source_title = "历史事件补充资料库"
    source_id = stable_history_source_id(
        source_title=f"{source_title}:{title}",
        grade=None,
        lesson=None,
        page=None,
        document_type="curated_event_fact",
        claim=summary,
    )
    content = f"{title}：{summary}"
    document = Document(page_content=content, metadata={
        "source_id": source_id,
        "document_type": "curated_event_fact",
        "source_tier": "L3_CURATED_REFERENCE",
        "source_title": source_title,
        "source": source_title,
        "topic": title,
        "event": title,
        "entity": title,
        "entities": [title, event.get("character")] if event.get("character") else [title],
        "aspect": detect_history_aspect(summary),
        "claim": summary,
        "context": event.get("location_name"),
        "period": event.get("dynasty"),
        "corpus_version": "history-v1.31",
        "reviewed": bool(event.get("reviewed", False)),
        "meta_source": "geo_events",
    })
    return _source_from_scored_doc(
        {
            "document": document,
            "rank": 1,
            "score": 0.0,
            "final_score": 0.0,
            "retrieval_score": 0.0,
            "keyword_score": 0.0,
            "source_mode": "curated_fallback",
        },
        topic,
        query,
        target_aspect=target_aspect,
    )


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


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


_ASPECT_COMPATIBLE_TERMS: dict[str, tuple[str, ...]] = {
    "definition": ("是", "指", "概念"),
    "background": ("背景", "条件", "局面"),
    "cause": ("原因", "由于", "因为", "为了", "导火索"),
    "process": ("经过", "过程", "开始", "随后", "进而"),
    "result": ("结果", "失败", "胜利", "大败", "战败", "获胜", "灭亡", "建立", "结束"),
    "impact": ("影响", "作用", "促进", "推动", "导致", "改变", "奠定", "元气大伤", "削弱"),
    "significance": ("意义", "重要", "奠定", "促进", "推动", "标志", "基础", "元气大伤"),
    "measure": ("措施", "内容", "实行", "推行", "颁布", "设置"),
    "contribution": ("贡献", "创作", "改进", "提出", "发明", "建立", "成就"),
    "feature": ("特点", "特征", "风格", "表现"),
    "comparison": ("比较", "相同", "不同", "共同"),
    "evaluation": ("评价", "地位", "局限", "进步", "决定性", "规模最大"),
}


def _source_matches_aspect(source: dict[str, Any], target_aspect: str, target_entity: str | None = None) -> bool:
    if target_aspect in {"", "unknown", "fact", "definition"}:
        return True
    source_aspect = str(source.get("aspect") or "")
    if source_aspect == target_aspect:
        return True
    raw_text = f"{source.get('topic', '')}。{source.get('snippet', '')}"
    text = _compact(raw_text)
    if target_aspect == "contribution" and target_entity:
        entity = _compact(target_entity)
        entity_clauses = [
            _compact(clause)
            for clause in re.split(r"[。！？；，,]", raw_text)
            if target_entity in clause
        ]
        for clause in entity_clauses:
            if any(marker in clause for marker in (f"继承了{entity}", f"{entity}以来", f"学习{entity}", f"受到{entity}")):
                continue
            entity_at = clause.find(entity)
            for term in _ASPECT_COMPATIBLE_TERMS["contribution"]:
                term_at = clause.find(_compact(term))
                if entity_at >= 0 and term_at > entity_at and term_at - entity_at <= 24:
                    return True
        return False
    return any(_compact(term) in text for term in _ASPECT_COMPATIBLE_TERMS.get(target_aspect, (aspect_query_label(target_aspect),)))


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        evidence_key = _compact(source.get("snippet") or source.get("claim") or "")
        key = evidence_key or str(source.get("source_id") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append({**source, "rank": len(deduped) + 1})
    return deduped


def _feature_enabled(name: str, *, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sufficiency(sources: list[dict[str, Any]], query: HistoryQuery) -> EvidenceSufficiency:
    entity_sources = [source for source in sources if source.get("entity_match")]
    answer_bearing = [source for source in sources if source.get("answer_bearing")]
    reason_codes: list[str] = []
    if not sources:
        reason_codes.append("retrieval_no_sources")
    if sources and not entity_sources:
        reason_codes.append("retrieval_entity_mismatch")
    if entity_sources and not answer_bearing:
        reason_codes.append("retrieval_aspect_not_supported")
    direct_answer_bearing = [
        source
        for source in answer_bearing
        if source.get("source_tier") == "L1_TEXTBOOK_DIRECT"
        or (source.get("source_tier") == "L2_TEXTBOOK_DERIVED" and source.get("reviewed") is True)
    ]
    if answer_bearing and not direct_answer_bearing:
        reason_codes.append(
            "retrieval_curated_only"
            if all(source.get("source_tier") == "L3_CURATED_REFERENCE" for source in answer_bearing)
            else "retrieval_unreviewed_derived_only"
        )
    if direct_answer_bearing:
        status: Literal["sufficient", "partial", "none"] = "sufficient"
    elif entity_sources or answer_bearing:
        status = "partial"
    else:
        status = "none"
    return EvidenceSufficiency(
        status=status,
        source_count=len(sources),
        answer_bearing_source_count=len(answer_bearing),
        entity_match=bool(entity_sources),
        aspect_match=bool(answer_bearing),
        reason_codes=reason_codes,
    )


def search_history_knowledge(payload: BaseModel) -> ToolResult:
    req = payload if isinstance(payload, SearchHistoryKnowledgeInput) else SearchHistoryKnowledgeInput.model_validate(payload)
    history_query = req.history_query if _feature_enabled("EDU_AGENT_HISTORY_QUERY_V2_ENABLED") else None
    if history_query is None:
        history_query = parse_history_query(req.query, topic=req.topic, grade=req.grade, lesson=req.lesson)
    topic = history_query.entity or topic_anchor(req.topic)
    hints: MetadataHints = {"keywords": [history_query.retrieval_query]}
    if topic:
        hints["topic"] = [topic]
    if req.grade:
        hints["grade"] = req.grade
    candidate_k = max(20, req.k * 3)
    candidates, diagnostics = search_with_scores_and_diagnostics(
        "history",
        history_query.retrieval_query,
        k=candidate_k,
        mode="hybrid",
        metadata_hints=hints,
        fetch_k=max(30, candidate_k * 3),
        fusion="rrf" if _feature_enabled("EDU_AGENT_HISTORY_RRF_ENABLED") else "weighted",
        entity=topic,
        aspect=history_query.aspect,
        rerank_enabled=_feature_enabled("EDU_AGENT_HISTORY_RERANK_ENABLED"),
    )
    matching_candidates = [item for item in candidates if not topic or _topic_matches_scored_doc(topic, item)]
    if _query_aspects(req.query):
        matching_candidates.sort(
            key=lambda item: (_aspect_match_count(req.query, item), float(item.get("final_score", item.get("score", 0)))),
            reverse=True,
        )
    scored_docs = matching_candidates[:req.k]
    sources = _dedupe_sources([
        _source_from_scored_doc(item, topic, req.query, target_aspect=history_query.aspect)
        for item in scored_docs
    ])
    sufficiency = _sufficiency(sources, history_query)
    curated_fallback_added = False
    if sufficiency.status != "sufficient" and topic and history_query.aspect not in {"fact", "unknown"}:
        curated = _curated_event_source(topic, req.query, history_query.aspect)
        if curated and all(source.get("source_id") != curated.get("source_id") for source in sources):
            combined = [*sources, curated]
            if len(combined) > req.k:
                combined = [*combined[: max(req.k - 1, 0)], curated]
            sources = _dedupe_sources(combined)
            sufficiency = _sufficiency(sources, history_query)
            curated_fallback_added = True
    return ToolResult(
        tool_name="search_history_knowledge",
        ok=True,
        data={
            "sources": sources,
            "history_query": history_query.model_dump(mode="json"),
            "retrieval_status": sufficiency.status,
            "evidence_sufficiency": sufficiency.model_dump(mode="json"),
        },
        metadata={
            "source_count": len(sources),
            "answer_bearing_source_count": sufficiency.answer_bearing_source_count,
            "retrieval_status": sufficiency.status,
            "candidate_count": len(candidates),
            "rejected_irrelevant_count": len(candidates) - len(matching_candidates),
            "query": truncate_text(req.query, max_chars=160),
            "topic": topic,
            "entity": history_query.entity,
            "aspect": history_query.aspect,
            "query_confidence": history_query.confidence,
            "fusion": diagnostics.get("fusion"),
            "rerank_status": (diagnostics.get("reranker") or {}).get("status"),
            "curated_fallback_added": curated_fallback_added,
            "retrieval_diagnostics": diagnostics,
        },
    )
