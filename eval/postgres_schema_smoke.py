from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

database_url = os.getenv("DATABASE_URL", "")
if not database_url.startswith(("postgresql://", "postgres://")):
    raise SystemExit("postgres_schema_smoke requires a PostgreSQL DATABASE_URL")

from agent_runtime.readiness import RUNTIME_SCHEMA_HEAD, runtime_schema_readiness
from db.engine import get_connection


def main() -> None:
    with get_connection() as conn:
        assert conn.dialect.name == "postgresql"
        tables = set(sa_inspect(conn).get_table_names())
        assert {"agent_rollout_observations", "agent_release_evidence", "agent_runs", "review_mastery_state"} <= tables
        version = str(conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one())
        assert version == RUNTIME_SCHEMA_HEAD, (version, RUNTIME_SCHEMA_HEAD)
        pgvector = conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar()
        assert pgvector == "vector"
    readiness = runtime_schema_readiness()
    assert readiness["schema_ready"] is True, readiness
    print("postgres_schema_smoke=PASS")


if __name__ == "__main__":
    main()
