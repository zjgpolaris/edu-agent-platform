"""Shared real-database reflection regression (CI PostgreSQL and local SQLite)."""
import json
from contextlib import contextmanager
from time import perf_counter
from unittest.mock import patch

from sqlalchemy import event, inspect, text
from agent_runtime import readiness


def check_reflection(conn, *, expect_fewer: bool):
    @contextmanager
    def borrowed():
        yield conn

    statements = []
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(conn, "before_cursor_execute", count)
    try:
        started = perf_counter()
        tables = set(inspect(conn).get_table_names())
        for table in ("learning_events", "autotutor_sessions", "accounts", "agent_rollout_observations", "weakpoints"):
            if table in tables:
                inspect(conn).get_columns(table)
        conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        baseline_ms = (perf_counter() - started) * 1000
        baseline_count = len(statements)
        statements.clear()
        started = perf_counter()
        with patch.object(readiness, "get_connection", borrowed):
            result = readiness.runtime_schema_readiness()
        optimized_ms = (perf_counter() - started) * 1000
        optimized_count = len(statements)
        assert result["schema_ready"], result
        if expect_fewer:
            assert optimized_count < baseline_count, (baseline_count, optimized_count)
    finally:
        event.remove(conn, "before_cursor_execute", count)

    with patch.object(readiness, "get_connection", borrowed):
        for mutation, expected in (
            ("ALTER TABLE weakpoints RENAME COLUMN correct_streak TO missing_correct_streak", "missing_columns"),
            ("ALTER TABLE autotutor_sessions RENAME COLUMN last_request_hash TO missing_request_hash", "missing_columns"),
            ("ALTER TABLE agent_checkpoints RENAME TO missing_checkpoints", "missing_tables"),
            ("UPDATE alembic_version SET version_num='016'", "revision"),
        ):
            savepoint = conn.begin_nested()
            try:
                conn.execute(text(mutation))
                result = readiness.runtime_schema_readiness()
                assert not result["schema_ready"], result
                if expected != "revision":
                    assert result[expected], result
            finally:
                savepoint.rollback()
        with patch.object(readiness, "sa_inspect", side_effect=RuntimeError("private DSN")):
            unavailable = readiness.runtime_schema_readiness()
            assert not unavailable["schema_ready"] and "private" not in str(unavailable)
        assert readiness.runtime_schema_readiness()["schema_ready"]
    print(json.dumps({"schema_reflection_benchmark": conn.dialect.name,
                      "baseline_queries": baseline_count, "optimized_queries": optimized_count,
                      "baseline_ms": round(baseline_ms, 3), "optimized_ms": round(optimized_ms, 3)}))
