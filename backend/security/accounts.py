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
              display_name TEXT, created_at TEXT NOT NULL,
              account_status TEXT NOT NULL DEFAULT 'active',
              traffic_cohort TEXT NOT NULL DEFAULT 'unverified',
              updated_at TEXT NOT NULL DEFAULT '')"""))


def create_account(
    actor_id: str,
    username: str,
    password: str,
    role: str,
    display_name: str | None = None,
    *,
    traffic_cohort: str = "unverified",
) -> None:
    if role not in {"student", "teacher", "admin"}:
        raise ValueError("invalid account role")
    if traffic_cohort not in {"demo", "unverified", "verified", "operator"}:
        raise ValueError("invalid traffic cohort")
    _init_accounts_table()
    created_at = now_iso()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO accounts (
                actor_id, username, password_hash, role, display_name, created_at,
                account_status, traffic_cohort, updated_at
            ) VALUES (
                :actor_id, :username, :pw_hash, :role, :display_name, :created_at,
                'active', :traffic_cohort, :updated_at
            )"""),
            {"actor_id": actor_id, "username": username, "pw_hash": hash_password(password),
             "role": role, "display_name": display_name, "created_at": created_at,
             "traffic_cohort": traffic_cohort, "updated_at": created_at},
        )


def authenticate(username: str, password: str) -> dict | None:
    _init_accounts_table()
    with get_connection() as conn:
        row = conn.execute(text("SELECT * FROM accounts WHERE username = :username"), {"username": username}).mappings().fetchone()
    if row and row.get("account_status", "active") == "active" and verify_password(password, row["password_hash"]):
        return {
            "actor_id": row["actor_id"],
            "role": row["role"],
            "display_name": row["display_name"],
            "account_status": row.get("account_status", "active"),
            "traffic_cohort": row.get("traffic_cohort", "unverified"),
        }
    return None


def get_account(actor_id: str) -> dict | None:
    _init_accounts_table()
    with get_connection() as conn:
        row = conn.execute(text("""SELECT actor_id, username, role, display_name,
            account_status, traffic_cohort, created_at, updated_at
            FROM accounts WHERE actor_id=:actor_id"""), {"actor_id": actor_id}).mappings().fetchone()
    return dict(row) if row else None


def set_account_cohort(actor_id: str, traffic_cohort: str) -> bool:
    if traffic_cohort not in {"demo", "unverified", "verified", "operator"}:
        raise ValueError("invalid traffic cohort")
    _init_accounts_table()
    with get_connection() as conn:
        result = conn.execute(text("""UPDATE accounts SET traffic_cohort=:traffic_cohort,
            updated_at=:updated_at WHERE actor_id=:actor_id"""), {
            "traffic_cohort": traffic_cohort,
            "updated_at": now_iso(),
            "actor_id": actor_id,
        })
    return bool(result.rowcount)


def trusted_rollout_cohort_status() -> dict[str, int | bool]:
    _init_accounts_table()
    with get_connection() as conn:
        verified = int(conn.execute(text("""SELECT COUNT(*) FROM accounts
            WHERE account_status='active' AND traffic_cohort='verified'""")).scalar_one())
    return {"ready": verified > 0, "verified_actor_count": verified}


def list_students() -> list[dict]:
    _init_accounts_table()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT actor_id, display_name FROM accounts WHERE role='student' ORDER BY actor_id")
        ).mappings().fetchall()
    return [dict(r) for r in rows]
