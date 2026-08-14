"""Validate normalized history retrieval documents before indexing."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_history_documents import build_history_documents


def main() -> None:
    documents = build_history_documents()
    source_ids = [str((row.get("meta") or {}).get("source_id") or "") for row in documents]
    failures: list[str] = []
    if not documents:
        failures.append("document_set_empty")
    if any(not source_id for source_id in source_ids):
        failures.append("source_id_missing")
    if len(source_ids) != len(set(source_ids)):
        failures.append("source_id_duplicate")

    ids = set(source_ids)
    for index, row in enumerate(documents):
        meta = row.get("meta") or {}
        doc_type = meta.get("document_type")
        tier = meta.get("source_tier")
        if doc_type not in {"textbook_passage", "textbook_fact", "curated_event_fact"}:
            failures.append(f"invalid_document_type:{index}")
        if tier not in {"L1_TEXTBOOK_DIRECT", "L2_TEXTBOOK_DERIVED", "L3_CURATED_REFERENCE"}:
            failures.append(f"invalid_source_tier:{index}")
        if doc_type == "textbook_fact" and meta.get("parent_source_id") not in ids:
            failures.append(f"invalid_parent_source_id:{index}")
        if tier == "L3_CURATED_REFERENCE" and meta.get("page") not in (None, ""):
            failures.append(f"curated_source_has_textbook_page:{index}")

    if failures:
        raise SystemExit("history_corpus_validation=FAIL " + ",".join(failures[:20]))
    print(f"history_corpus_validation=PASS documents={len(documents)} unique_source_ids={len(ids)}")


if __name__ == "__main__":
    main()

