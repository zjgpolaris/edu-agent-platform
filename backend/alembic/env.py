import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context
from db.engine import DATABASE_URL
from db.schema import metadata

MIGRATION_DATABASE_URL = os.getenv("DIRECT_URL") or DATABASE_URL

config = context.config
config.set_main_option("sqlalchemy.url", MIGRATION_DATABASE_URL.replace("%", "%%"))

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=MIGRATION_DATABASE_URL, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    connectable = create_engine(MIGRATION_DATABASE_URL)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
