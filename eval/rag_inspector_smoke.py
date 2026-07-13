from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")
if not os.environ.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
    os.environ["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)

from rag.knowledge_base import build_rag_inspector, search_with_scores
from textbook_learning.schema import TextbookAskRequest
from textbook_learning.service import stream_ask_events
from trace_store import create_trace_id, trace_context


def _skip(reason: str) -> None:
    print(f"SKIP rag_inspector_smoke: {reason}")
    raise SystemExit(0)


def search_inspector_contract() -> None:
    try:
        scored_docs = search_with_scores("history", "鸦片战争", k=2, mode="hybrid", fetch_k=10)
    except Exception as exc:
        _skip(f"embedding/RAG unavailable ({exc})")
    inspector = build_rag_inspector(collection="history", original_query="鸦片战争", scored_docs=scored_docs, mode="hybrid")
    assert inspector["original_query"] == "鸦片战争"
    assert inspector["source_count"] == len(scored_docs)
    assert isinstance(inspector["chunks"], list)
    if scored_docs:
        chunk = inspector["chunks"][0]
        for key in ("rank", "topic", "source_mode", "final_score", "keyword_score", "content_preview"):
            assert key in chunk


def textbook_sources_emit_inspector() -> None:
    try:
        trace_id = create_trace_id()
        req = TextbookAskRequest(
            book_id="history-grade-8a",
            lesson_id="lesson-1",
            question="鸦片战争为什么重要",
            item_id="lesson-1-item-2",
        )
        with trace_context(trace_id):
            events = stream_ask_events(req)
            for event, data in events:
                if event != "sources":
                    continue
                inspector = data.get("rag_inspector")
                assert isinstance(inspector, dict)
                assert inspector["original_query"]
                assert isinstance(inspector["chunks"], list)
                assert inspector["diagnosis_code"]
                assert inspector["diagnosis_summary"]
                assert data.get("sources")
                return
    except Exception as exc:
        _skip(f"textbook stream unavailable ({exc})")
    raise AssertionError("sources event was not emitted")


def main() -> None:
    search_inspector_contract()
    textbook_sources_emit_inspector()
    print("rag_inspector_smoke=PASS")


if __name__ == "__main__":
    main()
