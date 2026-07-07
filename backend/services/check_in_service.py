"""
每日签卡挑战与成就系统服务
"""
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import text

from db.engine import engine, get_connection

_TABLES_READY = False
_TABLES_LOCK = Lock()

# 成就配置
ACHIEVEMENTS = {
    "first_check_in": {"days": 1, "name": "初来乍到", "icon": "👋", "description": "首次打卡"},
    "bronze_streak": {"days": 7, "name": "铜牌学者", "icon": "🥉", "description": "连续打卡7天"},
    "silver_streak": {"days": 14, "name": "银牌学者", "icon": "🥈", "description": "连续打卡14天"},
    "gold_streak": {"days": 30, "name": "金牌学者", "icon": "🥇", "description": "连续打卡30天"},
    "master_100": {"days": 100, "name": "百日坚持", "icon": "💯", "description": "累计打卡100天"},
}


def _ensure_tables():
    global _TABLES_READY
    if _TABLES_READY:
        return

    with _TABLES_LOCK:
        if _TABLES_READY:
            return

        is_postgres = engine.dialect.name == "postgresql"
        id_column = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        now_default = "CURRENT_TIMESTAMP" if is_postgres else "datetime('now')"

        with get_connection() as conn:
            if is_postgres:
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('edu_agent_check_in_tables'))"))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS check_ins (
                    id {id_column},
                    student_id TEXT NOT NULL,
                    check_in_date TEXT NOT NULL,
                    summary TEXT,
                    created_at TEXT NOT NULL DEFAULT ({now_default}),
                    UNIQUE(student_id, check_in_date)
                )
            """))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS achievements (
                    id {id_column},
                    student_id TEXT NOT NULL,
                    achievement_key TEXT NOT NULL,
                    unlocked_at TEXT NOT NULL DEFAULT ({now_default}),
                    UNIQUE(student_id, achievement_key)
                )
            """))
        _TABLES_READY = True


def check_in(student_id: str) -> dict:
    """
    学生每日打卡

    Returns:
        success, current_streak, total_days, new_achievements, summary
    """
    _ensure_tables()
    today = datetime.now().strftime("%Y-%m-%d")

    with get_connection() as conn:
        # 检查今天是否已打卡
        row = conn.execute(
            text("SELECT id FROM check_ins WHERE student_id = :sid AND check_in_date = :d"),
            {"sid": student_id, "d": today},
        ).fetchone()
        if row:
            return {
                "success": False,
                "message": "今天已经打卡过了",
                "current_streak": _get_current_streak(student_id),
                "total_days": _get_total_days(student_id),
                "new_achievements": [],
            }

        summary = _generate_today_summary(student_id)
        conn.execute(
            text("INSERT INTO check_ins (student_id, check_in_date, summary) VALUES (:sid, :d, :s)"),
            {"sid": student_id, "d": today, "s": summary},
        )
        conn.commit()

    current_streak = _get_current_streak(student_id)
    total_days = _get_total_days(student_id)
    new_achievements = _unlock_achievements(student_id, current_streak, total_days)

    return {
        "success": True,
        "current_streak": current_streak,
        "total_days": total_days,
        "new_achievements": new_achievements,
        "summary": summary,
    }


def _generate_today_summary(student_id: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    parts = []
    try:
        with get_connection() as conn:
            rows = conn.execute(
                text("""
                    SELECT feature, COUNT(*) AS cnt
                    FROM learning_events
                    WHERE student_id = :sid AND DATE(timestamp) = :d
                    GROUP BY feature
                """),
                {"sid": student_id, "d": today},
            ).fetchall()
        for feature, cnt in rows:
            label = {"review": f"复习 {cnt} 题", "auto_tutor": f"AI辅导 {cnt} 次",
                     "assignment": f"完成作业 {cnt} 次", "character_chat": f"历史对话 {cnt} 次"}.get(feature)
            if label:
                parts.append(label)
    except Exception:
        pass

    return ("今日" + "、".join(parts) + "！") if parts else "今日学习完成！"


def _get_current_streak(student_id: str) -> int:
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT check_in_date FROM check_ins WHERE student_id = :sid ORDER BY check_in_date DESC"),
            {"sid": student_id},
        ).fetchall()

    if not rows:
        return 0

    streak = 0
    expected = datetime.now().date()
    for (date_str,) in rows:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


def _get_total_days(student_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM check_ins WHERE student_id = :sid"),
            {"sid": student_id},
        ).fetchone()
    return row[0] if row else 0


def _unlock_achievements(student_id: str, current_streak: int, total_days: int) -> list:
    new_achievements = []
    with get_connection() as conn:
        # 获取已解锁的成就
        rows = conn.execute(
            text("SELECT achievement_key FROM achievements WHERE student_id = :sid"),
            {"sid": student_id},
        ).fetchall()
        unlocked_keys = {r[0] for r in rows}

        for key, config in ACHIEVEMENTS.items():
            if key in unlocked_keys:
                continue
            should_unlock = False
            if key in ("bronze_streak", "silver_streak", "gold_streak"):
                should_unlock = current_streak >= config["days"]
            elif key == "first_check_in":
                should_unlock = total_days >= 1
            elif key == "master_100":
                should_unlock = total_days >= 100

            if should_unlock:
                try:
                    conn.execute(
                        text("INSERT INTO achievements (student_id, achievement_key) VALUES (:sid, :k)"),
                        {"sid": student_id, "k": key},
                    )
                    new_achievements.append({"key": key, "name": config["name"],
                                             "icon": config["icon"], "description": config["description"]})
                except Exception:
                    pass
        conn.commit()
    return new_achievements


def get_check_in_status(student_id: str) -> dict:
    _ensure_tables()
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT summary FROM check_ins WHERE student_id = :sid AND check_in_date = :d"),
            {"sid": student_id, "d": today},
        ).fetchone()
    return {
        "checked_in_today": row is not None,
        "current_streak": _get_current_streak(student_id),
        "total_days": _get_total_days(student_id),
        "today_summary": row[0] if row else None,
    }


def get_achievements(student_id: str) -> dict:
    _ensure_tables()
    current_streak = _get_current_streak(student_id)
    total_days = _get_total_days(student_id)

    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT achievement_key, unlocked_at FROM achievements WHERE student_id = :sid ORDER BY unlocked_at DESC"),
            {"sid": student_id},
        ).fetchall()
    unlocked_keys = {r[0]: r[1] for r in rows}

    unlocked, locked = [], []
    for key, config in ACHIEVEMENTS.items():
        if key in unlocked_keys:
            unlocked.append({"key": key, "name": config["name"], "icon": config["icon"],
                             "description": config["description"], "unlocked_at": unlocked_keys[key]})
        else:
            if key in ("bronze_streak", "silver_streak", "gold_streak"):
                progress = min(1.0, current_streak / config["days"])
            elif key == "first_check_in":
                progress = 1.0 if total_days >= 1 else 0.0
            elif key == "master_100":
                progress = min(1.0, total_days / 100)
            else:
                progress = 0.0
            locked.append({"key": key, "name": config["name"], "icon": config["icon"],
                           "description": config["description"], "progress": progress})
    return {"unlocked": unlocked, "locked": locked}


def get_check_in_history(student_id: str, days: int = 90) -> list:
    _ensure_tables()
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute(
            text("""
                SELECT check_in_date, summary
                FROM check_ins
                WHERE student_id = :sid AND check_in_date >= :sd
                ORDER BY check_in_date DESC
            """),
            {"sid": student_id, "sd": start_date},
        ).fetchall()
    return [{"date": r[0], "summary": r[1]} for r in rows]
