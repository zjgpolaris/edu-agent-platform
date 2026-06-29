from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-weakpoints-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

import sys
sys.path.insert(0, str(ROOT / "backend"))

from services.weakpoint_service import clear_stale_weakpoints, clear_weakpoints, get_weakpoints, record_weakpoint


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def record_and_retrieve() -> None:
    record_weakpoint("smoke-a", "鸦片战争", "homework_grading")
    record_weakpoint("smoke-a", "洋务运动", "game")
    points = get_weakpoints("smoke-a")
    tags = [p["knowledge_tag"] for p in points]
    assert "鸦片战争" in tags
    assert "洋务运动" in tags


def wrong_count_increments() -> None:
    record_weakpoint("smoke-b", "辛亥革命", "game")
    record_weakpoint("smoke-b", "辛亥革命", "game")
    record_weakpoint("smoke-b", "辛亥革命", "homework_grading")
    points = get_weakpoints("smoke-b")
    entry = next(p for p in points if p["knowledge_tag"] == "辛亥革命")
    assert entry["wrong_count"] == 3, f"expected 3, got {entry['wrong_count']}"


def students_are_isolated() -> None:
    record_weakpoint("smoke-iso-a", "秦始皇", "game")
    points_b = get_weakpoints("smoke-iso-b")
    assert all(p["knowledge_tag"] != "秦始皇" for p in points_b)


def clear_removes_entries() -> None:
    record_weakpoint("smoke-c", "汉武帝", "game")
    clear_weakpoints("smoke-c")
    assert get_weakpoints("smoke-c") == []


def stale_cleanup_removes_old() -> None:
    import time, sqlite3
    record_weakpoint("smoke-d", "隋朝灭亡", "game")
    # backdate entry to 100 days ago
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 100 * 86400))
    import sqlite3
    with sqlite3.connect(str(_DB)) as conn:
        conn.execute("UPDATE weakpoints SET last_wrong_at = ? WHERE student_id = 'smoke-d'", (cutoff,))
    deleted = clear_stale_weakpoints(days=90)
    assert deleted >= 1
    assert get_weakpoints("smoke-d") == []


def main() -> None:
    cases = [
        ("record_and_retrieve", record_and_retrieve),
        ("wrong_count_increments", wrong_count_increments),
        ("students_are_isolated", students_are_isolated),
        ("clear_removes_entries", clear_removes_entries),
        ("stale_cleanup_removes_old", stale_cleanup_removes_old),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"weakpoints_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
