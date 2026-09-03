"""Migration 017 upgrades legacy observations and cleanly downgrades to 016."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-traffic-migration-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(temp_dir.name) / "migration.sqlite3")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402


def main() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(config, "016")
    engine = create_engine(f"sqlite:///{os.environ['EDU_AGENT_DB_PATH']}")
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO agent_rollout_observations (
            observation_id, agent_type, config_version, runtime_mode, deployed_commit,
            environment, status, latency_ms, trace_id, data_scope, created_at,
            traffic_cohort, rollout_eligible, eligibility_reason
        ) VALUES (
            'legacy-observation', 'auto_tutor', 'legacy-config', 'control', :commit,
            'production', 'completed', 10, NULL, 'runtime', '2026-09-03T00:00:00+00:00',
            'verified', 1, 'verified_runtime_actor'
        )"""), {"commit": "a" * 40})
    command.upgrade(config, "017")
    with engine.connect() as conn:
        inspector = inspect(conn)
        assert {"traffic_source", "verification_run_id"} <= {
            column["name"] for column in inspector.get_columns("agent_rollout_observations")
        }
        assert "autotutor_verification_nonces" in inspector.get_table_names()
        row = conn.execute(text("SELECT traffic_source, verification_run_id FROM agent_rollout_observations WHERE observation_id='legacy-observation'" )).one()
        assert tuple(row) == ("organic", None)
    command.downgrade(config, "016")
    with engine.connect() as conn:
        inspector = inspect(conn)
        assert "autotutor_verification_nonces" not in inspector.get_table_names()
        assert "traffic_source" not in {column["name"] for column in inspector.get_columns("agent_rollout_observations")}
        assert conn.execute(text("SELECT COUNT(*) FROM agent_rollout_observations WHERE observation_id='legacy-observation'" )).scalar_one() == 1
    print("autotutor_verification_traffic_migration_smoke=PASS")


if __name__ == "__main__":
    main()
