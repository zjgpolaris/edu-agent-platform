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
        assert {"agent_rollout_observations", "agent_release_evidence", "llm_capability_manifests", "agent_runs", "review_mastery_state", "autotutor_verification_nonces"} <= tables
        inspector = sa_inspect(conn)
        account_columns = {column["name"] for column in inspector.get_columns("accounts")}
        observation_columns = {column["name"] for column in inspector.get_columns("agent_rollout_observations")}
        observation_indexes = {index["name"] for index in inspector.get_indexes("agent_rollout_observations")}
        assert {"account_status", "traffic_cohort", "updated_at"} <= account_columns
        assert {
            "traffic_cohort", "rollout_eligible", "eligibility_reason",
            "assigned_executor", "selected_executor", "transition_id",
            "observation_schema_version", "outcome_schema_version", "commit_status",
            "assignment_reason", "admission_status", "admission_reason", "admission_checked_at",
            "traffic_source", "verification_run_id",
        } <= observation_columns
        assert "idx_rollout_observation_eligibility" in observation_indexes
        version = str(conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one())
        assert version == RUNTIME_SCHEMA_HEAD, (version, RUNTIME_SCHEMA_HEAD)
        pgvector = conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar()
        assert pgvector == "vector"
    readiness = runtime_schema_readiness()
    assert readiness["schema_ready"] is True, readiness
    print("postgres_schema_smoke=PASS")


if __name__ == "__main__":
    main()
