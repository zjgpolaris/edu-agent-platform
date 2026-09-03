from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect, text

from db.engine import get_connection

RUNTIME_SCHEMA_HEAD = "017"
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
    "autotutor_verification_nonces",
}


def runtime_schema_readiness() -> dict[str, Any]:
    """Read-only deployment gate; never bootstraps missing schema."""
    try:
        with get_connection() as conn:
            dialect = str(conn.dialect.name)
            tables = set(sa_inspect(conn).get_table_names())
            missing = sorted(RUNTIME_TABLES - tables)
            missing_columns: list[str] = []
            if "learning_events" not in tables:
                missing.append("learning_events")
            elif "effect_key" not in {column["name"] for column in sa_inspect(conn).get_columns("learning_events")}:
                missing_columns.append("learning_events.effect_key")
            if "autotutor_sessions" in tables:
                session_columns = {column["name"] for column in sa_inspect(conn).get_columns("autotutor_sessions")}
                for column in ("inflight_request_hash", "last_request_hash"):
                    if column not in session_columns:
                        missing_columns.append(f"autotutor_sessions.{column}")
            if "accounts" in tables:
                account_columns = {column["name"] for column in sa_inspect(conn).get_columns("accounts")}
                for column in ("account_status", "traffic_cohort", "updated_at"):
                    if column not in account_columns:
                        missing_columns.append(f"accounts.{column}")
            if "agent_rollout_observations" in tables:
                observation_columns = {column["name"] for column in sa_inspect(conn).get_columns("agent_rollout_observations")}
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
