"""Build normalized parent-child history documents for retrieval indexing."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "knowledge_base" / "history"


def _bootstrap_backend() -> None:
    import sys

    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _entity_lookup() -> dict[str, dict[str, Any]]:
    path = HISTORY_DIR / "entities.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        for name in [row.get("canonical_name"), *(row.get("aliases") or [])]:
            if name:
                lookup[str(name)] = row
    return lookup


def _best_entity(meta: dict[str, Any], text: str, lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        meta.get("event"),
        *(meta.get("entities") or []),
        meta.get("topic"),
    ]
    matches = [lookup[str(name)] for name in candidates if str(name or "") in lookup]
    if not matches:
        contained = [row for name, row in lookup.items() if len(name) >= 2 and name in text]
        matches = contained
    if not matches:
        return None
    return max(matches, key=lambda row: len(str(row.get("canonical_name") or "")))


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    return [item.strip() for item in re.split(r"(?<=[。！？；])", compact) if 30 <= len(item.strip()) <= 220]


def build_history_documents() -> list[dict[str, Any]]:
    _bootstrap_backend()
    from rag.history_documents import stable_history_source_id
    from rag.history_query import detect_history_aspect

    corpus = json.loads((HISTORY_DIR / "corpus.json").read_text(encoding="utf-8"))
    events = json.loads((HISTORY_DIR / "geo_events.json").read_text(encoding="utf-8"))
    entities = _entity_lookup()
    documents: list[dict[str, Any]] = []

    for row in corpus:
        text = str(row.get("text") or "").strip()
        meta = dict(row.get("meta") or {})
        if not text:
            continue
        source_title = str(meta.get("source") or "历史教材")
        passage_id = stable_history_source_id(
            source_title=source_title,
            grade=str(meta.get("grade") or "") or None,
            lesson=str(meta.get("lesson") or "") or None,
            page=meta.get("page"),
            document_type="textbook_passage",
            claim=text,
        )
        entity = _best_entity(meta, text, entities)
        passage_meta = {
            **meta,
            "source_id": passage_id,
            "document_type": "textbook_passage",
            "source_tier": "L1_TEXTBOOK_DIRECT",
            "source_title": source_title,
            "claim": text,
            "entity_id": (entity or {}).get("entity_id"),
            "entity": (entity or {}).get("canonical_name"),
            "aliases": (entity or {}).get("aliases") or [],
            "aspect": detect_history_aspect(f"{meta.get('topic', '')} {text}"),
            "corpus_version": "history-v1.31",
            "reviewed": True,
        }
        documents.append({"text": text, "meta": passage_meta})

        for sentence in _sentences(text):
            fact_entity = _best_entity(meta, sentence, entities) or entity
            fact_id = stable_history_source_id(
                source_title=source_title,
                grade=str(meta.get("grade") or "") or None,
                lesson=str(meta.get("lesson") or "") or None,
                page=meta.get("page"),
                document_type="textbook_fact",
                claim=sentence,
            )
            documents.append({
                "text": sentence,
                "meta": {
                    **meta,
                    "source_id": fact_id,
                    "parent_source_id": passage_id,
                    "document_type": "textbook_fact",
                    "source_tier": "L2_TEXTBOOK_DERIVED",
                    "source_title": source_title,
                    "claim": sentence,
                    "context": text[:800],
                    "entity_id": (fact_entity or {}).get("entity_id"),
                    "entity": (fact_entity or {}).get("canonical_name"),
                    "aliases": (fact_entity or {}).get("aliases") or [],
                    "aspect": detect_history_aspect(f"{meta.get('topic', '')} {sentence}"),
                    "corpus_version": "history-v1.31",
                    "reviewed": False,
                },
            })

    for event in events:
        title = str(event.get("title") or "").strip()
        summary = str(event.get("summary") or "").strip()
        if not title or not summary:
            continue
        entity = entities.get(title)
        source_title = "历史事件补充资料库"
        source_id = stable_history_source_id(
            source_title=f"{source_title}:{title}",
            grade=None,
            lesson=None,
            page=None,
            document_type="curated_event_fact",
            claim=summary,
        )
        documents.append({
            "text": f"{title}：{summary}",
            "meta": {
                "source_id": source_id,
                "document_type": "curated_event_fact",
                "source_tier": "L3_CURATED_REFERENCE",
                "source_title": source_title,
                "source": source_title,
                "topic": title,
                "event": title,
                "entity_id": (entity or {}).get("entity_id"),
                "entity": title,
                "aliases": (entity or {}).get("aliases") or [],
                "aspect": detect_history_aspect(summary),
                "claim": summary,
                "context": event.get("location_name"),
                "period": event.get("dynasty"),
                "entities": [title, event.get("character")] if event.get("character") else [title],
                "corpus_version": "history-v1.31",
                "reviewed": bool(event.get("reviewed", False)),
                "meta_source": "geo_events",
            },
        })
    deduplicated: dict[str, dict[str, Any]] = {}
    for document in documents:
        source_id = str((document.get("meta") or {}).get("source_id") or "")
        if source_id:
            deduplicated.setdefault(source_id, document)
    return list(deduplicated.values())


def main() -> None:
    documents = build_history_documents()
    target = HISTORY_DIR / "documents.json"
    target.write_text(json.dumps(documents, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for row in documents:
        doc_type = str((row.get("meta") or {}).get("document_type"))
        counts[doc_type] = counts.get(doc_type, 0) + 1
    print(f"history_documents={len(documents)} counts={counts} target={target}")


if __name__ == "__main__":
    main()
