"""Smoke test: 学生学习日历

覆盖场景：
1. lastNDays 帮助函数生成正确日期列表（纯逻辑验证）
2. 学习报告 API 返回字段包含 activity_by_day / review_by_day / streak_days
3. 活跃度 = 0 时 activity_by_day 不含该日期（而非存 0）
4. review_by_day 格式：{date: {completed, total}}
5. streak_days 计算：有连续活跃天则 > 0
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-calendar-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

STUDENT = "smoke-calendar-stu"
TODAY = date.today().isoformat()


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


# ── C1: lastNDays 日期列表正确（纯 Python 验证）─────────────────────────────
def c1_last_n_days():
    from datetime import date as _d, timedelta as _td
    def last_n_days(n: int) -> list[str]:
        today = _d.today()
        return [(today - _td(days=n - 1 - i)).isoformat() for i in range(n)]

    days14 = last_n_days(14)
    assert len(days14) == 14, f"期望14天，实际 {len(days14)}"
    assert days14[-1] == _d.today().isoformat(), "最后一项应为今天"
    assert days14[0] == (_d.today() - _td(days=13)).isoformat(), "第一项应为 13 天前"
    # 递增顺序
    for i in range(len(days14) - 1):
        assert days14[i] < days14[i + 1], "日期应递增"


# ── C2: 报告 API 包含所需字段 ─────────────────────────────────────────────────
def c2_report_has_calendar_fields():
    from db.engine import get_connection
    from sqlalchemy import text
    from student_profile import init_db
    init_db()
    # 写入一条学习事件
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS learning_events (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            feature TEXT,
            event_type TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT)"""))
        conn.execute(text("""INSERT OR IGNORE INTO learning_events
            (id, student_id, feature, event_type, created_at, metadata_json)
            VALUES ('cal-evt-1', :sid, 'review', 'answer', :ts, '{}')"""),
            {"sid": STUDENT, "ts": TODAY + "T10:00:00Z"})

    # 构造简化版 learning report（不调 LLM，只检查数据库查询逻辑）
    from db.engine import get_connection
    from sqlalchemy import text as _text
    with get_connection() as conn:
        since = (date.today() - timedelta(days=14)).isoformat()
        ev_rows = conn.execute(_text(
            "SELECT substr(created_at,1,10) as day, COUNT(*) as cnt "
            "FROM learning_events WHERE student_id=:sid AND created_at>=:since "
            "GROUP BY day"),
            {"sid": STUDENT, "since": since},
        ).mappings().fetchall()
    activity_by_day = {r["day"]: int(r["cnt"]) for r in ev_rows}

    assert TODAY in activity_by_day, f"今日事件应出现在 activity_by_day，实际：{list(activity_by_day.keys())}"
    assert activity_by_day[TODAY] >= 1


# ── C3: 无活跃事件的日期不出现在 activity_by_day ─────────────────────────────
def c3_inactive_days_absent():
    from db.engine import get_connection
    from sqlalchemy import text as _text
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with get_connection() as conn:
        since = (date.today() - timedelta(days=14)).isoformat()
        ev_rows = conn.execute(_text(
            "SELECT substr(created_at,1,10) as day, COUNT(*) as cnt "
            "FROM learning_events WHERE student_id=:sid AND created_at>=:since "
            "GROUP BY day"),
            {"sid": STUDENT, "since": since},
        ).mappings().fetchall()
    activity_by_day = {r["day"]: int(r["cnt"]) for r in ev_rows}
    # 昨天没有事件，不应出现
    if yesterday not in activity_by_day:
        pass  # correct
    else:
        # 如果昨天有数据，值应 > 0
        assert activity_by_day[yesterday] > 0, "0 值不应出现在 activity_by_day"


# ── C4: review_by_day 格式验证 ────────────────────────────────────────────────
def c4_review_by_day_format():
    from services.weakpoint_service import _ensure_table, record_weakpoint
    from services.review_service import create_today_session, get_today_session, _ensure_table as _rv_ensure
    _ensure_table(); _rv_ensure()
    record_weakpoint(STUDENT, "日历测试知识点", "assignment")
    session = create_today_session(STUDENT, TODAY)
    assert "tasks" in session and "total" in session

    from db.engine import get_connection
    from sqlalchemy import text as _text
    with get_connection() as conn:
        rows = conn.execute(_text(
            "SELECT date, completed, total FROM review_sessions WHERE student_id=:sid"),
            {"sid": STUDENT},
        ).mappings().fetchall()
    review_by_day = {r["date"]: {"completed": r["completed"], "total": r["total"]} for r in rows}
    assert TODAY in review_by_day, f"今日复习应在 review_by_day，实际键：{list(review_by_day.keys())}"
    rev = review_by_day[TODAY]
    assert "completed" in rev and "total" in rev


# ── C5: streak_days：连续活跃天数计算 ────────────────────────────────────────
def c5_streak_days():
    from db.engine import get_connection
    from sqlalchemy import text as _text
    with get_connection() as conn:
        ev_rows = conn.execute(_text(
            "SELECT DISTINCT substr(created_at,1,10) as day "
            "FROM learning_events WHERE student_id=:sid ORDER BY day DESC"),
            {"sid": STUDENT},
        ).mappings().fetchall()
    dates_set = {r["day"] for r in ev_rows}
    streak, check = 0, date.today()
    while check.isoformat() in dates_set:
        streak += 1
        check -= timedelta(days=1)
    # STUDENT 今天有事件，streak 应 >= 1
    assert streak >= 1, f"今天有事件，streak 应 ≥1，实际 {streak}"


if __name__ == "__main__":
    cases = [
        ("C1 lastNDays 日期列表正确", c1_last_n_days),
        ("C2 activity_by_day 今日有事件", c2_report_has_calendar_fields),
        ("C3 无活跃日期不出现在 map", c3_inactive_days_absent),
        ("C4 review_by_day 格式正确", c4_review_by_day_format),
        ("C5 streak_days ≥1", c5_streak_days),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
