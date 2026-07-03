"""Smoke test: 催办通知实际发送

覆盖场景：
1. send_urge_notification 向学生写入通知，返回正确数量
2. get_student_notifications 返回通知列表，含全部字段
3. get_unread_count 返回正确未读数
4. mark_notification_read 标记已读后 is_read=True
5. mark_all_read 批量标记，未读数归零
6. 空 student_ids 不写入任何通知
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-urge-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

TEACHER = "smoke-urge-teacher"
STUDENT_A = "smoke-urge-sa"
STUDENT_B = "smoke-urge-sb"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback; traceback.print_exc()
        return False


# ── Case 1: send_urge_notification 写入通知 ───────────────────────────────────
def c1_send_notification():
    from services.notification_service import send_urge_notification
    n = send_urge_notification(TEACHER, [STUDENT_A, STUDENT_B], "请完成作业！", ["asgn-001"])
    assert n == 2, f"期望写入 2 条，实际 {n}"


# ── Case 2: get_student_notifications 字段完整 ────────────────────────────────
def c2_get_notifications():
    from services.notification_service import get_student_notifications
    items = get_student_notifications(STUDENT_A)
    assert len(items) >= 1, "应有至少一条通知"
    item = items[0]
    for field in ("id", "teacher_id", "message", "assignment_ids", "created_at", "is_read"):
        assert field in item, f"缺少字段: {field}"
    assert item["teacher_id"] == TEACHER
    assert item["message"] == "请完成作业！"
    assert "asgn-001" in item["assignment_ids"]
    assert item["is_read"] is False  # 刚发送，未读


# ── Case 3: get_unread_count 正确 ─────────────────────────────────────────────
def c3_unread_count():
    from services.notification_service import get_unread_count
    cnt = get_unread_count(STUDENT_A)
    assert cnt >= 1, f"应有 ≥1 未读，实际 {cnt}"


# ── Case 4: mark_notification_read 标记已读 ────────────────────────────────────
def c4_mark_read():
    from services.notification_service import get_student_notifications, mark_notification_read, get_unread_count
    items = get_student_notifications(STUDENT_A, unread_only=True)
    assert items, "应有未读通知"
    nid = items[0]["id"]
    before = get_unread_count(STUDENT_A)
    ok = mark_notification_read(nid, STUDENT_A)
    assert ok, "标记已读应返回 True"
    after = get_unread_count(STUDENT_A)
    assert after == before - 1, f"已读后未读数应 -1，实际 before={before} after={after}"


# ── Case 5: mark_all_read 未读数归零 ──────────────────────────────────────────
def c5_mark_all_read():
    from services.notification_service import send_urge_notification, mark_all_read, get_unread_count
    # 给 STUDENT_B 再发一条
    send_urge_notification(TEACHER, [STUDENT_B], "再催一次", [])
    before = get_unread_count(STUDENT_B)
    assert before >= 1, f"STUDENT_B 应有未读，实际 {before}"
    n = mark_all_read(STUDENT_B)
    assert n >= 1, f"标记行数应 ≥1，实际 {n}"
    after = get_unread_count(STUDENT_B)
    assert after == 0, f"全部已读后未读数应为 0，实际 {after}"


# ── Case 6: 空 student_ids 不写入 ─────────────────────────────────────────────
def c6_empty_students():
    from services.notification_service import send_urge_notification
    n = send_urge_notification(TEACHER, [], "空列表", [])
    assert n == 0, f"空 student_ids 应写入 0 条，实际 {n}"


if __name__ == "__main__":
    cases = [
        ("C1 send_urge_notification 写入数量正确", c1_send_notification),
        ("C2 get_student_notifications 字段完整", c2_get_notifications),
        ("C3 get_unread_count 正确", c3_unread_count),
        ("C4 mark_notification_read 标记已读", c4_mark_read),
        ("C5 mark_all_read 未读数归零", c5_mark_all_read),
        ("C6 空 student_ids 不写入", c6_empty_students),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
