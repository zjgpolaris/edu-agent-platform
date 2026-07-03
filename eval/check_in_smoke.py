#!/usr/bin/env python3
"""
每日签卡挑战 + 成就系统 smoke test
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-check-in-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text
from db.engine import get_connection
from services.check_in_service import (
    check_in,
    get_check_in_status,
    get_achievements,
    get_check_in_history,
    _ensure_tables,
    _get_current_streak,
    _get_total_days,
)


def run_case(name: str, fn):
    print(f"  ⏳ {name}...", end=" ", flush=True)
    try:
        fn()
        print("✅")
    except AssertionError as e:
        print(f"❌  {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"❌  unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)


def _insert_checkins(student_id: str, days_back: list[int]):
    """辅助：批量插入历史打卡记录"""
    today = datetime.now().date()
    _ensure_tables()
    with get_connection() as conn:
        for d in days_back:
            date_str = (today - timedelta(days=d)).strftime("%Y-%m-%d")
            conn.execute(
                text("INSERT OR IGNORE INTO check_ins (student_id, check_in_date, summary) VALUES (:sid, :d, :s)"),
                {"sid": student_id, "d": date_str, "s": f"day-{d}"},
            )
        conn.commit()


def test_first_check_in():
    """C1: 首次打卡 — 解锁「初来乍到」成就"""
    result = check_in("ci_c1")
    assert result["success"], "首次打卡应该成功"
    assert result["current_streak"] == 1
    assert result["total_days"] == 1
    keys = [a["key"] for a in result["new_achievements"]]
    assert "first_check_in" in keys, f"应解锁 first_check_in，实际: {keys}"


def test_duplicate_check_in():
    """C2: 同一天重复打卡 — 应拒绝"""
    check_in("ci_c2")
    result = check_in("ci_c2")
    assert not result["success"], "同一天不能重复打卡"
    assert "已经打卡" in result.get("message", ""), f"msg={result.get('message')}"


def test_streak_calculation():
    """C3: 连续打卡计算 — 3 天连续"""
    _insert_checkins("ci_c3", [2, 1, 0])
    assert _get_current_streak("ci_c3") == 3
    assert _get_total_days("ci_c3") == 3


def test_broken_streak():
    """C4: 断签 — 中间空一天，连续天数只算今天"""
    _insert_checkins("ci_c4", [3, 0])   # 今天 + 3天前，中间空了
    assert _get_current_streak("ci_c4") == 1
    assert _get_total_days("ci_c4") == 2


def test_bronze_achievement():
    """C5: 连续 7 天解锁铜牌"""
    # 先插入前 6 天
    _insert_checkins("ci_c5", [6, 5, 4, 3, 2, 1])
    # 今天打卡
    result = check_in("ci_c5")
    assert result["success"]
    assert result["current_streak"] == 7
    keys = [a["key"] for a in result["new_achievements"]]
    assert "bronze_streak" in keys, f"应解锁铜牌，实际新成就: {keys}"


def test_get_achievements():
    """C6: 获取成就列表 — 已/未解锁结构正确"""
    _ensure_tables()
    with get_connection() as conn:
        for k in ("first_check_in", "bronze_streak"):
            conn.execute(
                text("INSERT OR IGNORE INTO achievements (student_id, achievement_key) VALUES (:sid, :k)"),
                {"sid": "ci_c6", "k": k},
            )
        conn.commit()
    _insert_checkins("ci_c6", list(range(6, -1, -1)))  # 7 天历史

    data = get_achievements("ci_c6")
    assert len(data["unlocked"]) == 2, f"已解锁应为2，实际{len(data['unlocked'])}"
    assert len(data["locked"]) > 0
    gold = next((a for a in data["locked"] if a["key"] == "gold_streak"), None)
    assert gold is not None
    assert gold["progress"] > 0, "金牌进度应 > 0"


def test_check_in_history():
    """C7: 获取打卡历史"""
    _insert_checkins("ci_c7", [4, 3, 2, 1, 0])
    history = get_check_in_history("ci_c7", days=7)
    assert len(history) == 5, f"应返回5条，实际{len(history)}"
    today = datetime.now().strftime("%Y-%m-%d")
    assert history[0]["date"] == today


def test_check_in_status():
    """C8: 获取打卡状态 — 未打卡 / 已打卡"""
    status = get_check_in_status("ci_c8_fresh")
    assert not status["checked_in_today"]
    assert status["current_streak"] == 0

    check_in("ci_c8_done")
    status2 = get_check_in_status("ci_c8_done")
    assert status2["checked_in_today"]
    assert status2["current_streak"] == 1
    assert status2["today_summary"] is not None


def main():
    print("check_in_smoke.py — 每日签卡挑战 smoke test")
    run_case("C1: 首次打卡解锁初来乍到", test_first_check_in)
    run_case("C2: 同一天重复打卡应拒绝", test_duplicate_check_in)
    run_case("C3: 连续打卡3天计算正确", test_streak_calculation)
    run_case("C4: 断签后连续天数重置为1", test_broken_streak)
    run_case("C5: 连续7天解锁铜牌成就", test_bronze_achievement)
    run_case("C6: 获取成就列表结构正确", test_get_achievements)
    run_case("C7: 获取打卡历史记录", test_check_in_history)
    run_case("C8: 获取打卡状态已/未打卡", test_check_in_status)
    print("✅ 8/8 all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
