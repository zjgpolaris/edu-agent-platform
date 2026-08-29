from __future__ import annotations

import runpy
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_ENV = ROOT / "backend" / "alembic" / "env.py"


def main() -> None:
    events: list[str] = []

    class FakeConnection:
        dialect = types.SimpleNamespace(name="postgresql")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("connection_closed")

        def exec_driver_sql(self, statement: str):
            assert statement.startswith("SET ")
            events.append("set_timeout")

        def commit(self):
            events.append("configuration_committed")

    connection = FakeConnection()

    class FakeEngine:
        def connect(self):
            return connection

    fake_sqlalchemy = types.ModuleType("sqlalchemy")
    fake_sqlalchemy.create_engine = lambda _url: FakeEngine()

    class FakeConfig:
        def set_main_option(self, _key: str, _value: str) -> None:
            return None

    fake_context = types.SimpleNamespace(config=FakeConfig())
    fake_context.is_offline_mode = lambda: False

    def configure(*, connection, target_metadata) -> None:
        assert connection is not None
        assert target_metadata is not None
        assert events == ["set_timeout", "set_timeout", "configuration_committed"]
        events.append("configured")

    @contextmanager
    def begin_transaction():
        assert events[-1] == "configured"
        events.append("migration_transaction_started")
        yield
        events.append("migration_transaction_finished")

    def run_migrations() -> None:
        assert events[-1] == "migration_transaction_started"
        events.append("migrations_run")

    fake_context.configure = configure
    fake_context.begin_transaction = begin_transaction
    fake_context.run_migrations = run_migrations

    fake_alembic = types.ModuleType("alembic")
    fake_alembic.context = fake_context
    fake_db = types.ModuleType("db")
    fake_db_engine = types.ModuleType("db.engine")
    fake_db_engine.DATABASE_URL = "postgresql://migration-smoke"
    fake_db_schema = types.ModuleType("db.schema")
    fake_db_schema.metadata = object()

    with patch.dict(sys.modules, {
        "alembic": fake_alembic,
        "db": fake_db,
        "db.engine": fake_db_engine,
        "db.schema": fake_db_schema,
        "sqlalchemy": fake_sqlalchemy,
    }):
        runpy.run_path(str(ALEMBIC_ENV), run_name="__alembic_transaction_boundary_smoke__")

    assert events == [
        "set_timeout",
        "set_timeout",
        "configuration_committed",
        "configured",
        "migration_transaction_started",
        "migrations_run",
        "migration_transaction_finished",
        "connection_closed",
    ]
    print("alembic_transaction_boundary_smoke=PASS")


if __name__ == "__main__":
    main()
