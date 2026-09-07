"""Local SQL contract test; PostgreSQL CI runs the same shared checks natively."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
_temp = tempfile.TemporaryDirectory(prefix="autotutor-hotpath-")
os.environ["DATABASE_URL"] = f"sqlite:///{_temp.name}/hotpath.db"

from db.engine import get_connection
from db.schema import metadata
from autotutor_schema_hotpath_checks import check_schema_hotpath


def main():
    with get_connection() as conn:
        metadata.create_all(conn)
        check_schema_hotpath(conn)
    print("autotutor_schema_hotpath_smoke=PASS")


if __name__ == "__main__":
    main()
