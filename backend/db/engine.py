"""SQLAlchemy engine and connection context manager.

Set DATABASE_URL env var to use PostgreSQL:
  DATABASE_URL=postgresql://user:password@localhost:5432/edu_agent

Defaults to SQLite at .data/edu_agent.sqlite3 for local development.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, event as sa_event, text

_DEFAULT_DB = Path(
    os.getenv("EDU_AGENT_DB_PATH")
    or (Path(__file__).resolve().parents[2] / ".data" / "edu_agent.sqlite3")
)
_DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)


def _normalize_database_url(url: str) -> str:
    """Drop Supabase pooler hints that psycopg2 does not accept."""
    if not url.startswith(("postgresql://", "postgres://")):
        return url
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != "pgbouncer"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB}"))

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

if DATABASE_URL.startswith("sqlite"):
    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


@contextmanager
def get_connection():
    """Yield a SQLAlchemy connection inside a transaction."""
    with engine.begin() as conn:
        yield conn
