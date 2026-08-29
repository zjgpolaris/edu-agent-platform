#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect as sa_inspect, text

from db.engine import DATABASE_URL

MIGRATION_LOCK_KEY = 4_539_941_140
REQUIRED_REVISION = "011"


def _bounded_milliseconds(name: str, default: int, maximum: int) -> int:
    try:
        return max(1_000, min(int(os.getenv(name, str(default))), maximum))
    except (TypeError, ValueError):
        return default


def migration_database_url() -> str:
    direct_url = os.getenv("DIRECT_URL", "").strip()
    require_direct = os.getenv("EDU_AGENT_REQUIRE_DIRECT_MIGRATION_URL", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if require_direct and not direct_url:
        raise RuntimeError("DIRECT_URL is required for controlled database migration")
    return direct_url or DATABASE_URL.strip()


def current_revision(connection) -> str | None:
    if "alembic_version" not in set(sa_inspect(connection).get_table_names()):
        return None
    return str(connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar() or "") or None


@contextmanager
def migration_lock(database_url: str) -> Iterator[None]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                yield
                return
            wait_ms = _bounded_milliseconds("EDU_AGENT_MIGRATION_LOCK_WAIT_MS", 120_000, 15 * 60_000)
            connection.exec_driver_sql(f"SET statement_timeout = {wait_ms}")
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
    finally:
        engine.dispose()


def _alembic_config() -> Config:
    config_path = Path(__file__).resolve().parent / "alembic.ini"
    return Config(str(config_path))


def _inspect_revision(database_url: str) -> str | None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return current_revision(connection)
    finally:
        engine.dispose()


def run_migrations() -> dict[str, object]:
    started = time.monotonic()
    before = None
    failure_stage = "preflight"
    try:
        database_url = migration_database_url()
        if not database_url:
            raise RuntimeError("migration database URL is missing")
        before = _inspect_revision(database_url)
        failure_stage = "lock"
        with migration_lock(database_url):
            locked_revision = _inspect_revision(database_url)
            failure_stage = "upgrade"
            command.upgrade(_alembic_config(), "head")
            failure_stage = "revision_postcheck"
            after = _inspect_revision(database_url)
            if after != REQUIRED_REVISION:
                raise RuntimeError(f"migration post-check expected {REQUIRED_REVISION}, observed {after or 'none'}")
            from agent_runtime.readiness import runtime_schema_readiness

            failure_stage = "schema_postcheck"
            schema = runtime_schema_readiness()
            if not schema.get("schema_ready"):
                raise RuntimeError(f"migration schema post-check failed: {schema}")
    except Exception as exc:
        payload = {
            "status": "fail",
            "from_revision": before,
            "required_revision": REQUIRED_REVISION,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "failure_stage": failure_stage,
            "error_type": exc.__class__.__name__,
        }
        print(json.dumps(payload, sort_keys=True), flush=True)
        raise
    payload = {
        "status": "pass",
        "from_revision": before,
        "locked_revision": locked_revision,
        "to_revision": after,
        "required_revision": REQUIRED_REVISION,
        "no_op": before == after,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    print(json.dumps(payload, sort_keys=True), flush=True)
    return payload


def serve() -> None:
    port = os.getenv("PORT", "8000").strip() or "8000"
    os.execvp(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", port],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate the database under an advisory lock, then start EduAgent API.")
    parser.add_argument("--migrate-only", action="store_true")
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()
    auto_migrate = os.getenv("EDU_AGENT_AUTO_MIGRATE", "true").strip().lower() in {"1", "true", "yes", "on"}
    if not args.skip_migration and auto_migrate:
        run_migrations()
    if not args.migrate_only:
        serve()


if __name__ == "__main__":
    main()
