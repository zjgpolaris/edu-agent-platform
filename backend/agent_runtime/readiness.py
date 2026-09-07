from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection

RUNTIME_SCHEMA_HEAD = "018"
RUNTIME_TABLES = {
    "autotutor_sessions",
    "agent_runs",
    "agent_run_events",
    "agent_run_artifacts",
    "agent_checkpoints",
    "agent_side_effects",
    "agent_rollout_observations",
    "agent_release_evidence",
    "llm_capability_manifests",
    "weakpoint_evidence",
    "weakpoints",
    "autotutor_verification_nonces",
}

_COLUMN_TABLES = {"learning_events", "autotutor_sessions", "accounts", "agent_rollout_observations", "weakpoints"}


def _schema_inventory(conn) -> tuple[set[str], dict[str, set[str]]]:
    if conn.dialect.name == "postgresql":
        # Read names only: SQLAlchemy's full column reflection also fetches
        # domains/enums/types/defaults which this existence gate never uses.
        # Match Inspector's default (visible, non-temp, ordinary/partitioned
        # tables) scope. No cache: every refresh still detects live schema drift.
        rows = conn.execute(text("""SELECT c.relname AS table_name, a.attname AS column_name
            FROM pg_catalog.pg_class AS c
            JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attribute AS a
              ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
             AND c.relname IN ('learning_events', 'autotutor_sessions', 'accounts',
                              'agent_rollout_observations', 'weakpoints')
            WHERE c.relkind IN ('r', 'p') AND c.relpersistence != 't'
              AND pg_catalog.pg_table_is_visible(c.oid) AND n.nspname != 'pg_catalog'
        """)).mappings().all()
        tables: set[str] = set()
        columns: dict[str, set[str]] = {}
        for row in rows:
            name = row["table_name"]
            tables.add(name)
            if name in _COLUMN_TABLES:
                columns.setdefault(name, set())
                if row["column_name"] is not None:
                    columns[name].add(row["column_name"])
        return tables, columns
    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())
    inspected = sorted(tables & _COLUMN_TABLES)
    reflected = inspector.get_multi_columns(filter_names=inspected) if inspected else {}
    return tables, {name: {column["name"] for column in reflected.get((None, name), [])}
                    for name in inspected}


def runtime_schema_readiness() -> dict[str, Any]:
    """Read-only deployment gate; never bootstraps missing schema."""
    try:
        with get_connection() as conn:
            dialect = str(conn.dialect.name)
            tables, columns = _schema_inventory(conn)
            missing = sorted(RUNTIME_TABLES - tables)
            missing_columns: list[str] = []
            if "weakpoints" in tables and "correct_streak" not in columns["weakpoints"]:
                missing_columns.append("weakpoints.correct_streak")
            if "learning_events" not in tables:
                missing.append("learning_events")
            elif "effect_key" not in columns["learning_events"]:
                missing_columns.append("learning_events.effect_key")
            if "autotutor_sessions" in tables:
                session_columns = columns["autotutor_sessions"]
                for column in ("inflight_request_hash", "last_request_hash"):
                    if column not in session_columns:
                        missing_columns.append(f"autotutor_sessions.{column}")
            if "accounts" in tables:
                account_columns = columns["accounts"]
                for column in ("account_status", "traffic_cohort", "updated_at"):
                    if column not in account_columns:
                        missing_columns.append(f"accounts.{column}")
            if "agent_rollout_observations" in tables:
                observation_columns = columns["agent_rollout_observations"]
                for column in (
                    "traffic_cohort", "rollout_eligible", "eligibility_reason",
                    "selected_executor", "transition_kind", "comparator_matched",
                    "fallback_reason", "provider_latency_ms", "executor_latency_ms",
                    "comparator_latency_ms", "observation_external_calls", "effect_intent_count",
                    "assigned_executor", "transition_id", "observation_schema_version",
                    "outcome_schema_version", "commit_status",
                    "assignment_reason", "admission_status", "admission_reason", "admission_checked_at",
                    "traffic_source", "verification_run_id",
                ):
                    if column not in observation_columns:
                        missing_columns.append(f"agent_rollout_observations.{column}")
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
    ready = not missing and not missing_columns and str(alembic_version or "") == RUNTIME_SCHEMA_HEAD
    return {
        "status": "ready" if ready else "not_ready",
        "schema_ready": ready,
        "database_dialect": dialect,
        "required_alembic_version": RUNTIME_SCHEMA_HEAD,
        "alembic_version": alembic_version,
        "missing_tables": missing,
        "missing_columns": missing_columns,
    }
