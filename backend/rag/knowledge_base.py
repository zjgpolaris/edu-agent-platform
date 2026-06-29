"""RAG 知识库 — 历史史料 & 古诗文典籍

生产形态：Embedding 走 DashScope/百炼 兼容 API（复用 LLM 的 BAILIAN_API_KEY），
向量库走 Postgres + pgvector（复用 DATABASE_URL）。本地若 DATABASE_URL 仍是 sqlite，
向量检索会优雅降级为空（调用方均有兜底）；本地要用 RAG 请把 DATABASE_URL 指向
带 pgvector 的 Postgres（可直接用 Supabase）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text as sa_text

from db.engine import engine
from tracing import end_span, start_span, truncate_text

MetadataValue: TypeAlias = str | int | float | bool
MetadataFilter: TypeAlias = dict[str, MetadataValue | list[MetadataValue]]
MetadataHints: TypeAlias = dict[str, str | list[str]]
SearchMode: TypeAlias = Literal["vector", "keyword", "hybrid"]


class ScoredDocument(TypedDict, total=False):
    document: Document
    score: float
    source_mode: str
    rank: int
    vector_rank: int | None
    vector_rank_score: float
    keyword_score: float
    retrieval_score: float
    rerank_score: float | None
    final_score: float

_EMBED_MODEL: "DashScopeEmbeddings | None" = None

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-v3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
_EMBED_BASE_URL = (os.getenv("BAILIAN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
_EMBED_BATCH = int(os.getenv("EMBED_BATCH", "10"))


class DashScopeEmbeddings:
    """OpenAI 兼容的 DashScope/百炼 文本向量客户端（复用 LLM 的 BAILIAN_API_KEY）。

    暴露 LangChain Embeddings 同名方法 embed_documents / embed_query，
    无需本地 BGE 模型与 GPU/大内存。
    """

    def __init__(self, model: str = EMBED_MODEL, dimensions: int = EMBED_DIM):
        self.model = model
        self.dimensions = dimensions

    def _api_key(self) -> str:
        key = os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError(
                "BAILIAN_API_KEY (or DASHSCOPE_API_KEY) is not set; "
                "cannot call the embedding API for RAG retrieval."
            )
        return key

    def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        body = json.dumps({
            "model": self.model,
            "input": inputs,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"{_EMBED_BASE_URL}/embeddings",
                    data=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key()}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                rows = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
                return [row["embedding"] for row in rows]
            except urllib.error.HTTPError as exc:
                try:
                    error_body = exc.read().decode("utf-8")[:1000]
                except Exception:
                    error_body = ""
                last_error = RuntimeError(f"HTTP {exc.code}: {error_body}")
                time.sleep(1.5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"embedding API failed after retries: {last_error}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH):
            out.extend(self._embed_batch_resilient(texts[i:i + _EMBED_BATCH]))
        return out

    def _embed_batch_resilient(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._embed_batch(texts)
        except Exception as exc:
            reason = str(exc)
            if "Arrearage" in reason or "Access denied" in reason:
                raise RuntimeError(f"embedding API is not available: {exc}") from exc
            if len(texts) <= 1:
                preview = texts[0][:120].replace("\n", " ") if texts else ""
                raise RuntimeError(f"embedding failed for single text: {exc}; preview={preview}") from exc
            mid = len(texts) // 2
            return self._embed_batch_resilient(texts[:mid]) + self._embed_batch_resilient(texts[mid:])

    def embed_query(self, text_in: str) -> list[float]:
        return self._embed_batch([text_in])[0]


def get_embed_model() -> "DashScopeEmbeddings":
    """Lazily build the embedding client (no local model needed)."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = DashScopeEmbeddings()
    return _EMBED_MODEL

# DashScope 向量无需 BGE 查询前缀；保留常量为空串，兼容历史调用点（vector_search / materials）。
BGE_QUERY_PREFIX = ""
RAG_TABLE = "rag_documents"

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["。", "；", "\n\n", "\n"],
)


def _vec_literal(vec: list[float]) -> str:
    # pgvector 文本输入格式：[0.1,0.2,...]
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def _row_to_document(content: str, metadata_json: str | dict | None) -> Document:
    if isinstance(metadata_json, dict):
        metadata = metadata_json
    else:
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except (TypeError, ValueError):
            metadata = {}
    return Document(page_content=content or "", metadata=metadata or {})


class PgVectorStore:
    """Chroma 兼容的最小向量库，后端为 Postgres + pgvector。

    只实现检索层与 materials 实际用到的方法：similarity_search /
    similarity_search_with_relevance_scores / get / add_documents / delete /
    delete_collection。其余 Chroma API 未实现。
    """

    def __init__(self, collection: str):
        self.collection = collection

    # --- 读 ---
    def similarity_search(self, query: str, k: int = 5, filter: dict | None = None) -> list[Document]:
        return [doc for doc, _ in self._search_scored(query, k, filter)]

    def similarity_search_with_relevance_scores(self, query: str, k: int = 5, filter: dict | None = None):
        return self._search_scored(query, k, filter)

    def _search_scored(self, query: str, k: int, filter: dict | None) -> list[tuple[Document, float]]:
        vec = _vec_literal(get_embed_model().embed_query(query))
        where_sql, params = _sql_metadata_filter(filter)
        params.update({"coll": self.collection, "vec": vec, "k": max(int(k), 1)})
        sql = (
            f"SELECT content, metadata, 1 - (embedding <=> CAST(:vec AS vector)) AS score "
            f"FROM {RAG_TABLE} WHERE collection = :coll {where_sql} "
            f"ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k"
        )
        with engine.connect() as conn:
            rows = conn.execute(sa_text(sql), params).fetchall()
        return [(_row_to_document(r[0], r[1]), float(r[2])) for r in rows]

    def get(self, where: dict | None = None, include=None, limit: int = 80) -> dict:
        where_sql, params = _sql_metadata_filter(where)
        params.update({"coll": self.collection, "lim": max(int(limit), 1)})
        sql = (
            f"SELECT id, content, metadata FROM {RAG_TABLE} "
            f"WHERE collection = :coll {where_sql} LIMIT :lim"
        )
        with engine.connect() as conn:
            rows = conn.execute(sa_text(sql), params).fetchall()
        return {
            "ids": [r[0] for r in rows],
            "documents": [r[1] for r in rows],
            "metadatas": [_row_to_document("", r[2]).metadata for r in rows],
        }

    # --- 写 ---
    def add_documents(self, docs: list[Document], ids: list[str]) -> None:
        vectors = get_embed_model().embed_documents([d.page_content for d in docs])
        rows = [
            {
                "id": doc_id,
                "coll": self.collection,
                "content": doc.page_content,
                "metadata": json.dumps(doc.metadata or {}, ensure_ascii=False),
                "embedding": _vec_literal(vec),
            }
            for doc_id, doc, vec in zip(ids, docs, vectors)
        ]
        sql = (
            f"INSERT INTO {RAG_TABLE} (id, collection, content, metadata, embedding) "
            f"VALUES (:id, :coll, :content, CAST(:metadata AS jsonb), CAST(:embedding AS vector)) "
            f"ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, "
            f"metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding"
        )
        with engine.begin() as conn:
            for row in rows:
                conn.execute(sa_text(sql), row)

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        with engine.begin() as conn:
            conn.execute(
                sa_text(f"DELETE FROM {RAG_TABLE} WHERE collection = :coll AND id = ANY(:ids)"),
                {"coll": self.collection, "ids": list(ids)},
            )

    def delete_collection(self) -> None:
        with engine.begin() as conn:
            conn.execute(
                sa_text(f"DELETE FROM {RAG_TABLE} WHERE collection = :coll"),
                {"coll": self.collection},
            )


def build_vectorstore(collection: str, docs_path: Path) -> PgVectorStore:
    raw = json.loads(docs_path.read_text(encoding="utf-8"))
    docs = [
        Document(
            page_content=f"{d['meta'].get('topic', '')}：{d['text']}" if d.get("meta", {}).get("topic") else d["text"],
            metadata={k: v for k, v in d.get("meta", {}).items() if v is not None},
        )
        for d in raw
    ]
    chunks = splitter.split_documents(docs)
    store = PgVectorStore(collection)
    store.delete_collection()
    ids = [f"{collection}-{i}" for i in range(len(chunks))]
    store.add_documents(chunks, ids=ids)
    return store


def load_vectorstore(collection: str) -> PgVectorStore:
    return PgVectorStore(collection)


def add_documents_to_collection(collection: str, docs: list[Document], ids: list[str]) -> int:
    if len(docs) != len(ids):
        raise ValueError("docs 和 ids 数量不一致")
    if not docs:
        return 0
    vs = load_vectorstore(collection)
    vs.add_documents(docs, ids=ids)
    return len(docs)


def delete_documents_by_filter(collection: str, metadata_filter: MetadataFilter) -> int:
    where = build_chroma_where(metadata_filter)
    if not where:
        raise ValueError("删除向量文档必须提供 metadata filter")
    vs = load_vectorstore(collection)
    try:
        payload = vs.get(where=where)
        ids = payload.get("ids") or []
    except Exception:
        ids = []
    if not ids:
        return 0
    vs.delete(ids=ids)
    return len(ids)


def build_chroma_where(metadata_filter: MetadataFilter | None) -> dict | None:
    if not metadata_filter:
        return None

    clauses = []
    for key, value in metadata_filter.items():
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            values = [item for item in value if item not in (None, "")]
            if len(values) == 1:
                clauses.append({key: values[0]})
            elif values:
                clauses.append({key: {"$in": values}})
        else:
            clauses.append({key: value})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


_SAFE_KEY = re.compile(r"^[A-Za-z0-9_]+$")


def _filter_clause_sql(clause: dict, params: dict, idx: int) -> str | None:
    """把单个 {key: val} / {key: {"$in": [...]}} 子句翻成 jsonb 条件。"""
    if not clause:
        return None
    (key, value), = clause.items()
    if not _SAFE_KEY.match(str(key)):
        return None  # 防注入：非法 key 直接忽略
    pname = f"mf_{idx}"
    if isinstance(value, dict) and "$in" in value:
        params[pname] = [str(v) for v in value["$in"]]
        return f"metadata->>'{key}' = ANY(:{pname})"
    params[pname] = str(value)
    return f"metadata->>'{key}' = :{pname}"


def _sql_metadata_filter(where: dict | None) -> tuple[str, dict]:
    """build_chroma_where 的输出 → (SQL 片段, 参数)。片段含前导 ' AND '，无过滤则为空串。"""
    if not where:
        return "", {}
    params: dict = {}
    clauses = where["$and"] if "$and" in where else [where]
    fragments = [frag for i, c in enumerate(clauses) if (frag := _filter_clause_sql(c, params, i))]
    if not fragments:
        return "", {}
    return " AND " + " AND ".join(fragments), params


def vector_search(
    collection: str,
    query: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    fetch_k: int | None = None,
) -> list[Document]:
    vs = load_vectorstore(collection)
    where = build_chroma_where(metadata_filter)
    limit = fetch_k or k
    try:
        if where:
            return vs.similarity_search(query, k=limit, filter=where)
        return vs.similarity_search(query, k=limit)
    except Exception:
        # embedding API / pgvector 不可用（未配 key、未建索引、DB 非 Postgres）时降级：
        # 带过滤的再试一次无过滤；仍失败则返回空，让 keyword 路径独立工作、上层不崩。
        if where:
            try:
                return vs.similarity_search(query, k=limit)
            except Exception:
                return []
        return []


QUERY_STOPWORDS = {
    "什么", "为什么", "怎么", "怎样", "如何", "有什么", "意义", "影响", "重要", "原因",
    "请", "一下", "这个", "那个", "他", "她", "它", "你", "我们", "进行", "主要",
}


def _normalize_compact(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _query_terms(query: str) -> list[str]:
    compact = _normalize_compact(query)
    raw_terms = re.findall(r"[a-z0-9]+|[一-鿿]{2,}", compact)
    terms = [term for term in raw_terms if term not in QUERY_STOPWORDS]

    for stopword in QUERY_STOPWORDS:
        compact = compact.replace(stopword, "")
    if compact:
        terms.insert(0, compact)
    if len(compact) >= 4:
        terms.extend(compact[index : index + 2] for index in range(len(compact) - 1))

    seen = set()
    result = []
    for term in terms:
        if term and term not in seen and term not in QUERY_STOPWORDS:
            seen.add(term)
            result.append(term)
    return result


def _metadata_value_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _metadata_text(doc: Document, keys: tuple[str, ...]) -> str:
    metadata = doc.metadata or {}
    return _normalize_compact(" ".join(_metadata_value_text(metadata.get(key)) for key in keys))


def keyword_score(query: str, doc: Document, metadata_hints: MetadataHints | None = None) -> float:
    content_text = _normalize_compact(doc.page_content)
    exact_text = _metadata_text(doc, ("topic", "lesson", "event", "tags", "entities", "keywords"))
    scope_text = _metadata_text(doc, ("grade", "unit", "source", "type", "page", "period", "book"))
    haystack = content_text + exact_text + scope_text
    if not haystack:
        return 0.0

    score = 0.0
    for term in _query_terms(query):
        weight = min(4.0, max(1.0, len(term) / 2))
        if term and term in exact_text:
            score += weight * 3.0
        elif term and term in content_text:
            score += weight * 1.6
        elif term and term in scope_text:
            score += weight

    if metadata_hints:
        metadata = doc.metadata or {}
        for key, expected in metadata_hints.items():
            values = expected if isinstance(expected, list) else [expected]
            actual = _normalize_compact(str(metadata.get(key, "")))
            for value in values:
                hint = _normalize_compact(str(value))
                if hint and (hint in actual or actual in hint):
                    score += 6.0 if key in {"topic", "lesson"} else 3.0
    return score


def _doc_key(doc: Document) -> tuple[str, str, str, str]:
    metadata = doc.metadata or {}
    return (
        str(metadata.get("source", "")),
        str(metadata.get("page", "")),
        str(metadata.get("topic", "")),
        doc.page_content[:160],
    )


def _keyword_candidates(collection: str, metadata_filter: MetadataFilter | None, limit: int) -> list[Document]:
    vs = load_vectorstore(collection)
    where = build_chroma_where(metadata_filter)
    try:
        payload = vs.get(where=where, include=["documents", "metadatas"], limit=limit) if where else vs.get(
            include=["documents", "metadatas"],
            limit=limit,
        )
    except Exception:
        if not where:
            return []
        try:
            payload = vs.get(include=["documents", "metadatas"], limit=limit)
        except Exception:
            return []

    documents = payload.get("documents") or []
    metadatas = payload.get("metadatas") or [{} for _ in documents]
    return [
        Document(page_content=content or "", metadata=metadata or {})
        for content, metadata in zip(documents, metadatas)
        if content
    ]


def keyword_search(
    collection: str,
    query: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    metadata_hints: MetadataHints | None = None,
    fetch_k: int = 80,
) -> list[Document]:
    candidates = _keyword_candidates(collection, metadata_filter, limit=max(fetch_k, k))
    ranked: dict[tuple[str, str, str, str], tuple[Document, float]] = {}
    for doc in candidates:
        score = keyword_score(query, doc, metadata_hints)
        if score <= 0:
            continue
        key = _doc_key(doc)
        previous = ranked.get(key)
        if not previous or score > previous[1]:
            ranked[key] = (doc, score)
    return [doc for doc, _ in sorted(ranked.values(), key=lambda item: item[1], reverse=True)[:k]]


def rerank_documents(
    query: str,
    docs: list[Document],
    metadata_hints: MetadataHints | None = None,
    vector_ranks: dict[tuple[str, str, str, str], int] | None = None,
    source_modes: dict[tuple[str, str, str, str], str] | None = None,
    fetch_k: int | None = None,
) -> list[ScoredDocument]:
    limit = max(fetch_k or len(docs), 1)
    ranked: dict[tuple[str, str, str, str], ScoredDocument] = {}
    for index, doc in enumerate(docs):
        key = _doc_key(doc)
        vector_index = vector_ranks.get(key) if vector_ranks else None
        vector_rank_score = ((limit - vector_index) / limit) if vector_index is not None else 0.0
        keyword = keyword_score(query, doc, metadata_hints)
        retrieval_score = vector_rank_score + keyword
        if retrieval_score <= 0 and vector_index is None:
            continue
        source_mode = source_modes.get(key, "hybrid") if source_modes else "hybrid"
        previous = ranked.get(key)
        if previous is None or retrieval_score > previous["final_score"]:
            ranked[key] = {
                "document": doc,
                "score": retrieval_score,
                "source_mode": source_mode,
                "vector_rank": vector_index,
                "vector_rank_score": vector_rank_score,
                "keyword_score": keyword,
                "retrieval_score": retrieval_score,
                "rerank_score": None,
                "final_score": retrieval_score,
            }
    ordered = sorted(ranked.values(), key=lambda item: item["final_score"], reverse=True)
    return [{**item, "rank": index + 1} for index, item in enumerate(ordered)]


def apply_cross_encoder_rerank(query: str, scored_docs: list[ScoredDocument], top_k: int = 5) -> list[ScoredDocument]:
    """Apply cross-encoder reranking if available."""
    try:
        from rag.rerank import rerank
        return rerank(query, scored_docs, top_k=top_k)
    except Exception:
        return scored_docs[:top_k]


def _rag_preview(scored_docs: list[ScoredDocument]) -> list[dict[str, object]]:
    previews = []
    for item in scored_docs[:5]:
        doc = item["document"]
        metadata = doc.metadata or {}
        previews.append(
            {
                "topic": metadata.get("topic"),
                "source": metadata.get("source"),
                "grade": metadata.get("grade"),
                "unit": metadata.get("unit"),
                "lesson": metadata.get("lesson"),
                "page": metadata.get("page"),
                "type": metadata.get("type"),
                "score": round(float(item.get("final_score", item.get("score", 0))), 3),
                "retrieval_score": round(float(item.get("retrieval_score", 0)), 3),
                "keyword_score": round(float(item.get("keyword_score", 0)), 3),
                "vector_rank": item.get("vector_rank"),
                "vector_rank_score": round(float(item.get("vector_rank_score", 0)), 3),
                "rerank_score": round(float(item["rerank_score"]), 3) if item.get("rerank_score") is not None else None,
                "source_mode": item["source_mode"],
                "content_preview": truncate_text(doc.page_content, max_chars=240),
            }
        )
    return previews


def _search_with_scores_impl(
    collection: str,
    query: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    mode: SearchMode = "hybrid",
    metadata_hints: MetadataHints | None = None,
    fetch_k: int = 20,
) -> list[ScoredDocument]:
    limit = max(fetch_k, k)
    if mode == "vector":
        docs = vector_search(collection, query, k=k, metadata_filter=metadata_filter, fetch_k=limit)
        source_modes = {_doc_key(doc): "vector" for doc in docs}
        vector_ranks = {_doc_key(doc): index for index, doc in enumerate(docs)}
        return rerank_documents(query, docs, metadata_hints, vector_ranks, source_modes, limit)[:k]

    if mode == "keyword":
        docs = keyword_search(
            collection,
            query,
            k=max(limit, k),
            metadata_filter=metadata_filter,
            metadata_hints=metadata_hints,
            fetch_k=max(limit * 8, 80),
        )
        source_modes = {_doc_key(doc): "keyword" for doc in docs}
        return rerank_documents(query, docs, metadata_hints, source_modes=source_modes, fetch_k=limit)[:k]

    vector_docs = vector_search(collection, query, k=k, metadata_filter=metadata_filter, fetch_k=limit)
    keyword_docs = keyword_search(
        collection,
        query,
        k=max(limit, k),
        metadata_filter=metadata_filter,
        metadata_hints=metadata_hints,
        fetch_k=max(limit * 8, 80),
    )
    global_keyword_docs = [] if metadata_filter is None else keyword_search(
        collection,
        query,
        k=max(limit, k),
        metadata_filter=None,
        metadata_hints=metadata_hints,
        fetch_k=max(limit * 8, 80),
    )

    merged: dict[tuple[str, str, str, str], Document] = {}
    source_modes: dict[tuple[str, str, str, str], str] = {}
    vector_ranks: dict[tuple[str, str, str, str], int] = {}
    for index, doc in enumerate(vector_docs):
        key = _doc_key(doc)
        merged[key] = doc
        source_modes[key] = "vector"
        vector_ranks[key] = index
    for doc in [*keyword_docs, *global_keyword_docs]:
        key = _doc_key(doc)
        if key not in merged:
            merged[key] = doc
            source_modes[key] = "keyword"
        elif source_modes.get(key) == "vector":
            source_modes[key] = "hybrid"

    return rerank_documents(query, list(merged.values()), metadata_hints, vector_ranks, source_modes, limit)[:k]


def search_with_scores(
    collection: str,
    query: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    mode: SearchMode = "hybrid",
    metadata_hints: MetadataHints | None = None,
    fetch_k: int = 20,
) -> list[ScoredDocument]:
    metadata = {
        "collection": collection,
        "query": truncate_text(query, max_chars=500),
        "k": k,
        "mode": mode,
        "metadata_filter": metadata_filter,
        "metadata_hints": metadata_hints,
        "fetch_k": fetch_k,
    }
    span = start_span(name="rag.search", input_data=truncate_text(query, max_chars=500), metadata=metadata)
    try:
        results = _search_with_scores_impl(
            collection,
            query,
            k=k,
            metadata_filter=metadata_filter,
            mode=mode,
            metadata_hints=metadata_hints,
            fetch_k=fetch_k,
        )
        # Apply cross-encoder reranking if available
        results = apply_cross_encoder_rerank(query, results, top_k=k)
        end_span(
            span,
            output=_rag_preview(results),
            metadata={
                **metadata,
                "source_count": len(results),
                "top_score": round(float(results[0].get("final_score", results[0].get("score", 0))), 3) if results else 0,
                "top_mode": results[0]["source_mode"] if results else "",
            },
        )
        return results
    except Exception as exc:
        end_span(span, metadata={**metadata, "source_count": 0}, level="ERROR", status_message=str(exc))
        raise


def hybrid_search(
    collection: str,
    query: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    metadata_hints: MetadataHints | None = None,
    fetch_k: int = 20,
) -> list[Document]:
    return [
        item["document"]
        for item in search_with_scores(
            collection,
            query,
            k=k,
            metadata_filter=metadata_filter,
            mode="hybrid",
            metadata_hints=metadata_hints,
            fetch_k=fetch_k,
        )
    ]


def search(
    collection: str,
    query: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    mode: SearchMode = "hybrid",
    metadata_hints: MetadataHints | None = None,
) -> list[Document]:
    try:
        if mode == "vector":
            docs = vector_search(collection, query, k=k, metadata_filter=metadata_filter)
        elif mode == "keyword":
            docs = keyword_search(collection, query, k=k, metadata_filter=metadata_filter, metadata_hints=metadata_hints)
        else:
            docs = hybrid_search(collection, query, k=k, metadata_filter=metadata_filter, metadata_hints=metadata_hints)
        if docs or not metadata_filter:
            return docs
    except Exception:
        pass
    return vector_search(collection, query, k=k)


class BGERetriever:
    def __init__(
        self,
        collection: str,
        k: int = 5,
        metadata_filter: MetadataFilter | None = None,
        mode: SearchMode = "hybrid",
        metadata_hints: MetadataHints | None = None,
    ):
        self.collection = collection
        self.k = k
        self.metadata_filter = metadata_filter
        self.mode = mode
        self.metadata_hints = metadata_hints

    def invoke(self, query: str):
        return search(
            self.collection,
            query,
            self.k,
            metadata_filter=self.metadata_filter,
            mode=self.mode,
            metadata_hints=self.metadata_hints,
        )


def get_retriever(
    collection: str,
    k: int = 5,
    metadata_filter: MetadataFilter | None = None,
    mode: SearchMode = "hybrid",
    metadata_hints: MetadataHints | None = None,
):
    return BGERetriever(collection, k, metadata_filter=metadata_filter, mode=mode, metadata_hints=metadata_hints)
