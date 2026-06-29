"""SQLAlchemy-backed storage for game rounds."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from db.engine import get_connection

ROUND_TTL = timedelta(hours=2)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS game_rounds (
            round_id TEXT PRIMARY KEY, round_type TEXT NOT NULL,
            data TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_game_rounds_type ON game_rounds(round_type)"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS card_game_wrong_records (
            student_key TEXT PRIMARY KEY, card_ids TEXT NOT NULL)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS card_game_reports (
            id TEXT PRIMARY KEY, student_key TEXT NOT NULL, data TEXT NOT NULL)"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_card_game_reports_key ON card_game_reports(student_key)"))


def save_round(round_id: str, round_type: str, record: dict[str, Any]) -> None:
    init_db()
    data = record.copy()
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat()
        data["created_at"] = created_at_str
    else:
        created_at_str = created_at or datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.fromisoformat(created_at_str) + ROUND_TTL).isoformat()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO game_rounds (round_id, round_type, data, created_at, expires_at)
            VALUES (:round_id, :round_type, :data, :created_at, :expires_at)
            ON CONFLICT(round_id) DO UPDATE SET
                data = excluded.data, created_at = excluded.created_at, expires_at = excluded.expires_at"""),
            {"round_id": round_id, "round_type": round_type,
             "data": json.dumps(data, ensure_ascii=False, default=str),
             "created_at": created_at_str, "expires_at": expires_at},
        )


def load_round(round_id: str) -> dict[str, Any] | None:
    init_db()
    cleanup_expired_rounds()
    with get_connection() as conn:
        row = conn.execute(text("SELECT data FROM game_rounds WHERE round_id = :round_id"), {"round_id": round_id}).mappings().fetchone()
    return json.loads(row["data"]) if row else None


def cleanup_expired_rounds() -> None:
    with get_connection() as conn:
        conn.execute(text("DELETE FROM game_rounds WHERE expires_at < :now"), {"now": datetime.now(timezone.utc).isoformat()})


def get_wrong_records(student_key: str) -> list[str]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(text("SELECT card_ids FROM card_game_wrong_records WHERE student_key = :key"), {"key": student_key}).mappings().fetchone()
    return json.loads(row["card_ids"]) if row else []


def save_wrong_records(student_key: str, card_ids: list[str]) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO card_game_wrong_records (student_key, card_ids) VALUES (:key, :ids)
            ON CONFLICT(student_key) DO UPDATE SET card_ids = excluded.card_ids"""),
            {"key": student_key, "ids": json.dumps(card_ids)},
        )


def append_card_game_report(student_key: str, report: dict[str, Any]) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            text("INSERT INTO card_game_reports (id, student_key, data) VALUES (:id, :key, :data)"),
            {"id": uuid4().hex, "key": student_key, "data": json.dumps(report, ensure_ascii=False, default=str)},
        )


def get_card_game_reports(student_key: str) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(text("SELECT data FROM card_game_reports WHERE student_key = :key"), {"key": student_key}).mappings().fetchall()
    return [json.loads(r["data"]) for r in rows]
