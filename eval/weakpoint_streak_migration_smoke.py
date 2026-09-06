"""Real 017->018 upgrade preserves old rows and already-existing streak values."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
TEMP = tempfile.TemporaryDirectory(prefix="weakpoint-migration-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(TEMP.name) / "migration.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DIRECT_URL", None)

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def main():
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    command.upgrade(config, "017")
    engine = create_engine(f"sqlite:///{os.environ['EDU_AGENT_DB_PATH']}")
    try:
        with engine.begin() as conn:
            assert "correct_streak" not in {col["name"] for col in inspect(conn).get_columns("weakpoints")}
            conn.execute(text("""INSERT INTO weakpoints (student_id, knowledge_tag, wrong_count, last_wrong_at, source)
                VALUES ('migration-student', 'tag', 3, '2026-09-06', 'auto_tutor')"""))
            before = tuple(conn.execute(text("SELECT * FROM weakpoints")).one())
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "018"
            column = next(col for col in inspect(conn).get_columns("weakpoints") if col["name"] == "correct_streak")
            assert not column["nullable"]
            assert tuple(conn.execute(text("SELECT student_id, knowledge_tag, wrong_count, last_wrong_at, source FROM weakpoints")).one()) == before
            assert conn.execute(text("SELECT correct_streak FROM weakpoints")).scalar_one() == 0
        command.upgrade(config, "head")
        # Simulate an old SQLite/operator repair with existing non-zero values,
        # WITHOUT dropping business data or re-creating the schema from metadata.
        command.stamp(config, "017")
        with engine.begin() as conn:
            conn.execute(text("UPDATE weakpoints SET correct_streak=2"))
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT correct_streak FROM weakpoints")).scalar_one() == 2
        command.downgrade(config, "017")
        with engine.connect() as conn:
            assert "correct_streak" not in {col["name"] for col in inspect(conn).get_columns("weakpoints")}
            assert tuple(conn.execute(text("SELECT * FROM weakpoints")).one()) == before
        command.upgrade(config, "head")
        print("weakpoint_streak_migration_smoke=PASS")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    finally:
        TEMP.cleanup()
