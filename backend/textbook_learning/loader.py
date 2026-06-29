from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from textbook_learning.schema import (
    TextbookItem,
    TextbookLessonResponse,
    TextbookLessonTocItem,
    TextbookListItem,
    TextbookStatus,
    TextbookTocResponse,
    TextbookUnitTocItem,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
STRUCTURED_DIR = ROOT_DIR / "textbooks" / "structured"

BOOK_ID_MAP = {
    "中国历史七年级上册": "history-grade-7a",
    "中国历史七年级下册": "history-grade-7b",
    "中国历史八年级上册": "history-grade-8a",
    "中国历史八年级下册": "history-grade-8b",
    "世界历史九年级上册": "world-history-grade-9a",
    "世界历史九年级下册": "world-history-grade-9b",
}

BOOK_ORDER = {
    "history-grade-7a": 10,
    "history-grade-7b": 11,
    "history-grade-8a": 20,
    "history-grade-8b": 21,
    "world-history-grade-9a": 30,
    "world-history-grade-9b": 31,
}

ALLOWED_ITEM_TYPES = {"textbook", "primary", "concept", "timeline"}


@dataclass(frozen=True)
class LoadedTextbook:
    id: str
    grade: str
    book: str
    source: str
    status: TextbookStatus
    units: list[dict[str, Any]]
    message: str | None = None

    @property
    def lesson_count(self) -> int:
        return sum(len(unit.get("lessons", [])) for unit in self.units)

    @property
    def item_count(self) -> int:
        return sum(len(lesson.get("items", [])) for unit in self.units for lesson in unit.get("lessons", []))


def _normalize_book_name(book: str) -> str:
    return re.sub(r"（.*?）|\(.*?\)", "", book).strip()


def _slugify_book_id(grade: str, book: str) -> str:
    normalized = _normalize_book_name(book)
    mapped = BOOK_ID_MAP.get(normalized)
    if mapped:
        return mapped
    source = f"{grade}-{normalized}"
    slug = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", source).strip("-").lower()
    return slug or "textbook"


def _validate_raw(data: dict[str, Any]) -> tuple[TextbookStatus, str | None]:
    if not data.get("grade") or not data.get("book"):
        return "invalid", "缺少 grade 或 book"
    units = data.get("units")
    if not isinstance(units, list) or not units:
        return "empty", "缺少 units"

    item_count = 0
    for unit_index, unit in enumerate(units, start=1):
        if not isinstance(unit, dict) or not unit.get("title"):
            return "invalid", f"第 {unit_index} 个单元缺少 title"
        lessons = unit.get("lessons")
        if not isinstance(lessons, list) or not lessons:
            return "empty", f"{unit.get('title')} 缺少 lessons"
        for lesson_index, lesson in enumerate(lessons, start=1):
            if not isinstance(lesson, dict) or not lesson.get("title"):
                return "invalid", f"第 {unit_index} 单元第 {lesson_index} 课缺少 title"
            items = lesson.get("items")
            if not isinstance(items, list) or not items:
                return "empty", f"{lesson.get('title')} 缺少 items"
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    return "invalid", f"{lesson.get('title')} 第 {item_index} 条不是对象"
                for field in ("text", "topic", "type", "page"):
                    if field not in item or item.get(field) in (None, ""):
                        return "invalid", f"{lesson.get('title')} 第 {item_index} 条缺少 {field}"
                if item.get("type") not in ALLOWED_ITEM_TYPES:
                    return "invalid", f"{lesson.get('title')} 第 {item_index} 条 type 不支持"
                item_count += 1

    if item_count == 0:
        return "empty", "没有可用知识点"
    return "ready", None


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        raw = value
    else:
        raw = [value]
    return [str(item).strip() for item in raw if str(item).strip()]


def _split_title_terms(text: str) -> list[str]:
    cleaned = re.sub(r"第\d+课|第[一二三四五六七八九十百]+课|第[一二三四五六七八九十百]+单元", "", text)
    parts = re.split(r"[：:、，,和与及\s（）()《》\"“”]+", cleaned)
    return [part.strip() for part in parts if len(part.strip()) >= 2]


def _merge_text_lists(*groups: list[str]) -> list[str]:
    seen = set()
    result = []
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
    return result


def _normalize_item(item: dict[str, Any], unit_title: str, lesson_title: str) -> dict[str, Any]:
    normalized = dict(item)
    topic = str(normalized.get("topic") or "").strip()
    unit_terms = _split_title_terms(unit_title)
    lesson_terms = _split_title_terms(lesson_title)
    topic_terms = _split_title_terms(topic)

    normalized["tags"] = _merge_text_lists(_text_list(normalized.get("tags")), topic_terms, lesson_terms[:3], unit_terms[:2])
    normalized["entities"] = _merge_text_lists(_text_list(normalized.get("entities")), [topic] if 2 <= len(topic) <= 8 else [])
    normalized["keywords"] = _merge_text_lists(_text_list(normalized.get("keywords")), topic_terms, lesson_terms[:3])
    normalized["event"] = str(normalized.get("event") or topic).strip() or None
    normalized["period"] = str(normalized.get("period") or (lesson_terms[0] if lesson_terms else unit_terms[0] if unit_terms else "")).strip() or None
    return normalized


def _with_ids(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lesson_counter = 0
    result = []
    for unit in units:
        lessons = []
        for lesson in unit.get("lessons", []):
            lesson_counter += 1
            lesson_id = f"lesson-{lesson_counter}"
            items = []
            for item_index, item in enumerate(lesson.get("items", []), start=1):
                items.append({**_normalize_item(item, str(unit.get("title") or ""), str(lesson.get("title") or "")), "id": f"{lesson_id}-item-{item_index}"})
            lessons.append({**lesson, "id": lesson_id, "items": items})
        result.append({**unit, "lessons": lessons})
    return result


def _load_file(path: Path) -> LoadedTextbook:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return LoadedTextbook(
            id=path.stem,
            grade="",
            book=path.stem,
            source=str(path.relative_to(ROOT_DIR)),
            status="invalid",
            units=[],
            message=str(exc),
        )

    if not isinstance(data, dict):
        return LoadedTextbook(
            id=path.stem,
            grade="",
            book=path.stem,
            source=str(path.relative_to(ROOT_DIR)),
            status="invalid",
            units=[],
            message="YAML 根节点不是对象",
        )

    grade = str(data.get("grade") or "")
    book = str(data.get("book") or path.stem)
    status, message = _validate_raw(data)
    units = _with_ids(data.get("units") or []) if status == "ready" else []
    return LoadedTextbook(
        id=_slugify_book_id(grade, book),
        grade=grade,
        book=book,
        source=str(path.relative_to(ROOT_DIR)),
        status=status,
        units=units,
        message=message,
    )


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, LoadedTextbook]:
    textbooks = [_load_file(path) for path in sorted(STRUCTURED_DIR.glob("*.yaml"))]
    catalog: dict[str, LoadedTextbook] = {}
    for textbook in textbooks:
        key = textbook.id
        suffix = 2
        while key in catalog:
            key = f"{textbook.id}-{suffix}"
            suffix += 1
        if key != textbook.id:
            textbook = LoadedTextbook(
                id=key,
                grade=textbook.grade,
                book=textbook.book,
                source=textbook.source,
                status=textbook.status,
                units=textbook.units,
                message=textbook.message,
            )
        catalog[key] = textbook
    return catalog


def list_textbooks() -> list[TextbookListItem]:
    textbooks = sorted(load_catalog().values(), key=lambda book: (BOOK_ORDER.get(book.id, 999), book.grade, book.book))
    return [
        TextbookListItem(
            id=book.id,
            grade=book.grade,
            book=book.book,
            source=book.source,
            status=book.status,
            unit_count=len(book.units),
            lesson_count=book.lesson_count,
            item_count=book.item_count,
            message=book.message,
        )
        for book in textbooks
    ]


def get_textbook(book_id: str) -> LoadedTextbook:
    textbook = load_catalog().get(book_id)
    if not textbook:
        raise LookupError("未找到教材")
    if textbook.status != "ready":
        raise ValueError(textbook.message or "教材暂不可用")
    return textbook


def get_toc(book_id: str) -> TextbookTocResponse:
    textbook = get_textbook(book_id)
    return TextbookTocResponse(
        book_id=textbook.id,
        grade=textbook.grade,
        book=textbook.book,
        status=textbook.status,
        units=[
            TextbookUnitTocItem(
                title=unit["title"],
                lessons=[
                    TextbookLessonTocItem(
                        id=lesson["id"],
                        title=lesson["title"],
                        item_count=len(lesson.get("items", [])),
                    )
                    for lesson in unit.get("lessons", [])
                ],
            )
            for unit in textbook.units
        ],
    )


def get_lesson(book_id: str, lesson_id: str) -> TextbookLessonResponse:
    textbook = get_textbook(book_id)
    for unit in textbook.units:
        for lesson in unit.get("lessons", []):
            if lesson.get("id") == lesson_id:
                return TextbookLessonResponse(
                    book_id=textbook.id,
                    lesson_id=lesson_id,
                    grade=textbook.grade,
                    book=textbook.book,
                    unit_title=unit["title"],
                    lesson_title=lesson["title"],
                    items=[TextbookItem(**item) for item in lesson.get("items", [])],
                )
    raise LookupError("未找到课程")
