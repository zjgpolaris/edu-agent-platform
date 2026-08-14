from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from rag.history_query import HistoryAspect, detect_history_aspect


HistoryDocumentType = Literal["textbook_passage", "textbook_fact", "curated_event_fact"]
HistorySourceTier = Literal["L1_TEXTBOOK_DIRECT", "L2_TEXTBOOK_DERIVED", "L3_CURATED_REFERENCE"]


class HistorySource(BaseModel):
    source_id: str
    parent_source_id: str | None = None
    document_type: HistoryDocumentType
    source_tier: HistorySourceTier
    entity_id: str | None = None
    entity: str | None = None
    aliases: list[str] = Field(default_factory=list)
    aspect: HistoryAspect = "fact"
    claim: str
    context: str | None = None
    grade: str | None = None
    unit: str | None = None
    lesson: str | None = None
    page: int | None = None
    source_title: str
    corpus_version: str = "legacy-v1"
    reviewed: bool = False


def normalize_claim(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def stable_history_source_id(*, source_title: str, grade: str | None, lesson: str | None, page: Any, document_type: str, claim: str) -> str:
    basis = "|".join(
        normalize_claim(value)
        for value in (source_title, grade or "", lesson or "", page if page is not None else "", document_type, claim)
    )
    return f"history_{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:24]}"


def source_tier_from_metadata(metadata: dict[str, Any]) -> HistorySourceTier:
    explicit = str(metadata.get("source_tier") or "")
    if explicit in {"L1_TEXTBOOK_DIRECT", "L2_TEXTBOOK_DERIVED", "L3_CURATED_REFERENCE"}:
        return explicit  # type: ignore[return-value]
    if str(metadata.get("document_type") or "") == "curated_event_fact" or str(metadata.get("meta_source") or "") == "geo_events":
        return "L3_CURATED_REFERENCE"
    return "L1_TEXTBOOK_DIRECT"


def document_type_from_metadata(metadata: dict[str, Any]) -> HistoryDocumentType:
    explicit = str(metadata.get("document_type") or "")
    if explicit in {"textbook_passage", "textbook_fact", "curated_event_fact"}:
        return explicit  # type: ignore[return-value]
    if source_tier_from_metadata(metadata) == "L3_CURATED_REFERENCE":
        return "curated_event_fact"
    return "textbook_passage"


def history_source_fields(content: str, metadata: dict[str, Any]) -> dict[str, Any]:
    document_type = document_type_from_metadata(metadata)
    source_tier = source_tier_from_metadata(metadata)
    source_title = str(metadata.get("source_title") or metadata.get("source") or "历史知识库")
    claim = str(metadata.get("claim") or content).strip()
    source_id = str(metadata.get("source_id") or "").strip() or stable_history_source_id(
        source_title=source_title,
        grade=str(metadata.get("grade") or "") or None,
        lesson=str(metadata.get("lesson") or "") or None,
        page=metadata.get("page"),
        document_type=document_type,
        claim=claim,
    )
    aspect = str(metadata.get("aspect") or "")
    if aspect not in {
        "definition", "background", "cause", "process", "result", "impact", "significance",
        "measure", "contribution", "feature", "comparison", "evaluation", "fact", "unknown",
    }:
        aspect = detect_history_aspect(f"{metadata.get('topic', '')} {claim}")
    return {
        "source_id": source_id,
        "parent_source_id": metadata.get("parent_source_id"),
        "document_type": document_type,
        "source_tier": source_tier,
        "entity_id": metadata.get("entity_id"),
        "entity": metadata.get("entity") or metadata.get("event"),
        "aliases": metadata.get("aliases") or [],
        "aspect": aspect,
        "claim": claim,
        "context": metadata.get("context"),
        "grade": metadata.get("grade"),
        "unit": metadata.get("unit"),
        "lesson": metadata.get("lesson"),
        "page": metadata.get("page"),
        "source_title": source_title,
        "corpus_version": str(metadata.get("corpus_version") or "legacy-v1"),
        "reviewed": bool(metadata.get("reviewed", False)),
    }

