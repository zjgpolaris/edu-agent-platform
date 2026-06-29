"""离线建索引：把 knowledge_base/history/corpus.json 向量化写入 Postgres + pgvector。

用法（需连真库，建议本地或 CI 跑一次，改语料后重跑）：
    DATABASE_URL=postgresql://... \
    BAILIAN_API_KEY=sk-... \
    [BAILIAN_BASE_URL=...] [EMBED_MODEL=text-embedding-v3] [EMBED_DIM=1024] \
    python3 scripts/build_pgvector_index.py

- 不在生产运行时执行；生产只查询。
- 依赖 rag_documents 表（见 alembic 003）。脚本会先确保扩展/表存在。
- 分批 embedding + 分批 upsert，并实时打印进度；可安全重跑（先清空 history 集合）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.documents import Document
from sqlalchemy import text as sa_text

from db.engine import DATABASE_URL, engine
from rag.knowledge_base import EMBED_DIM, RAG_TABLE, get_embed_model, load_vectorstore, splitter

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
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    docs = [
        Document(
            page_content=f"{d['meta'].get('topic', '')}：{d['text']}" if d.get("meta", {}).get("topic") else d["text"],
            metadata={k: v for k, v in d.get("meta", {}).items() if v is not None},
        )
        for d in raw
    ]
    return splitter.split_documents(docs)


def main() -> None:
    corpus_path = ROOT / "knowledge_base" / "history" / "corpus.json"
    if not corpus_path.exists():
        print(f"ERROR: 未找到 {corpus_path}", flush=True)
        sys.exit(1)

    _ensure_table()
    chunks = _load_chunks(corpus_path)
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
        ids = [f"history-{i}" for i in range(start, start + len(batch))]
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
    print(f"完成。history 集合现有 {count} 条向量，总耗时 {time.perf_counter() - started:.1f}s。", flush=True)


if __name__ == "__main__":
    main()
