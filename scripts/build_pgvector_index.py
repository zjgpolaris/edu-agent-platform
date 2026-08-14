"""离线建索引：把 knowledge_base/history/corpus.json 向量化写入 Postgres + pgvector。

用法（需连真库，建议本地或 CI 跑一次，改语料后重跑）：
    DATABASE_URL=postgresql://... \
    EMBED_API_BASE=https://api.jina.ai/v1 \
    EMBED_API_KEY=jina_... \
    EMBED_MODEL=jina-embeddings-v3 EMBED_TASK=text-matching EMBED_DIM=1024 \
    python3 scripts/build_pgvector_index.py

- 不在生产运行时执行；生产只查询。
- 依赖 rag_documents 表（见 alembic 003）。脚本会先确保扩展/表存在。
- 分批 embedding + 分批 upsert，并实时打印进度；可安全重跑（先清空 history 集合）。
"""
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from langchain_core.documents import Document
from sqlalchemy import text as sa_text

from db.engine import DATABASE_URL, engine
from rag.knowledge_base import EMBED_DIM, RAG_TABLE, get_embed_model, load_vectorstore, splitter
from scripts.build_history_documents import build_history_documents

BATCH_SIZE = 50


def _ensure_table() -> None:
    if not DATABASE_URL.startswith(("postgresql", "postgres")):
        print(f"ERROR: DATABASE_URL 必须指向 Postgres（当前：{DATABASE_URL.split('://')[0]}）。", flush=True)
        sys.exit(1)
    with engine.begin() as conn:
        conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(sa_text(
            f"CREATE TABLE IF NOT EXISTS {RAG_TABLE} ("
            "id TEXT PRIMARY KEY, collection TEXT NOT NULL, content TEXT NOT NULL, "
            "metadata JSONB NOT NULL DEFAULT '{}'::jsonb, "
            f"embedding vector({EMBED_DIM}))"
        ))
        conn.execute(sa_text(
            f"CREATE INDEX IF NOT EXISTS idx_{RAG_TABLE}_collection ON {RAG_TABLE} (collection)"
        ))


def _load_chunks(corpus_path: Path) -> list[Document]:
    raw = build_history_documents() if corpus_path.name == "corpus.json" else json.loads(corpus_path.read_text(encoding="utf-8"))
    docs = [
        Document(
            page_content=f"{d['meta'].get('topic', '')}：{d['text']}" if d.get("meta", {}).get("topic") else d["text"],
            metadata={k: v for k, v in d.get("meta", {}).items() if v is not None},
        )
        for d in raw
    ]
    return splitter.split_documents(docs)


def _stable_chunk_ids(chunks: list[Document]) -> list[str]:
    seen: dict[str, int] = {}
    ids: list[str] = []
    for doc in chunks:
        base = str((doc.metadata or {}).get("source_id") or "").strip()
        if not base:
            base = "history_" + hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()[:24]
        index = seen.get(base, 0)
        seen[base] = index + 1
        ids.append(base if index == 0 else f"{base}_chunk_{index + 1}")
    return ids


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _write_manifest(chunks: list[Document], indexed_row_count: int) -> None:
    type_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    for doc in chunks:
        metadata = doc.metadata or {}
        doc_type = str(metadata.get("document_type") or "unknown")
        tier = str(metadata.get("source_tier") or "unknown")
        type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    manifest = {
        "schema_version": 1,
        "corpus_version": "history-v1.31",
        "collection": "history",
        "document_count": len({str((doc.metadata or {}).get("source_id") or "") for doc in chunks}),
        "chunk_count": len(chunks),
        "indexed_row_count": indexed_row_count,
        "document_type_counts": type_counts,
        "source_tier_counts": tier_counts,
        "embedding_model": get_embed_model().model,
        "embedding_dimension": EMBED_DIM,
        "splitter_version": "recursive-800-120-v1",
        "build_commit": _git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    target = ROOT / "knowledge_base" / "history" / "index_manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    corpus_path = ROOT / "knowledge_base" / "history" / "corpus.json"
    if not corpus_path.exists():
        print(f"ERROR: 未找到 {corpus_path}", flush=True)
        sys.exit(1)

    _ensure_table()
    chunks = _load_chunks(corpus_path)
    chunk_ids = _stable_chunk_ids(chunks)
    store = load_vectorstore("history")
    print(
        f"准备重建 collection='history'：{corpus_path.name} -> {len(chunks)} chunks, dim={EMBED_DIM}, batch={BATCH_SIZE}",
        flush=True,
    )
    print("预检 embedding API...", flush=True)
    probe = get_embed_model().embed_query("三国鼎立的意义")
    print(f"embedding API OK：dim={len(probe)}。开始清空并重建 history 集合。", flush=True)
    store.delete_collection()

    started = time.perf_counter()
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        ids = chunk_ids[start:start + len(batch)]
        batch_started = time.perf_counter()
        store.add_documents(batch, ids=ids)
        done = start + len(batch)
        print(
            f"[{done}/{len(chunks)}] batch={len(batch)} elapsed={time.perf_counter() - batch_started:.1f}s total={time.perf_counter() - started:.1f}s",
            flush=True,
        )

    with engine.connect() as conn:
        count = conn.execute(
            sa_text(f"SELECT count(*) FROM {RAG_TABLE} WHERE collection = :c"),
            {"c": "history"},
        ).scalar()
    _write_manifest(chunks, int(count or 0))
    print(f"完成。history 集合现有 {count} 条向量，总耗时 {time.perf_counter() - started:.1f}s。", flush=True)


if __name__ == "__main__":
    main()
