"""Smoke test: 自适应复习系统"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-review-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from datetime import date

from services.review_service import create_today_session, get_mastery_overview, get_today_session, submit_answer

STUDENT = "smoke-review"
TODAY = date.today().isoformat()


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def no_session_initially() -> None:
    s = get_today_session(STUDENT, TODAY)
    assert s is None, f"expected None, got {s}"


def mastery_overview_empty() -> None:
    o = get_mastery_overview(STUDENT)
    assert "total_tags" in o
    assert "streak_days" in o
    assert "heatmap" in o


def create_empty_session() -> None:
    # No weakpoints for smoke student → 0 tasks, still valid session
    s = create_today_session(STUDENT, TODAY)
    assert s["date"] == TODAY
    assert isinstance(s["tasks"], list)
    assert s["total"] == len(s["tasks"])


def session_cached() -> None:
    create_today_session(STUDENT, TODAY)  # idempotent
    s = get_today_session(STUDENT, TODAY)
    assert s is not None
    assert s["date"] == TODAY


if __name__ == "__main__":
    cases = [
        ("no_session_initially", no_session_initially),
        ("mastery_overview_empty", mastery_overview_empty),
        ("create_empty_session", create_empty_session),
        ("session_cached", session_cached),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"review_system_smoke={passed}/{len(cases)}")
