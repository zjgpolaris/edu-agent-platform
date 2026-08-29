from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="edu-agent-migration-failure-") as temp_dir:
        # A directory cannot be opened as a SQLite database. Running without
        # --migrate-only proves migration failure exits before uvicorn starts.
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{temp_dir}",
            "PYTHONPATH": str(BACKEND),
            "EDU_AGENT_AUTO_MIGRATE": "true",
        }
        completed = subprocess.run(
            [sys.executable, str(BACKEND / "start_backend.py")],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert completed.returncode != 0, completed.stdout
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stdout or completed.stderr
    payload = json.loads(lines[-1])
    assert payload["status"] == "fail"
    assert payload["failure_stage"] == "preflight"
    assert "Uvicorn running" not in completed.stderr
    print("backend_startup_migration_failure_smoke=PASS")


if __name__ == "__main__":
    main()
