"""Smoke test: AI 辅导效果追踪

覆盖场景：
1. 无辅导记录时返回空摘要
2. 写入 learning_events 后聚合正确（total_steps/mastered_steps/mastery_rate）
3. 按知识点聚合正确（tag stats）
4. still_weak 字段与当前错题本一致
5. 教师班级视角聚合（active_students/class-level tags）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-tutor-eff-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

STUDENT = "smoke-teff-student"
TEACHER = "smoke-teff-teacher"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


def _ensure_learning_events_table():
    from db.engine import get_connection
    from sqlalchemy import text
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS learning_events (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            feature TEXT,
            event_type TEXT,
            topic TEXT,
            success INTEGER,
            score REAL,
            session_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT)"""))


def _write_tutor_step(student_id: str, tag: str, success: bool):
    """模拟 _finalize 写入 learning_events 的 auto_tutor_step 记录。"""
    import uuid
    from db.engine import get_connection
    from sqlalchemy import text
    _ensure_learning_events_table()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(text("""INSERT INTO learning_events
            (id, student_id, feature, event_type, topic, success, score, session_id, created_at, metadata_json)
            VALUES (:id, :sid, 'auto_tutor', 'auto_tutor_step', :tag, :success, :score, 'sess1', :ts, '{}')"""),
            {"id": str(uuid.uuid4()), "sid": student_id, "tag": tag,
             "success": 1 if success else 0, "score": 1.0 if success else 0.0, "ts": ts})


def _write_exit_ticket(student_id: str, tag: str, success: bool, session_id: str = "sess-exit"):
    """模拟 AutoTutor 退出票学习证据。"""
    import uuid
    from db.engine import get_connection
    from sqlalchemy import text
    _ensure_learning_events_table()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        conn.execute(text("""INSERT INTO learning_events
            (id, student_id, feature, event_type, topic, success, score, session_id, created_at, metadata_json)
            VALUES (:id, :sid, 'auto_tutor', 'auto_tutor_exit_ticket', :tag, :success, :score, :session_id, :ts, '{}')"""),
            {"id": str(uuid.uuid4()), "sid": student_id, "tag": tag,
             "success": 1 if success else 0, "score": 1.0 if success else 0.0, "session_id": session_id, "ts": ts})


# ── Case 1: 无辅导记录返回空摘要 ─────────────────────────────────────────────
def c1_no_records():
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    _ensure_learning_events_table()
    result = get_student_tutor_effectiveness("no-data-student-xyz")
    assert result["summary"]["total_steps"] == 0
    assert result["summary"]["mastery_rate"] == 0.0
    assert result["tags"] == []


# ── Case 2: 聚合正确 ──────────────────────────────────────────────────────────
def c2_aggregation():
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    # 2 次「鸦片战争」：1 掌握 1 未掌握；1 次「洋务运动」掌握
    _write_tutor_step(STUDENT, "鸦片战争", True)
    _write_tutor_step(STUDENT, "鸦片战争", False)
    _write_tutor_step(STUDENT, "洋务运动", True)
    result = get_student_tutor_effectiveness(STUDENT)
    assert result["summary"]["total_steps"] == 3, f"期望3，实际 {result['summary']['total_steps']}"
    assert result["summary"]["mastered_steps"] == 2
    assert abs(result["summary"]["mastery_rate"] - 66.7) < 1.0
    assert result["summary"]["tags_worked"] == 2


# ── Case 3: 按知识点统计正确 ──────────────────────────────────────────────────
def c3_per_tag_stats():
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    result = get_student_tutor_effectiveness(STUDENT)
    tags = {t["tag"]: t for t in result["tags"]}
    assert "鸦片战争" in tags
    assert tags["鸦片战争"]["total"] == 2
    assert tags["鸦片战争"]["mastered"] == 1
    assert abs(tags["鸦片战争"]["mastery_rate"] - 50.0) < 0.1
    assert "洋务运动" in tags
    assert tags["洋务运动"]["mastery_rate"] == 100.0


# ── Case 4: still_weak 与错题本一致 ──────────────────────────────────────────
def c4_still_weak():
    from services.weakpoint_service import _ensure_table, record_weakpoint
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    _ensure_table()
    record_weakpoint(STUDENT, "鸦片战争", source="auto_tutor")  # 仍在错题本
    result = get_student_tutor_effectiveness(STUDENT)
    tags = {t["tag"]: t for t in result["tags"]}
    assert tags["鸦片战争"]["still_weak"] is True, "仍在错题本应为 still_weak=True"
    # 洋务运动未加入错题本
    assert tags.get("洋务运动", {}).get("still_weak") is False


# ── Case 5: 教师班级视角 ──────────────────────────────────────────────────────
def c5_class_view():
    from services.tutor_effectiveness_service import get_class_tutor_effectiveness
    # 再写另一个学生的记录
    _write_tutor_step("smoke-teff-s2", "甲午战争", True)
    _write_tutor_step("smoke-teff-s2", "甲午战争", False)
    result = get_class_tutor_effectiveness(TEACHER)  # teacher_id 不用于过滤
    assert result["summary"]["total_steps"] >= 3, f"应有 ≥3 步骤，实际 {result['summary']['total_steps']}"
    assert result["summary"]["active_students"] >= 1
    assert len(result["tags"]) >= 1
    for t in result["tags"]:
        assert "student_count" in t and "mastery_rate" in t


# ── Case 6: 退出票学习证据被学生视角统计 ─────────────────────────────────────
def c6_exit_ticket_events_are_counted():
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    _write_exit_ticket(STUDENT, "鸦片战争", True, "sess-exit-a")
    _write_exit_ticket(STUDENT, "洋务运动", False, "sess-exit-b")
    result = get_student_tutor_effectiveness(STUDENT)
    summary = result["summary"]
    assert summary["exit_tickets"] == 2, summary
    assert summary["exit_ticket_mastered"] == 1, summary
    assert abs(summary["exit_ticket_mastery_rate"] - 50.0) < 0.1, summary
    tags = {t["tag"]: t for t in result["tags"]}
    assert tags["鸦片战争"]["exit_tickets"] >= 1, tags["鸦片战争"]
    assert tags["鸦片战争"]["exit_ticket_mastery_rate"] == 100.0, tags["鸦片战争"]


# ── Case 7: 班级视角聚合退出票证据 ──────────────────────────────────────────
def c7_class_exit_ticket_rollup():
    from services.tutor_effectiveness_service import get_class_tutor_effectiveness
    _write_exit_ticket("smoke-teff-s3", "辛亥革命", True, "sess-exit-c")
    result = get_class_tutor_effectiveness(TEACHER)
    summary = result["summary"]
    assert summary["exit_tickets"] >= 3, summary
    assert summary["students_with_exit_ticket"] >= 2, summary
    assert 0.0 <= summary["exit_ticket_mastery_rate"] <= 100.0, summary
    assert any(t.get("exit_tickets", 0) > 0 for t in result["tags"]), result["tags"]


# ── Case 8: 无退出票的旧 step 数据仍兼容 ─────────────────────────────────────
def c8_legacy_step_events_still_work_without_exit_ticket():
    from services.tutor_effectiveness_service import get_student_tutor_effectiveness
    legacy_student = "smoke-teff-legacy"
    _write_tutor_step(legacy_student, "分封制", True)
    result = get_student_tutor_effectiveness(legacy_student)
    assert result["summary"]["total_steps"] == 1, result
    assert result["summary"]["exit_tickets"] == 0, result
    assert result["summary"]["exit_ticket_mastery_rate"] == 0.0, result


if __name__ == "__main__":
    cases = [
        ("C1 无记录返回空摘要", c1_no_records),
        ("C2 步骤聚合正确", c2_aggregation),
        ("C3 按知识点统计正确", c3_per_tag_stats),
        ("C4 still_weak 与错题本一致", c4_still_weak),
        ("C5 教师班级视角聚合", c5_class_view),
        ("C6 退出票学习证据被统计", c6_exit_ticket_events_are_counted),
        ("C7 班级退出票证据聚合", c7_class_exit_ticket_rollup),
        ("C8 旧 step 数据兼容", c8_legacy_step_events_still_work_without_exit_ticket),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
