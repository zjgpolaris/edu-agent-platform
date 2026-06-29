from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import text

from db.engine import get_connection
from materials.schema import MaterialPage, MaterialRecord
from security.auth import Actor
from student_profile import _json_dump, _json_load, now_iso

_CLIENT_SESSION_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


class MaterialNotFoundError(LookupError):
    pass


def init_material_store() -> None:
    with get_connection() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS materials (
              material_id TEXT PRIMARY KEY,
              owner_key TEXT NOT NULL,
              title TEXT NOT NULL,
              filename TEXT NOT NULL,
              content_type TEXT NOT NULL,
              source_type TEXT NOT NULL,
              subject TEXT,
              grade TEXT,
              tags_json TEXT NOT NULL,
              text_chars INTEGER NOT NULL,
              page_count INTEGER NOT NULL,
              chunk_count INTEGER NOT NULL,
              ocr_mode TEXT,
              quality_json TEXT,
              warnings_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              expires_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_pages (
              id TEXT PRIMARY KEY,
              material_id TEXT NOT NULL,
              page_number INTEGER NOT NULL,
              source_type TEXT NOT NULL,
              text TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS material_chunks (
              chunk_id TEXT PRIMARY KEY,
              material_id TEXT NOT NULL,
              owner_key TEXT NOT NULL,
              page_number INTEGER NOT NULL,
              text TEXT NOT NULL,
              metadata_json TEXT NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_materials_owner_created ON materials(owner_key, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_material_chunks_material ON material_chunks(material_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_material_chunks_owner_material ON material_chunks(owner_key, material_id)"))


def resolve_owner_key(request: Request, actor: Actor) -> str:
    if actor.actor_id:
        return f"actor:{actor.actor_id}"
    session_id = request.headers.get("x-client-session", "").strip()
    if not _CLIENT_SESSION_RE.match(session_id):
        raise HTTPException(status_code=401, detail="请先登录或刷新页面后重试。")
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return f"anonymous:{digest}"


def new_material_id() -> str:
    return f"mat_{uuid4().hex}"


def _record_from_row(row: Any) -> MaterialRecord:
    return MaterialRecord(
        material_id=row["material_id"],
        title=row["title"],
        filename=row["filename"],
        subject=row["subject"],
        grade=row["grade"],
        source_type=row["source_type"],
        text_chars=row["text_chars"],
        page_count=row["page_count"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def insert_material(
    *,
    owner_key: str,
    material_id: str,
    title: str,
    filename: str,
    content_type: str,
    source_type: str,
    subject: str | None,
    grade: str | None,
    tags: list[str],
    text_chars: int,
    pages: list[MaterialPage],
    chunks: list[dict[str, Any]],
    ocr_mode: str | None,
    quality: dict[str, Any] | None,
    warnings: list[str],
    expires_at: str | None = None,
) -> MaterialRecord:
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute(
            text("""
            INSERT INTO materials (
              material_id, owner_key, title, filename, content_type, source_type, subject, grade,
              tags_json, text_chars, page_count, chunk_count, ocr_mode, quality_json, warnings_json,
              created_at, updated_at, expires_at
            ) VALUES (
              :material_id, :owner_key, :title, :filename, :content_type, :source_type, :subject, :grade,
              :tags_json, :text_chars, :page_count, :chunk_count, :ocr_mode, :quality_json, :warnings_json,
              :created_at, :updated_at, :expires_at
            )
            """),
            {
                "material_id": material_id,
                "owner_key": owner_key,
                "title": title,
                "filename": filename,
                "content_type": content_type,
                "source_type": source_type,
                "subject": subject,
                "grade": grade,
                "tags_json": _json_dump(tags),
                "text_chars": text_chars,
                "page_count": len(pages),
                "chunk_count": len(chunks),
                "ocr_mode": ocr_mode,
                "quality_json": _json_dump(quality) if quality else None,
                "warnings_json": _json_dump(warnings),
                "created_at": timestamp,
                "updated_at": timestamp,
                "expires_at": expires_at,
            },
        )
        conn.execute(
            text("INSERT INTO material_pages (id, material_id, page_number, source_type, text) VALUES (:id, :material_id, :page_number, :source_type, :text)"),
            [
                {"id": uuid4().hex, "material_id": material_id, "page_number": page.page_number, "source_type": page.source_type, "text": page.text}
                for page in pages
            ],
        )
        conn.execute(
            text("INSERT INTO material_chunks (chunk_id, material_id, owner_key, page_number, text, metadata_json) VALUES (:chunk_id, :material_id, :owner_key, :page_number, :text, :metadata_json)"),
            [
                {
                    "chunk_id": chunk["chunk_id"],
                    "material_id": material_id,
                    "owner_key": owner_key,
                    "page_number": int(chunk.get("page_number") or 1),
                    "text": chunk["text"],
                    "metadata_json": _json_dump(chunk.get("metadata") or {}),
                }
                for chunk in chunks
            ],
        )
    return MaterialRecord(
        material_id=material_id,
        title=title,
        filename=filename,
        subject=subject,
        grade=grade,
        source_type=source_type,  # type: ignore[arg-type]
        text_chars=text_chars,
        page_count=len(pages),
        chunk_count=len(chunks),
        created_at=timestamp,
        updated_at=timestamp,
    )


def list_material_records(owner_key: str) -> list[MaterialRecord]:
    init_material_store()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM materials WHERE owner_key = :owner_key ORDER BY created_at DESC"),
            {"owner_key": owner_key},
        ).mappings().fetchall()
    return [_record_from_row(row) for row in rows]


def get_material_row(owner_key: str, material_id: str) -> Any:
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM materials WHERE owner_key = :owner_key AND material_id = :material_id"),
            {"owner_key": owner_key, "material_id": material_id},
        ).mappings().fetchone()
    if row is None:
        raise MaterialNotFoundError("资料不存在或无权访问。")
    return row


def get_material_record(owner_key: str, material_id: str) -> MaterialRecord:
    return _record_from_row(get_material_row(owner_key, material_id))


def get_material_pages(owner_key: str, material_id: str) -> list[MaterialPage]:
    get_material_row(owner_key, material_id)
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT page_number, source_type, text FROM material_pages WHERE material_id = :material_id ORDER BY page_number ASC"),
            {"material_id": material_id},
        ).mappings().fetchall()
    return [MaterialPage(page_number=row["page_number"], source_type=row["source_type"], text=row["text"]) for row in rows]


def get_material_warnings(owner_key: str, material_id: str) -> list[str]:
    row = get_material_row(owner_key, material_id)
    value = _json_load(row["warnings_json"], [])
    return value if isinstance(value, list) else []


def get_material_chunks(owner_key: str, material_id: str) -> list[dict[str, Any]]:
    get_material_row(owner_key, material_id)
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM material_chunks WHERE owner_key = :owner_key AND material_id = :material_id ORDER BY page_number ASC, chunk_id ASC"),
            {"owner_key": owner_key, "material_id": material_id},
        ).mappings().fetchall()
    return [
        {
            "chunk_id": row["chunk_id"],
            "material_id": row["material_id"],
            "owner_key": row["owner_key"],
            "page_number": row["page_number"],
            "text": row["text"],
            "metadata": _json_load(row["metadata_json"], {}),
        }
        for row in rows
    ]


def delete_material_rows(owner_key: str, material_id: str) -> None:
    get_material_row(owner_key, material_id)
    with get_connection() as conn:
        conn.execute(text("DELETE FROM material_chunks WHERE owner_key = :owner_key AND material_id = :material_id"), {"owner_key": owner_key, "material_id": material_id})
        conn.execute(text("DELETE FROM material_pages WHERE material_id = :material_id"), {"material_id": material_id})
        conn.execute(text("DELETE FROM materials WHERE owner_key = :owner_key AND material_id = :material_id"), {"owner_key": owner_key, "material_id": material_id})


def delete_material_rows_if_exists(owner_key: str, material_id: str) -> None:
    with get_connection() as conn:
        conn.execute(text("DELETE FROM material_chunks WHERE owner_key = :owner_key AND material_id = :material_id"), {"owner_key": owner_key, "material_id": material_id})
        conn.execute(text("DELETE FROM material_pages WHERE material_id = :material_id"), {"material_id": material_id})
        conn.execute(text("DELETE FROM materials WHERE owner_key = :owner_key AND material_id = :material_id"), {"owner_key": owner_key, "material_id": material_id})


def list_expired_material_rows() -> list[tuple[str, str]]:
    """Return (owner_key, material_id) for all materials past their expires_at."""
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT owner_key, material_id FROM materials WHERE expires_at IS NOT NULL AND expires_at < :now"),
            {"now": now_iso()},
        ).mappings().fetchall()
    return [(row["owner_key"], row["material_id"]) for row in rows]
