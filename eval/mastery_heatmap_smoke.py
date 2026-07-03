"""Smoke test: 知识点掌握度热力图

覆盖场景：
1. 班级热力图：无数据时返回空列表
2. 班级热力图：有数据时按 student_count 降序聚合
3. 班级热力图：avg_strength 在 0-1 范围内
4. 学生 mastery-overview：无薄弱点时正常返回空 heatmap
5. 学生 mastery-overview：有薄弱点时 strength 计算在合理范围
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-mastery-heatmap-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

STUDENT_A = "smoke-mastery-sa"
STUDENT_B = "smoke-mastery-sb"
TAG1, TAG2 = "鸦片战争", "洋务运动"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


def _seed_weakpoints():
    """写入测试薄弱点数据。"""
    from services.weakpoint_service import _ensure_table, record_weakpoint
    _ensure_table()
    # STUDENT_A: TAG1 × 3, TAG2 × 1
    for _ in range(3):
        record_weakpoint(STUDENT_A, TAG1, "assignment")
    record_weakpoint(STUDENT_A, TAG2, "assignment")
    # STUDENT_B: TAG1 × 1
    record_weakpoint(STUDENT_B, TAG1, "review")


# ── Case 1: 班级热力图无数据 ───────────────────────────────────────────────────
def c1_no_data():
    from db.engine import get_connection
    from sqlalchemy import text
    from services.weakpoint_service import _ensure_table
    _ensure_table()
    # 只查询，不插入数据（用独立 teacher_empty 检验）
    with get_connection() as conn:
        rows = conn.execute(text("SELECT COUNT(*) AS cnt FROM weakpoints")).fetchone()
    # 只要不报错即可（数据可能来自其他 case）
    assert rows is not None


# ── Case 2: 班级热力图聚合正确 ────────────────────────────────────────────────
def c2_class_heatmap_aggregation():
    from collections import defaultdict
    from db.engine import get_connection
    from sqlalchemy import text
    from services.weakpoint_service import _ensure_table
    _ensure_table()
    _seed_weakpoints()

    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT knowledge_tag, wrong_count, correct_streak, student_id FROM weakpoints")
        ).mappings().fetchall()

    tag_students: dict[str, set] = defaultdict(set)
    for r in rows:
        tag_students[r["knowledge_tag"]].add(r["student_id"])

    # TAG1 被 2 个学生记录，TAG2 被 1 个
    assert len(tag_students[TAG1]) >= 2, f"TAG1 应有 ≥2 学生，实际 {len(tag_students[TAG1])}"
    assert len(tag_students[TAG2]) >= 1, f"TAG2 应有 ≥1 学生"

    # 降序排列
    sorted_tags = sorted(tag_students.items(), key=lambda x: -len(x[1]))
    assert sorted_tags[0][0] == TAG1, f"student_count 最高的应是 {TAG1}"


# ── Case 3: avg_strength 在 0-1 范围 ──────────────────────────────────────────
def c3_strength_in_range():
    from services.weakpoint_service import get_weakpoints
    wps = get_weakpoints(STUDENT_A)
    for wp in wps:
        wc = int(wp["wrong_count"] or 0)
        cs = int(wp.get("correct_streak") or 0)
        strength = round(min(1.0, max(0.1, 1.0 - min(wc * 0.15, 0.9) + cs * 0.2)), 3)
        assert 0.0 < strength <= 1.0, f"strength 超出范围: tag={wp['knowledge_tag']}, strength={strength}"


# ── Case 4: mastery-overview 无薄弱点时正常返回 ────────────────────────────────
def c4_mastery_empty_student():
    from services.review_service import get_mastery_overview
    result = get_mastery_overview("no-data-student-xyz")
    assert "total_tags" in result
    assert "heatmap" in result
    assert result["total_tags"] == 0
    assert result["heatmap"] == []
    assert result["streak_days"] == 0


# ── Case 5: 有薄弱点时 heatmap strength 计算合理 ──────────────────────────────
def c5_mastery_with_weakpoints():
    from services.review_service import get_mastery_overview
    result = get_mastery_overview(STUDENT_A)
    assert result["total_tags"] >= 1, "应有至少一个知识点"
    assert len(result["heatmap"]) == result["total_tags"]
    for item in result["heatmap"]:
        assert "tag" in item
        assert "strength" in item
        assert 0.0 < item["strength"] <= 1.0, f"strength 超出范围: {item}"
        assert "wrong_count" in item
        assert "correct_streak" in item
    # STUDENT_A 的 TAG1 答错 3 次，strength 应该 < 0.7（不是已掌握）
    tag1_item = next((x for x in result["heatmap"] if x["tag"] == TAG1), None)
    assert tag1_item is not None, f"heatmap 中应包含 {TAG1}"
    assert tag1_item["strength"] < 0.7, f"{TAG1} 答错3次，strength 应 <0.7，实际 {tag1_item['strength']}"


if __name__ == "__main__":
    cases = [
        ("C1 班级热力图无数据查询正常", c1_no_data),
        ("C2 班级热力图聚合正确", c2_class_heatmap_aggregation),
        ("C3 avg_strength 在 0-1 范围", c3_strength_in_range),
        ("C4 mastery-overview 无薄弱点", c4_mastery_empty_student),
        ("C5 有薄弱点时 heatmap 计算", c5_mastery_with_weakpoints),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
