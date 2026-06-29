from __future__ import annotations

from sqlalchemy import text

from db.engine import get_connection
from student_profile import init_db, now_iso
from security.auth import hash_password, verify_password


def _init_accounts_table() -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS accounts (
              actor_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
              display_name TEXT, created_at TEXT NOT NULL)"""))


def create_account(actor_id: str, username: str, password: str, role: str, display_name: str | None = None) -> None:
    _init_accounts_table()
    with get_connection() as conn:
        conn.execute(
            text("INSERT INTO accounts (actor_id, username, password_hash, role, display_name, created_at) VALUES (:actor_id, :username, :pw_hash, :role, :display_name, :created_at)"),
            {"actor_id": actor_id, "username": username, "pw_hash": hash_password(password),
             "role": role, "display_name": display_name, "created_at": now_iso()},
        )


def authenticate(username: str, password: str) -> dict | None:
    _init_accounts_table()
    with get_connection() as conn:
        row = conn.execute(text("SELECT * FROM accounts WHERE username = :username"), {"username": username}).mappings().fetchone()
    if row and verify_password(password, row["password_hash"]):
        return {"actor_id": row["actor_id"], "role": row["role"], "display_name": row["display_name"]}
    return None


def list_students() -> list[dict]:
    _init_accounts_table()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT actor_id, display_name FROM accounts WHERE role='student' ORDER BY actor_id")
        ).mappings().fetchall()
    return [dict(r) for r in rows]
