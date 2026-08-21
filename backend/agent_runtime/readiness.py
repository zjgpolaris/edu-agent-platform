from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection

RUNTIME_SCHEMA_HEAD = "008"
RUNTIME_TABLES = {
    "autotutor_sessions",
    "agent_runs",
    "agent_run_events",
    "agent_run_artifacts",
    "agent_checkpoints",
    "agent_side_effects",
}


def runtime_schema_readiness() -> dict[str, Any]:
    """Read-only deployment gate; never bootstraps missing schema."""
    try:
        with get_connection() as conn:
            dialect = str(conn.dialect.name)
            tables = set(sa_inspect(conn).get_table_names())
            missing = sorted(RUNTIME_TABLES - tables)
            alembic_version = None
            if "alembic_version" in tables:
                alembic_version = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
    except Exception as exc:
        return {
            "status": "unavailable",
            "schema_ready": False,
            "required_alembic_version": RUNTIME_SCHEMA_HEAD,
            "error_type": exc.__class__.__name__,
        }
    ready = not missing and str(alembic_version or "") == RUNTIME_SCHEMA_HEAD
    return {
        "status": "ready" if ready else "not_ready",
        "schema_ready": ready,
        "database_dialect": dialect,
        "required_alembic_version": RUNTIME_SCHEMA_HEAD,
        "alembic_version": alembic_version,
        "missing_tables": missing,
    }
