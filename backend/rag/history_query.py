from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


HistoryEntityType = Literal["event", "person", "dynasty", "institution", "concept", "place", "unknown"]
HistoryAspect = Literal[
    "definition",
    "background",
    "cause",
    "process",
    "result",
    "impact",
    "significance",
    "measure",
    "contribution",
    "feature",
    "comparison",
    "evaluation",
    "fact",
    "unknown",
]
HistoryQuestionType = Literal["fact", "explanation", "comparison", "evaluation", "quiz", "unknown"]


class HistoryEntity(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: HistoryEntityType = "unknown"
    aliases: list[str] = Field(default_factory=list)
    grades: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    reviewed: bool = False


class HistoryQuery(BaseModel):
    schema_version: Literal[1] = 1
    original_query: str
    retrieval_query: str
    entity: str | None = None
    entity_id: str | None = None
    entity_type: HistoryEntityType = "unknown"
    aliases: list[str] = Field(default_factory=list)
    aspect: HistoryAspect = "unknown"
    question_type: HistoryQuestionType = "unknown"
    grade: str | None = None
    lesson: str | None = None
    inherited_from_context: bool = False
    confidence: float = 0.0
    needs_clarification: bool = False
    reason_codes: list[str] = Field(default_factory=list)


ROOT = Path(__file__).resolve().parents[2]
ENTITY_CATALOG_PATH = ROOT / "knowledge_base" / "history" / "entities.json"

_ASPECT_TERMS: tuple[tuple[HistoryAspect, tuple[str, ...]], ...] = (
    ("comparison", ("比较", "区别", "相同点", "不同点", "异同")),
    ("evaluation", ("评价", "如何看待", "怎么看", "认识", "文学史上的地位", "地位如何")),
    ("significance", ("意义", "为什么重要", "重要性")),
    ("contribution", ("贡献", "做了什么", "主要成就")),
    ("cause", ("原因", "为什么", "为何", "导火索")),
    ("background", ("背景", "条件", "生活在什么时代", "所处时代")),
    ("process", ("经过", "过程", "如何发生", "怎么发生")),
    ("result", ("结果", "结局", "后果")),
    ("impact", ("影响", "作用", "带来什么", "带来了什么", "产生什么", "变化")),
    ("measure", ("措施", "内容", "做法", "政策")),
    ("feature", ("特点", "特征")),
    ("definition", ("是什么", "什么是", "是谁", "介绍")),
)

_ASPECT_QUERY_LABEL: dict[HistoryAspect, str] = {
    "definition": "定义",
    "background": "背景",
    "cause": "原因",
    "process": "经过",
    "result": "结果",
    "impact": "影响",
    "significance": "意义",
    "measure": "措施",
    "contribution": "贡献",
    "feature": "特点",
    "comparison": "比较",
    "evaluation": "评价",
    "fact": "核心史实",
    "unknown": "",
}

_QUESTION_SUFFIX_RE = re.compile(
    r"(?:的)?(?:主要)?(?:原因|背景|经过|过程|结果|影响|意义|作用|特点|特征|贡献|目的|内容|措施|导火索|重要性)"
    r"(?:是什么|有哪些|如何|怎么样|有多大)?$"
)
_ACTION_SUFFIXES = (
    "做了什么",
    "是什么",
    "为什么",
    "为何",
    "有什么影响",
    "有什么意义",
    "怎么评价",
    "如何评价",
    "怎么理解",
    "介绍一下",
    "讲讲",
    "解释",
)
_CONTEXTUAL_TERMS = ("它", "这个", "刚才", "上面", "结合教材", "结合课文", "按教材", "用教材")
_COLLECTION_FEATURE_TERMS = ("以少胜多", "以弱胜强")
_COLLECTION_OBJECT_TERMS = ("战役", "战争", "战斗", "战例")
_COLLECTION_LIST_TERMS = ("哪些", "哪几", "有什么", "列举", "举例", "盘点")


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def collection_query_label(query: str) -> str | None:
    """Return a canonical subject for supported cross-entity list queries."""
    compact = _compact(query)
    if "世界" in compact:
        return None
    if (
        any(_compact(term) in compact for term in _COLLECTION_FEATURE_TERMS)
        and any(_compact(term) in compact for term in _COLLECTION_OBJECT_TERMS)
        and any(_compact(term) in compact for term in _COLLECTION_LIST_TERMS)
    ):
        return "中国古代以少胜多的战役"
    return None


@lru_cache(maxsize=2)
def _load_catalog_cached(path: str, mtime_ns: int) -> tuple[HistoryEntity, ...]:
    del mtime_ns
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()
    entities: list[HistoryEntity] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            entities.append(HistoryEntity.model_validate(item))
        except Exception:
            continue
    return tuple(entities)


def load_history_entities(path: Path = ENTITY_CATALOG_PATH) -> tuple[HistoryEntity, ...]:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return ()
    return _load_catalog_cached(str(path), mtime_ns)


def detect_history_aspect(query: str) -> HistoryAspect:
    compact = _compact(query)
    for aspect, terms in _ASPECT_TERMS:
        if any(_compact(term) in compact for term in terms):
            return aspect
    return "fact" if compact else "unknown"


def aspect_query_label(aspect: HistoryAspect) -> str:
    return _ASPECT_QUERY_LABEL.get(aspect, "")


def _question_type(query: str, aspect: HistoryAspect) -> HistoryQuestionType:
    compact = _compact(query)
    if any(term in compact for term in ("出题", "练习题", "测验")):
        return "quiz"
    if aspect == "comparison":
        return "comparison"
    if aspect == "evaluation":
        return "evaluation"
    if aspect in {"background", "cause", "process", "result", "impact", "significance", "contribution"}:
        return "explanation"
    if compact:
        return "fact"
    return "unknown"


def topic_anchor(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = str(value).strip(" ，。！？,.!?、")
    cleaned = re.sub(r"^(?:请|帮我|能不能|可以|直接|分析下|分析一下|解释下|解释一下|讲讲|说说)", "", cleaned)
    cleaned = re.sub(r"(?:请|一下|吗|呢|吧)$", "", cleaned)
    cleaned = _QUESTION_SUFFIX_RE.sub("", cleaned).strip(" ，。！？,.!?、的")
    for suffix in _ACTION_SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip(" ，。！？,.!?、的")
            break
    return cleaned or None


def _entity_matches(text: str, catalog: tuple[HistoryEntity, ...]) -> list[tuple[int, HistoryEntity, str]]:
    compact = _compact(text)
    matches: list[tuple[int, HistoryEntity, str]] = []
    for entity in catalog:
        names = [entity.canonical_name, *entity.aliases]
        for name in names:
            needle = _compact(name)
            if len(needle) >= 2 and needle in compact:
                matches.append((len(needle), entity, name))
                break
    return sorted(matches, key=lambda item: (item[1].reviewed, item[0]), reverse=True)


def _resolve_entity(text: str, catalog: tuple[HistoryEntity, ...]) -> tuple[HistoryEntity | None, list[HistoryEntity]]:
    matches = _entity_matches(text, catalog)
    if not matches:
        return None, []
    preferred_reviewed = matches[0][1].reviewed
    longest = max(item[0] for item in matches if item[1].reviewed == preferred_reviewed)
    top = [item[1] for item in matches if item[1].reviewed == preferred_reviewed and item[0] == longest]
    unique = {item.entity_id: item for item in top}
    values = list(unique.values())
    return (values[0] if len(values) == 1 else None), values


def parse_history_query(
    query: str,
    *,
    topic: str | None = None,
    grade: str | None = None,
    lesson: str | None = None,
    context_entity: str | None = None,
    catalog: tuple[HistoryEntity, ...] | None = None,
) -> HistoryQuery:
    original = str(query or "").strip()[:500]
    entities = catalog if catalog is not None else load_history_entities()
    collection_label = collection_query_label(original)
    explicit_anchor = topic_anchor(topic)
    query_anchor = topic_anchor(original)
    resolved, ambiguous = _resolve_entity(" ".join(value for value in (explicit_anchor, original) if value), entities)
    if collection_label:
        resolved, ambiguous = None, []
    inherited = False
    reason_codes: list[str] = []

    if resolved is None and context_entity and any(term in original for term in _CONTEXTUAL_TERMS):
        resolved, ambiguous = _resolve_entity(context_entity, entities)
        inherited = resolved is not None
        if inherited:
            reason_codes.append("entity_inherited_from_context")

    if resolved is None and explicit_anchor:
        resolved, ambiguous = _resolve_entity(explicit_anchor, entities)
    if resolved is None and query_anchor and query_anchor != original:
        resolved, ambiguous = _resolve_entity(query_anchor, entities)

    aspect = detect_history_aspect(original)
    entity_name = resolved.canonical_name if resolved else None
    needs_clarification = len(ambiguous) > 1 or (not entity_name and any(term in original for term in _CONTEXTUAL_TERMS))
    if len(ambiguous) > 1:
        reason_codes.append("ambiguous_entity")
    if collection_label:
        reason_codes.append("collection_query")
    elif not entity_name:
        reason_codes.append("entity_not_in_catalog")
    if needs_clarification:
        reason_codes.append("clarification_required")

    retrieval_parts = [collection_label or entity_name or explicit_anchor or query_anchor or original]
    aspect_label = aspect_query_label(aspect)
    if not collection_label and aspect_label and aspect_label not in retrieval_parts[0]:
        retrieval_parts.append(aspect_label)
    confidence = 0.90 if collection_label else 0.98 if resolved and resolved.reviewed else 0.92 if resolved else 0.55 if (explicit_anchor or query_anchor) else 0.2
    if inherited:
        confidence = min(confidence, 0.90)

    return HistoryQuery(
        original_query=original,
        retrieval_query=" ".join(part for part in retrieval_parts if part).strip()[:500],
        entity=entity_name,
        entity_id=resolved.entity_id if resolved else None,
        entity_type=resolved.entity_type if resolved else "unknown",
        aliases=resolved.aliases if resolved else [],
        aspect=aspect,
        question_type=_question_type(original, aspect),
        grade=grade,
        lesson=lesson,
        inherited_from_context=inherited,
        confidence=confidence,
        needs_clarification=needs_clarification,
        reason_codes=reason_codes,
    )
