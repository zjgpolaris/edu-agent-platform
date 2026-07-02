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

from services.weakpoint_service import (
    clear_stale_weakpoints,
    clear_weakpoints,
    get_weakpoints,
    record_correct_evidence,
    record_weakpoint,
)


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


def mastery_requires_consecutive_correct() -> None:
    # 答对一次不移除（streak=1），连续两次才判定掌握并移除
    record_weakpoint("smoke-m", "文景之治", "game")
    r1 = record_correct_evidence("smoke-m", "文景之治")
    assert r1["removed"] is False and r1["correct_streak"] == 1, r1
    assert any(p["knowledge_tag"] == "文景之治" for p in get_weakpoints("smoke-m"))
    r2 = record_correct_evidence("smoke-m", "文景之治")
    assert r2["removed"] is True, r2
    assert all(p["knowledge_tag"] != "文景之治" for p in get_weakpoints("smoke-m"))


def wrong_resets_streak() -> None:
    # 答对一次后又答错 → streak 归零，需要重新连续答对两次
    record_weakpoint("smoke-n", "贞观之治", "game")
    record_correct_evidence("smoke-n", "贞观之治")  # streak=1
    record_weakpoint("smoke-n", "贞观之治", "game")  # 答错，streak 重置
    entry = next(p for p in get_weakpoints("smoke-n") if p["knowledge_tag"] == "贞观之治")
    assert entry["correct_streak"] == 0, entry
    r = record_correct_evidence("smoke-n", "贞观之治")
    assert r["removed"] is False and r["correct_streak"] == 1, r


def correct_evidence_on_untracked_is_noop() -> None:
    r = record_correct_evidence("smoke-o", "从未错过的知识点")
    assert r == {"removed": False, "reason": "not_tracked"}, r


def main() -> None:
    cases = [
        ("record_and_retrieve", record_and_retrieve),
        ("wrong_count_increments", wrong_count_increments),
        ("students_are_isolated", students_are_isolated),
        ("clear_removes_entries", clear_removes_entries),
        ("stale_cleanup_removes_old", stale_cleanup_removes_old),
        ("mastery_requires_consecutive_correct", mastery_requires_consecutive_correct),
        ("wrong_resets_streak", wrong_resets_streak),
        ("correct_evidence_on_untracked_is_noop", correct_evidence_on_untracked_is_noop),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"weakpoints_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
