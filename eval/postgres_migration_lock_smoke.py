from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
database_url = os.getenv("DATABASE_URL", "")
if not database_url.startswith(("postgresql://", "postgres://")):
    raise SystemExit("postgres_migration_lock_smoke requires a PostgreSQL DATABASE_URL")


def main() -> None:
    command = [sys.executable, str(ROOT / "backend" / "start_backend.py"), "--migrate-only"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
    processes = [subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outputs = [process.communicate(timeout=180) for process in processes]
    for process, (stdout, stderr) in zip(processes, outputs):
        assert process.returncode == 0, stderr or stdout
        assert '"status": "pass"' in stdout, stdout
        assert '"to_revision": "012"' in stdout, stdout
    print("postgres_migration_lock_smoke=PASS")


if __name__ == "__main__":
    main()
