"""Convert structured textbook YAML files into history corpus entries."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"textbook", "primary", "timeline", "concept"}
DEFAULT_STRUCTURED_DIR = Path("textbooks/structured")
DEFAULT_CORPUS_PATH = Path("knowledge_base/history/corpus.json")
LIST_META_FIELDS = {"tags", "entities", "keywords"}
TEXT_META_FIELDS = {"event", "period"}
STRUCTURED_META_SOURCE = "textbook_structured"
ENTITY_SUFFIXES = ("帝", "王", "公", "侯", "宗", "祖")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing dependency: install PyYAML with `pip install pyyaml`.") from exc

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML object at the top level")
    return data


def require_text(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: `{field}` must be a non-empty string")
    return value.strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.replace("，", ",").split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]

    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def merge_text_lists(*groups: list[str]) -> list[str]:
    seen = set()
    result = []
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
    return result


def split_title_terms(text: str) -> list[str]:
    cleaned = re.sub(r"第\d+课|第[一二三四五六七八九十百]+课|第[一二三四五六七八九十百]+单元", "", text)
    parts = re.split(r"[：:、，,和与及\s（）()《》\"“”]+", cleaned)
    return [part.strip() for part in parts if len(part.strip()) >= 2]


def extract_entities(topic: str, text: str) -> list[str]:
    candidates = []
    if 2 <= len(topic) <= 8:
        candidates.append(topic)
    candidates.extend(re.findall(r"[一-鿿]{2,4}(?:" + "|".join(ENTITY_SUFFIXES) + r")", text))
    candidates.extend(re.findall(r"[一-鿿]{2,4}(?:氏|子|太后|皇后|将军|管带)", text))
    return merge_text_lists(candidates)


def derive_metadata(
    grade: str,
    unit_title: str,
    lesson_title: str,
    topic: str,
    text: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    explicit_tags = optional_text_list(item.get("tags"))
    explicit_entities = optional_text_list(item.get("entities"))
    explicit_keywords = optional_text_list(item.get("keywords"))

    lesson_terms = split_title_terms(lesson_title)
    unit_terms = split_title_terms(unit_title)
    topic_terms = split_title_terms(topic)
    derived_entities = extract_entities(topic, text)
    derived_keywords = merge_text_lists(topic_terms, lesson_terms[:3])

    metadata: dict[str, Any] = {
        "event": optional_text(item.get("event")) or topic,
        "period": optional_text(item.get("period")) or (lesson_terms[0] if lesson_terms else unit_terms[0] if unit_terms else grade),
        "tags": merge_text_lists(explicit_tags, topic_terms, lesson_terms[:3], unit_terms[:2]),
        "entities": merge_text_lists(explicit_entities, derived_entities),
        "keywords": merge_text_lists(explicit_keywords, derived_keywords),
    }
    return {key: value for key, value in metadata.items() if value not in (None, "", [])}


def add_optional_metadata(
    meta: dict[str, Any],
    item: dict[str, Any],
    grade: str,
    unit_title: str,
    lesson_title: str,
    topic: str,
    text: str,
) -> None:
    meta.update(derive_metadata(grade, unit_title, lesson_title, topic, text, item))


def yaml_to_corpus(yaml_path: Path) -> list[dict[str, Any]]:
    data = load_yaml(yaml_path)
    grade = require_text(data.get("grade"), "grade", yaml_path)
    book = require_text(data.get("book"), "book", yaml_path)
    units = data.get("units")
    if not isinstance(units, list):
        raise ValueError(f"{yaml_path}: `units` must be a list")

    entries: list[dict[str, Any]] = []
    for unit_index, unit in enumerate(units, start=1):
        if not isinstance(unit, dict):
            raise ValueError(f"{yaml_path}: units[{unit_index}] must be an object")
        unit_title = require_text(unit.get("title"), f"units[{unit_index}].title", yaml_path)
        lessons = unit.get("lessons")
        if not isinstance(lessons, list):
            raise ValueError(f"{yaml_path}: units[{unit_index}].lessons must be a list")

        for lesson_index, lesson in enumerate(lessons, start=1):
            if not isinstance(lesson, dict):
                raise ValueError(
                    f"{yaml_path}: units[{unit_index}].lessons[{lesson_index}] must be an object"
                )
            lesson_title = require_text(
                lesson.get("title"),
                f"units[{unit_index}].lessons[{lesson_index}].title",
                yaml_path,
            )
            items = lesson.get("items")
            if not isinstance(items, list):
                raise ValueError(
                    f"{yaml_path}: units[{unit_index}].lessons[{lesson_index}].items must be a list"
                )

            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"{yaml_path}: units[{unit_index}].lessons[{lesson_index}].items[{item_index}] must be an object"
                    )
                item_type = item.get("type", "textbook")
                if item_type not in ALLOWED_TYPES:
                    raise ValueError(
                        f"{yaml_path}: unsupported type `{item_type}` at "
                        f"units[{unit_index}].lessons[{lesson_index}].items[{item_index}]"
                    )

                topic = str(item.get("topic", "") or "").strip()
                text = require_text(
                    item.get("text"),
                    f"units[{unit_index}].lessons[{lesson_index}].items[{item_index}].text",
                    yaml_path,
                )
                meta = {
                    "grade": grade,
                    "book": book,
                    "unit": unit_title,
                    "lesson": lesson_title,
                    "topic": topic,
                    "source": str(item.get("source") or f"《{book}》正文").strip(),
                    "type": item_type,
                    "meta_source": STRUCTURED_META_SOURCE,
                    "structured_file": yaml_path.name,
                }
                if item.get("page") is not None:
                    meta["page"] = item["page"]
                add_optional_metadata(meta, item, grade, unit_title, lesson_title, topic, text)

                entries.append({"text": text, "meta": meta})
    return entries


def load_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array")
    return data


def merge_without_duplicate_text(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]], replace_structured: bool = True
) -> tuple[list[dict[str, Any]], int, int]:
    incoming_texts = {item["text"].strip() for item in incoming}
    base = []
    replaced = 0
    for item in existing:
        meta = item.get("meta", {}) if isinstance(item, dict) else {}
        text = str(item.get("text", "")).strip()
        should_replace = replace_structured and (
            isinstance(meta, dict) and meta.get("meta_source") == STRUCTURED_META_SOURCE or text in incoming_texts
        )
        if should_replace:
            replaced += 1
            continue
        base.append(item)

    seen = {str(item.get("text", "")).strip() for item in base if item.get("text")}
    merged = list(base)
    skipped = 0
    for item in incoming:
        text = item["text"].strip()
        if text in seen:
            skipped += 1
            continue
        seen.add(text)
        merged.append(item)
    return merged, skipped, replaced


def parse_all(structured_dir: Path) -> list[dict[str, Any]]:
    files = sorted(structured_dir.glob("*.yaml")) + sorted(structured_dir.glob("*.yml"))
    if not files:
        raise FileNotFoundError(f"No YAML files found in {structured_dir}")

    entries: list[dict[str, Any]] = []
    for yaml_path in files:
        entries.extend(yaml_to_corpus(yaml_path))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge structured textbook YAML files into the history corpus."
    )
    parser.add_argument("--structured-dir", type=Path, default=DEFAULT_STRUCTURED_DIR)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keep-existing-structured",
        action="store_true",
        help="Append new structured entries without replacing previous structured textbook entries.",
    )
    args = parser.parse_args()

    incoming = parse_all(args.structured_dir)
    existing = load_existing(args.corpus)
    merged, skipped, replaced = merge_without_duplicate_text(
        existing,
        incoming,
        replace_structured=not args.keep_existing_structured,
    )
    output = args.output or args.corpus

    if not args.dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"Existing: {len(existing)} | New: {len(incoming)} | "
        f"Replaced structured: {replaced} | Skipped duplicates: {skipped} | Total: {len(merged)}"
    )
    if args.dry_run:
        print(f"Dry run only; {output} was not modified.")
    else:
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
