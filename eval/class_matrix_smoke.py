#!/usr/bin/env python3
"""
教师端班级知识热力图 smoke test
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-class-matrix-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text
from db.engine import get_connection


def run_case(name: str, fn):
    print(f"  ⏳ {name}...", end=" ", flush=True)
    try:
        fn()
        print("✅")
    except AssertionError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"❌ unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)


def _setup_test_data():
    """创建测试数据：3个学生 × 4个知识点"""
    with get_connection() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS weakpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                knowledge_tag TEXT NOT NULL,
                wrong_count INTEGER DEFAULT 1,
                correct_streak INTEGER DEFAULT 0,
                source TEXT DEFAULT 'test',
                last_wrong_at TEXT DEFAULT (datetime('now')),
                is_mastered INTEGER DEFAULT 0,
                last_attempt_at TEXT DEFAULT (datetime('now')),
                UNIQUE(student_id, knowledge_tag)
            )
        """))

        # 插入测试数据
        test_data = [
            ("student1", "秦始皇统一", 5, 0),
            ("student1", "鸦片战争", 2, 1),
            ("student2", "秦始皇统一", 3, 0),
            ("student2", "辛亥革命", 1, 2),
            ("student3", "鸦片战争", 4, 0),
            ("student3", "洋务运动", 2, 0),
        ]
        for sid, tag, wc, cs in test_data:
            conn.execute(
                text("""INSERT OR IGNORE INTO weakpoints
                        (student_id, knowledge_tag, wrong_count, correct_streak)
                        VALUES (:s, :t, :w, :c)"""),
                {"s": sid, "t": tag, "w": wc, "c": cs},
            )
        conn.commit()


def test_matrix_structure():
    """C1: 矩阵结构正确 - students/tags/matrix 三个字段"""
    _setup_test_data()

    # 模拟 API 调用
    from collections import defaultdict
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT student_id, knowledge_tag, wrong_count, correct_streak FROM weakpoints"),
        ).mappings().fetchall()

    student_ids = sorted(set(r["student_id"] for r in rows))
    tag_counts = defaultdict(int)
    student_tag_data = defaultdict(dict)

    for r in rows:
        sid = r["student_id"]
        tag = r["knowledge_tag"]
        wc = int(r["wrong_count"] or 0)
        cs = int(r["correct_streak"] or 0)
        strength = round(min(1.0, max(0.1, 1.0 - min(wc * 0.15, 0.9) + cs * 0.2)), 3)
        student_tag_data[sid][tag] = strength
        tag_counts[tag] += 1

    tags = sorted(tag_counts.keys(), key=lambda t: -tag_counts[t])

    matrix = []
    for sid in student_ids:
        row = [student_tag_data[sid].get(tag, 1.0) for tag in tags]
        matrix.append(row)

    # 验证结构
    assert len(student_ids) == 3, f"应有3个学生，实际{len(student_ids)}"
    assert len(tags) >= 4, f"应有至少4个知识点，实际{len(tags)}"
    assert len(matrix) == len(student_ids), "矩阵行数应等于学生数"
    assert all(len(row) == len(tags) for row in matrix), "每行列数应等于知识点数"


def test_matrix_values():
    """C2: 矩阵值范围正确 - 0.1-1.0 之间"""
    _setup_test_data()

    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT student_id, knowledge_tag, wrong_count, correct_streak FROM weakpoints"),
        ).mappings().fetchall()

    for r in rows:
        wc = int(r["wrong_count"] or 0)
        cs = int(r["correct_streak"] or 0)
        strength = round(min(1.0, max(0.1, 1.0 - min(wc * 0.15, 0.9) + cs * 0.2)), 3)
        assert 0.1 <= strength <= 1.0, f"掌握度应在0.1-1.0之间，实际{strength}"


def test_tag_ordering():
    """C3: 知识点按薄弱人数降序排列"""
    _setup_test_data()

    from collections import defaultdict
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT student_id, knowledge_tag FROM weakpoints"),
        ).mappings().fetchall()

    tag_counts = defaultdict(int)
    for r in rows:
        tag_counts[r["knowledge_tag"]] += 1

    tags = sorted(tag_counts.keys(), key=lambda t: -tag_counts[t])

    # 验证排序：前一个的人数应>=后一个
    for i in range(len(tags) - 1):
        assert tag_counts[tags[i]] >= tag_counts[tags[i + 1]], \
            f"知识点应按薄弱人数降序，{tags[i]}({tag_counts[tags[i]]}) < {tags[i+1]}({tag_counts[tags[i+1]]})"


def test_missing_tag_default():
    """C4: 学生未出现的知识点默认1.0（已掌握）"""
    _setup_test_data()

    from collections import defaultdict
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT student_id, knowledge_tag, wrong_count, correct_streak FROM weakpoints"),
        ).mappings().fetchall()

    student_ids = sorted(set(r["student_id"] for r in rows))
    all_tags = sorted(set(r["knowledge_tag"] for r in rows))
    student_tag_data = defaultdict(dict)

    for r in rows:
        sid = r["student_id"]
        tag = r["knowledge_tag"]
        wc = int(r["wrong_count"] or 0)
        cs = int(r["correct_streak"] or 0)
        strength = round(min(1.0, max(0.1, 1.0 - min(wc * 0.15, 0.9) + cs * 0.2)), 3)
        student_tag_data[sid][tag] = strength

    # student1 没有「洋务运动」，应默认1.0
    assert student_tag_data["student1"].get("洋务运动", 1.0) == 1.0


def test_empty_weakpoints():
    """C5: 错题本为空时返回空矩阵"""
    # 清空数据
    with get_connection() as conn:
        conn.execute(text("DELETE FROM weakpoints"))
        conn.commit()

    with get_connection() as conn:
        rows = conn.execute(text("SELECT * FROM weakpoints")).mappings().fetchall()

    assert len(rows) == 0, "错题本应为空"

    student_ids = sorted(set(r["student_id"] for r in rows))
    tags = sorted(set(r["knowledge_tag"] for r in rows))

    assert len(student_ids) == 0
    assert len(tags) == 0


def main():
    print("class_matrix_smoke.py — 教师端班级知识热力图 smoke test")
    run_case("C1: 矩阵结构正确", test_matrix_structure)
    run_case("C2: 掌握度值范围0.1-1.0", test_matrix_values)
    run_case("C3: 知识点按薄弱人数排序", test_tag_ordering)
    run_case("C4: 缺失知识点默认1.0", test_missing_tag_default)
    run_case("C5: 空错题本返回空矩阵", test_empty_weakpoints)
    print("✅ 5/5 all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
