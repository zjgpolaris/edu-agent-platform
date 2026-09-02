from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-readiness-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

from sqlalchemy import text  # noqa: E402
from agent_runtime.event_store import ensure_runtime_tables  # noqa: E402
from agent_runtime.readiness import runtime_schema_readiness  # noqa: E402
from db.engine import get_connection  # noqa: E402
from db.schema import agent_release_evidence, agent_rollout_observations, autotutor_sessions, llm_capability_manifests  # noqa: E402
from student_profile import init_db  # noqa: E402
from services.weakpoint_service import _ensure_table  # noqa: E402


def main() -> None:
    ensure_runtime_tables()
    before = runtime_schema_readiness()
    assert before["schema_ready"] is False
    assert before["alembic_version"] is None

    with get_connection() as conn:
        autotutor_sessions.create(bind=conn, checkfirst=True)
        agent_rollout_observations.create(bind=conn, checkfirst=True)
        agent_release_evidence.create(bind=conn, checkfirst=True)
        llm_capability_manifests.create(bind=conn, checkfirst=True)
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('015')"))
    init_db()
    _ensure_table()

    after = runtime_schema_readiness()
    assert after == {
        "status": "ready",
        "schema_ready": True,
        "database_dialect": "sqlite",
        "required_alembic_version": "015",
        "alembic_version": "015",
        "missing_tables": [],
        "missing_columns": [],
    }
    print("agent_runtime_schema_readiness_smoke=PASS")


if __name__ == "__main__":
    main()
