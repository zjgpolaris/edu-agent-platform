from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-startup-migration-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(temp_dir.name) / "startup.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DIRECT_URL", None)

from start_backend import REQUIRED_REVISION, run_migrations


def main() -> None:
    first = run_migrations()
    assert first["status"] == "pass"
    assert first["from_revision"] is None
    assert first["to_revision"] == REQUIRED_REVISION
    assert first["no_op"] is False
    second = run_migrations()
    assert second["status"] == "pass"
    assert second["from_revision"] == REQUIRED_REVISION
    assert second["to_revision"] == REQUIRED_REVISION
    assert second["no_op"] is True
    print("backend_startup_migration_smoke=PASS")


if __name__ == "__main__":
    main()
