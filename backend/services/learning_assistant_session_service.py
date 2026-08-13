"""Persistent short-term conversations for the free-question learning assistant."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso

MAX_CONTEXT_MESSAGES = 12
_SAFE_TOOL_METADATA = {"risk_level", "side_effect", "required_role", "source_count", "duration_ms", "degraded"}


def ensure_tables() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS assistant_sessions (
            session_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            title TEXT,
            status TEXT NOT NULL,
            source_feature TEXT NOT NULL,
            source_session_id TEXT,
            context_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS assistant_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            intent TEXT,
            trace_id TEXT,
            tool_results_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_sessions_student_updated ON assistant_sessions(student_id, updated_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_sessions_source ON assistant_sessions(source_feature, source_session_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assistant_messages_session_created ON assistant_messages(session_id, created_at)"))


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "student_id": row["student_id"],
        "title": row.get("title"),
        "status": row["status"],
        "source_feature": row["source_feature"],
        "source_session_id": row.get("source_session_id"),
        "context": _loads(row.get("context_json"), {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _safe_tool_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in results[:8]:
        error = item.get("error") or None
        metadata = item.get("metadata") or {}
        data = item.get("data") or {}
        summary: dict[str, Any] = {
            "tool_name": item.get("tool_name"),
            "ok": bool(item.get("ok")),
            "error": {"code": error.get("code"), "message": str(error.get("message") or "")[:240]} if error else None,
            "metadata": {key: metadata.get(key) for key in _SAFE_TOOL_METADATA if metadata.get(key) is not None},
        }
        if isinstance(data.get("sources"), list):
            summary["source_count"] = len(data["sources"])
        if isinstance(data.get("recommendations"), list):
            summary["recommendation_count"] = len(data["recommendations"])
        if isinstance(data.get("quiz"), dict):
            summary["question_count"] = len(data["quiz"].get("questions") or [])
        safe.append(summary)
    return safe


def create_session(
    student_id: str,
    *,
    source_feature: str = "standalone",
    source_session_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_tables()
    now = now_iso()
    session_id = f"la_{uuid4().hex[:16]}"
    with get_connection() as conn:
        conn.execute(text("""INSERT INTO assistant_sessions (
            session_id, student_id, title, status, source_feature, source_session_id,
            context_json, created_at, updated_at
        ) VALUES (
            :session_id, :student_id, NULL, 'active', :source_feature,
            :source_session_id, :context_json, :created_at, :updated_at
        )"""), {
            "session_id": session_id,
            "student_id": student_id,
            "source_feature": source_feature,
            "source_session_id": source_session_id,
            "context_json": json.dumps(context or {}, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        })
    return get_session(session_id)


def get_session(session_id: str) -> dict[str, Any]:
    ensure_tables()
    with get_connection() as conn:
        row = conn.execute(text("SELECT * FROM assistant_sessions WHERE session_id=:session_id"), {"session_id": session_id}).mappings().first()
    if not row:
        raise LookupError("learning assistant session not found")
    return _session(dict(row))


def get_latest_session(student_id: str) -> dict[str, Any]:
    ensure_tables()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT * FROM assistant_sessions
            WHERE student_id=:student_id AND status='active'
            ORDER BY updated_at DESC LIMIT 1"""), {"student_id": student_id}).mappings().first()
    if not row:
        raise LookupError("learning assistant session not found")
    session = _session(dict(row))
    session["messages"] = list_messages(session["session_id"], limit=MAX_CONTEXT_MESSAGES)
    return session


def get_active_source_session(student_id: str, source_feature: str, source_session_id: str) -> dict[str, Any] | None:
    """Return the active handoff conversation for one trusted source, if it exists."""
    ensure_tables()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT * FROM assistant_sessions
            WHERE student_id=:student_id AND source_feature=:source_feature
              AND source_session_id=:source_session_id AND status='active'
            ORDER BY updated_at DESC LIMIT 1"""), {
            "student_id": student_id,
            "source_feature": source_feature,
            "source_session_id": source_session_id,
        }).mappings().first()
    if not row:
        return None
    session = _session(dict(row))
    session["messages"] = list_messages(session["session_id"], limit=MAX_CONTEXT_MESSAGES)
    return session


def list_sessions(student_id: str, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List a student's conversations without loading full message bodies."""
    ensure_tables()
    limit = max(1, min(int(limit), 100))
    where_status = " AND s.status=:status" if status in {"active", "archived"} else ""
    params: dict[str, Any] = {"student_id": student_id, "limit": limit}
    if where_status:
        params["status"] = status
    with get_connection() as conn:
        rows = conn.execute(text(f"""SELECT s.*,
            (SELECT COUNT(*) FROM assistant_messages m WHERE m.session_id=s.session_id) AS message_count,
            (SELECT m.content FROM assistant_messages m WHERE m.session_id=s.session_id
                ORDER BY m.created_at DESC LIMIT 1) AS last_message
            FROM assistant_sessions s
            WHERE s.student_id=:student_id{where_status}
            ORDER BY s.updated_at DESC LIMIT :limit"""), params).mappings().all()
    return [{
        **_session(dict(row)),
        "message_count": int(row.get("message_count") or 0),
        "last_message": str(row.get("last_message") or "")[:120] or None,
    } for row in rows]


def update_session(session_id: str, *, title: str | None = None, status: str | None = None) -> dict[str, Any]:
    session = get_session(session_id)
    if status is not None and status not in {"active", "archived"}:
        raise ValueError("invalid assistant session status")
    next_title = session.get("title") if title is None else title.strip()[:80]
    if title is not None and not next_title:
        raise ValueError("assistant session title is empty")
    next_status = status or session["status"]
    with get_connection() as conn:
        conn.execute(text("""UPDATE assistant_sessions
            SET title=:title, status=:status, updated_at=:updated_at
            WHERE session_id=:session_id"""), {
            "title": next_title,
            "status": next_status,
            "updated_at": now_iso(),
            "session_id": session_id,
        })
    return get_session(session_id)


def update_textbook_context(session_id: str, textbook: dict[str, Any] | None) -> dict[str, Any]:
    session = get_session(session_id)
    if session["source_feature"] == "auto_tutor":
        raise ValueError("AutoTutor 来源会话不能附加第二教材上下文")
    context = dict(session.get("context") or {})
    if textbook is None:
        context.pop("textbook", None)
    else:
        context["textbook"] = {
            key: textbook[key]
            for key in ("book_id", "lesson_id", "grade", "book", "lesson_title")
            if textbook.get(key) is not None
        }
    with get_connection() as conn:
        conn.execute(text("""UPDATE assistant_sessions
            SET context_json=:context_json, updated_at=:updated_at
            WHERE session_id=:session_id"""), {
            "context_json": json.dumps(context, ensure_ascii=False),
            "updated_at": now_iso(),
            "session_id": session_id,
        })
    return get_session(session_id)


def prepare_regeneration(session_id: str, assistant_message_id: str) -> str:
    """Validate the latest assistant answer and return its preceding user prompt."""
    get_session(session_id)
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT message_id, role, content FROM assistant_messages
            WHERE session_id=:session_id ORDER BY created_at DESC LIMIT 2"""), {
            "session_id": session_id,
        }).mappings().all()
        if len(rows) < 2 or rows[0]["message_id"] != assistant_message_id or rows[0]["role"] != "assistant" or rows[1]["role"] != "user":
            raise ValueError("只能重新生成当前会话的最后一条回答")
    return str(rows[1]["content"])


def replace_assistant_message(
    session_id: str,
    message_id: str,
    content: str,
    *,
    intent: str | None = None,
    trace_id: str | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically replace a validated assistant answer only after regeneration succeeds."""
    content = content.strip()[:2000]
    if not content:
        raise ValueError("assistant message content is empty")
    with get_connection() as conn:
        row = conn.execute(text("""SELECT role FROM assistant_messages
            WHERE session_id=:session_id AND message_id=:message_id"""), {
            "session_id": session_id,
            "message_id": message_id,
        }).mappings().first()
        if not row or row["role"] != "assistant":
            raise LookupError("learning assistant message not found")
        conn.execute(text("""UPDATE assistant_messages SET
            content=:content, intent=:intent, trace_id=:trace_id,
            tool_results_json=:tool_results_json, metadata_json=:metadata_json
            WHERE session_id=:session_id AND message_id=:message_id"""), {
            "content": content,
            "intent": intent,
            "trace_id": trace_id,
            "tool_results_json": json.dumps(_safe_tool_results(tool_results or []), ensure_ascii=False),
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            "session_id": session_id,
            "message_id": message_id,
        })
        conn.execute(text("UPDATE assistant_sessions SET updated_at=:updated_at WHERE session_id=:session_id"), {
            "updated_at": now_iso(),
            "session_id": session_id,
        })
    return next(item for item in list_messages(session_id, limit=MAX_CONTEXT_MESSAGES) if item["message_id"] == message_id)


def validate_last_user_message(session_id: str, content: str) -> None:
    """Ensure an interrupted request can retry without duplicating its stored user turn."""
    get_session(session_id)
    with get_connection() as conn:
        row = conn.execute(text("""SELECT role, content FROM assistant_messages
            WHERE session_id=:session_id ORDER BY created_at DESC LIMIT 1"""), {
            "session_id": session_id,
        }).mappings().first()
    if not row or row["role"] != "user" or str(row["content"]).strip() != content.strip():
        raise ValueError("当前会话没有可重试的中断问题")


def list_messages(session_id: str, *, limit: int = MAX_CONTEXT_MESSAGES) -> list[dict[str, Any]]:
    ensure_tables()
    limit = max(1, min(int(limit), 100))
    with get_connection() as conn:
        rows = conn.execute(text("""SELECT * FROM (
            SELECT * FROM assistant_messages WHERE session_id=:session_id
            ORDER BY created_at DESC LIMIT :limit
        ) recent ORDER BY created_at ASC"""), {"session_id": session_id, "limit": limit}).mappings().all()
    return [{
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "intent": row.get("intent"),
        "trace_id": row.get("trace_id"),
        "tool_results": _loads(row.get("tool_results_json"), []),
        "metadata": _loads(row.get("metadata_json"), {}),
        "created_at": row["created_at"],
    } for row in rows]


def append_message(
    session_id: str,
    role: str,
    content: str,
    *,
    intent: str | None = None,
    trace_id: str | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if role not in {"user", "assistant", "system_context"}:
        raise ValueError("invalid assistant message role")
    session = get_session(session_id)
    content = content.strip()[:2000]
    if not content:
        raise ValueError("assistant message content is empty")
    now = now_iso()
    message_id = f"lam_{uuid4().hex[:16]}"
    title = content[:40] if role == "user" and not session.get("title") else session.get("title")
    with get_connection() as conn:
        conn.execute(text("""INSERT INTO assistant_messages (
            message_id, session_id, role, content, intent, trace_id,
            tool_results_json, metadata_json, created_at
        ) VALUES (
            :message_id, :session_id, :role, :content, :intent, :trace_id,
            :tool_results_json, :metadata_json, :created_at
        )"""), {
            "message_id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "intent": intent,
            "trace_id": trace_id,
            "tool_results_json": json.dumps(_safe_tool_results(tool_results or []), ensure_ascii=False),
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            "created_at": now,
        })
        conn.execute(text("UPDATE assistant_sessions SET title=:title, updated_at=:updated_at WHERE session_id=:session_id"), {
            "title": title,
            "updated_at": now,
            "session_id": session_id,
        })
    return list_messages(session_id, limit=1)[0]


def set_message_feedback(session_id: str, message_id: str, feedback: str) -> dict[str, Any]:
    """Persist one immutable feedback choice on an assistant answer."""
    if feedback not in {"resolved", "unresolved"}:
        raise ValueError("invalid learning assistant feedback")
    ensure_tables()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT * FROM assistant_messages
            WHERE session_id=:session_id AND message_id=:message_id"""), {
            "session_id": session_id,
            "message_id": message_id,
        }).mappings().first()
        if not row:
            raise LookupError("learning assistant message not found")
        if row["role"] != "assistant":
            raise ValueError("feedback is only supported for assistant messages")
        metadata = _loads(row.get("metadata_json"), {})
        existing = metadata.get("feedback")
        if existing:
            if existing != feedback:
                raise ValueError("learning assistant feedback already recorded")
            return {
                "message_id": message_id,
                "session_id": session_id,
                "feedback": existing,
                "changed": False,
                "history_messages": int(metadata.get("history_messages") or 0),
            }
        metadata["feedback"] = feedback
        metadata["feedback_at"] = now_iso()
        conn.execute(text("""UPDATE assistant_messages SET metadata_json=:metadata_json
            WHERE session_id=:session_id AND message_id=:message_id"""), {
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "session_id": session_id,
            "message_id": message_id,
        })
    return {
        "message_id": message_id,
        "session_id": session_id,
        "feedback": feedback,
        "changed": True,
        "history_messages": int(metadata.get("history_messages") or 0),
    }
