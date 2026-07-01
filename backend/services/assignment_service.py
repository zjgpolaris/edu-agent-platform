"""教师布置作业工作流服务

支持教师创建作业（客观题+主观题）、指定学生、学生作答提交与自动批改。
客观题（single_choice / multiple_choice / true_false）自动判分；主观题记录待人工评阅。
表结构见 db/schema.py 的 assignments / assignment_submissions。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from db.engine import get_connection
from student_profile import now_iso

# 自动判分支持的客观题型
OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false"}


def _ensure_tables() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY,
            teacher_id TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            grade TEXT,
            questions_json TEXT NOT NULL,
            assignee_ids_json TEXT NOT NULL,
            due_date TEXT,
            created_at TEXT NOT NULL)"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assignments_teacher ON assignments(teacher_id, created_at)"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS assignment_submissions (
            id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            score REAL,
            status TEXT NOT NULL DEFAULT 'submitted',
            submitted_at TEXT NOT NULL,
            teacher_feedback TEXT,
            reviewed_at TEXT,
            UNIQUE(student_id, assignment_id))"""))
        conn.execute(text("ALTER TABLE assignment_submissions ADD COLUMN IF NOT EXISTS teacher_feedback TEXT"))
        conn.execute(text("ALTER TABLE assignment_submissions ADD COLUMN IF NOT EXISTS reviewed_at TEXT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assignment_submissions_assignment ON assignment_submissions(assignment_id)"))


def _normalize_answer(value: Any) -> Any:
    """把答案规整成可比较形式：多选排序去空白，单选/判断转小写字符串。"""
    if isinstance(value, list):
        return sorted(str(v).strip().lower() for v in value)
    return str(value).strip().lower()


def create_assignment(
    teacher_id: str,
    title: str,
    questions: list[dict[str, Any]],
    assignee_ids: list[str],
    subject: str | None = None,
    grade: str | None = None,
    due_date: str | None = None,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("作业标题不能为空")
    if not questions:
        raise ValueError("作业至少需要一道题")
    if not assignee_ids:
        raise ValueError("请至少指定一名学生")

    assignment_id = f"asg_{uuid.uuid4().hex[:12]}"
    created_at = now_iso()
    _ensure_tables()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO assignments
                (id, teacher_id, title, subject, grade, questions_json, assignee_ids_json, due_date, created_at)
                VALUES (:id, :teacher_id, :title, :subject, :grade, :questions, :assignees, :due_date, :created_at)"""),
            {
                "id": assignment_id, "teacher_id": teacher_id, "title": title.strip(),
                "subject": subject, "grade": grade,
                "questions": json.dumps(questions, ensure_ascii=False),
                "assignees": json.dumps(assignee_ids, ensure_ascii=False),
                "due_date": due_date, "created_at": created_at,
            },
        )
    return {
        "id": assignment_id, "teacher_id": teacher_id, "title": title.strip(),
        "subject": subject, "grade": grade, "questions": questions,
        "assignee_ids": assignee_ids, "due_date": due_date, "created_at": created_at,
    }


def _row_to_assignment(row: Any, *, include_questions: bool = True) -> dict[str, Any]:
    data = {
        "id": row["id"], "teacher_id": row["teacher_id"], "title": row["title"],
        "subject": row["subject"], "grade": row["grade"],
        "assignee_ids": json.loads(row["assignee_ids_json"] or "[]"),
        "due_date": row["due_date"], "created_at": row["created_at"],
    }
    if include_questions:
        data["questions"] = json.loads(row["questions_json"] or "[]")
    return data


def list_teacher_assignments(teacher_id: str) -> list[dict[str, Any]]:
    """教师作业列表，附带每份作业的完成率与平均分。"""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM assignments WHERE teacher_id = :tid ORDER BY created_at DESC"),
            {"tid": teacher_id},
        ).mappings().fetchall()
        assignments = [_row_to_assignment(r, include_questions=False) for r in rows]
        for item in assignments:
            subs = conn.execute(
                text("SELECT score, status FROM assignment_submissions WHERE assignment_id = :aid"),
                {"aid": item["id"]},
            ).mappings().fetchall()
            assignee_count = len(item["assignee_ids"]) or 1
            item["submitted_count"] = len(subs)
            item["assignee_count"] = len(item["assignee_ids"])
            item["completion_rate"] = round(len(subs) / assignee_count * 100)
            scored = [s["score"] for s in subs if s["score"] is not None]
            item["average_score"] = round(sum(scored) / len(scored), 1) if scored else None
    return assignments


def get_assignment_submissions(teacher_id: str, assignment_id: str) -> dict[str, Any]:
    """查看一份作业的题目与所有学生提交明细。"""
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM assignments WHERE id = :aid"),
            {"aid": assignment_id},
        ).mappings().fetchone()
        if not row:
            raise LookupError("作业不存在")
        if row["teacher_id"] != teacher_id:
            raise PermissionError("无权查看此作业")
        assignment = _row_to_assignment(row)
        subs = conn.execute(
            text("SELECT * FROM assignment_submissions WHERE assignment_id = :aid ORDER BY submitted_at"),
            {"aid": assignment_id},
        ).mappings().fetchall()
    submissions = [
        {
            "student_id": s["student_id"], "score": s["score"], "status": s["status"],
            "submitted_at": s["submitted_at"], "answers": json.loads(s["answers_json"] or "[]"),
            "teacher_feedback": s.get("teacher_feedback") if hasattr(s, "get") else None,
            "reviewed_at": s.get("reviewed_at") if hasattr(s, "get") else None,
        }
        for s in subs
    ]
    return {"assignment": assignment, "submissions": submissions}


def review_assignment_submission(
    teacher_id: str,
    assignment_id: str,
    student_id: str,
    score: float,
    feedback: str | None = None,
) -> dict[str, Any]:
    """教师人工评阅一份学生提交（主要用于主观题），更新分数与反馈。"""
    _ensure_tables()
    if score < 0 or score > 100:
        raise ValueError("分数必须在 0-100 之间")

    with get_connection() as conn:
        assignment_row = conn.execute(
            text("SELECT * FROM assignments WHERE id = :aid"), {"aid": assignment_id},
        ).mappings().fetchone()
        if not assignment_row:
            raise LookupError("作业不存在")
        if assignment_row["teacher_id"] != teacher_id:
            raise PermissionError("无权评阅此作业")

        sub = conn.execute(
            text("SELECT * FROM assignment_submissions WHERE assignment_id = :aid AND student_id = :sid"),
            {"aid": assignment_id, "sid": student_id},
        ).mappings().fetchone()
        if not sub:
            raise LookupError("学生尚未提交此作业")

        reviewed_at = now_iso()
        conn.execute(
            text("""UPDATE assignment_submissions
                SET score = :score, status = 'graded', teacher_feedback = :feedback, reviewed_at = :reviewed_at
                WHERE assignment_id = :aid AND student_id = :sid"""),
            {"score": score, "feedback": feedback or "", "reviewed_at": reviewed_at, "aid": assignment_id, "sid": student_id},
        )

    # 主观题评阅后按整份作业分数粗粒度回流知识点：低分保留/写入，高分移除。
    try:
        from services.weakpoint_service import delete_weakpoint, record_weakpoint
        questions = json.loads(assignment_row["questions_json"] or "[]")
        tags = [str(q.get("knowledge_tag") or "").strip() for q in questions if q.get("type") == "subjective"]
        for tag in [t for t in tags if t]:
            if score < 60:
                record_weakpoint(student_id, tag, source="assignment_review")
            else:
                delete_weakpoint(student_id, tag)
    except Exception:
        pass

    return {
        "assignment_id": assignment_id,
        "student_id": student_id,
        "score": score,
        "status": "graded",
        "teacher_feedback": feedback or "",
        "reviewed_at": reviewed_at,
    }


def list_student_assignments(student_id: str) -> list[dict[str, Any]]:
    """学生待办 + 已完成作业。"""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM assignments ORDER BY created_at DESC"),
        ).mappings().fetchall()
        sub_rows = conn.execute(
            text("SELECT assignment_id, score, status, submitted_at FROM assignment_submissions WHERE student_id = :sid"),
            {"sid": student_id},
        ).mappings().fetchall()
    submitted = {s["assignment_id"]: s for s in sub_rows}
    result: list[dict[str, Any]] = []
    for row in rows:
        assignee_ids = json.loads(row["assignee_ids_json"] or "[]")
        if student_id not in assignee_ids:
            continue
        item = _row_to_assignment(row)
        sub = submitted.get(row["id"])
        item["submission"] = (
            {"score": sub["score"], "status": sub["status"], "submitted_at": sub["submitted_at"]}
            if sub else None
        )
        result.append(item)
    return result


def submit_assignment(student_id: str, assignment_id: str, answers: list[Any]) -> dict[str, Any]:
    """学生提交作答，自动批改客观题；含主观题则标记待人工评阅。"""
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT * FROM assignments WHERE id = :aid"),
            {"aid": assignment_id},
        ).mappings().fetchone()
        if not row:
            raise LookupError("作业不存在")
        assignee_ids = json.loads(row["assignee_ids_json"] or "[]")
        if student_id not in assignee_ids:
            raise PermissionError("此作业未分配给你")
        existing = conn.execute(
            text("SELECT id FROM assignment_submissions WHERE student_id = :sid AND assignment_id = :aid"),
            {"sid": student_id, "aid": assignment_id},
        ).mappings().fetchone()
        if existing:
            raise ValueError("你已提交过此作业")

    questions = json.loads(row["questions_json"] or "[]")
    objective_total = 0
    objective_correct = 0
    graded_answers: list[dict[str, Any]] = []
    has_subjective = False

    wrong_tags: list[str] = []     # 答错的知识点标签，提交后写入错题本
    correct_tags: list[str] = []   # 答对的，用于从错题本移除（已掌握）

    for idx, question in enumerate(questions):
        q_type = question.get("type", "single_choice")
        student_answer = answers[idx] if idx < len(answers) else None
        entry: dict[str, Any] = {"question_index": idx, "student_answer": student_answer}
        if q_type in OBJECTIVE_TYPES:
            objective_total += 1
            correct = question.get("answer")
            is_correct = _normalize_answer(student_answer) == _normalize_answer(correct)
            if is_correct:
                objective_correct += 1
            entry["is_correct"] = is_correct
            entry["correct_answer"] = correct
            # 收集知识点标签，用于回流错题本
            tag = (question.get("knowledge_tag") or "").strip()
            if tag:
                (correct_tags if is_correct else wrong_tags).append(tag)
        else:
            has_subjective = True
            entry["is_correct"] = None
        graded_answers.append(entry)

    # 分数：客观题占比 ×100；无客观题则待人工评阅（score=None）
    score = round(objective_correct / objective_total * 100, 1) if objective_total else None
    status = "graded" if not has_subjective else "partial"

    submission_id = f"sub_{uuid.uuid4().hex[:12]}"
    submitted_at = now_iso()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO assignment_submissions
                (id, assignment_id, student_id, answers_json, score, status, submitted_at)
                VALUES (:id, :aid, :sid, :answers, :score, :status, :submitted_at)"""),
            {
                "id": submission_id, "aid": assignment_id, "sid": student_id,
                "answers": json.dumps(graded_answers, ensure_ascii=False),
                "score": score, "status": status, "submitted_at": submitted_at,
            },
        )

    # ── 错题回流：答错写入薄弱点，答对尝试移除（已掌握）──────────────────
    try:
        from services.weakpoint_service import delete_weakpoint, record_weakpoint
        for tag in wrong_tags:
            record_weakpoint(student_id, tag, source="assignment")
        for tag in correct_tags:
            delete_weakpoint(student_id, tag)
    except Exception:
        pass  # 不因错题回流失败而影响提交结果
    # ──────────────────────────────────────────────────────────────────────

    return {
        "submission_id": submission_id, "assignment_id": assignment_id,
        "score": score, "status": status,
        "objective_correct": objective_correct, "objective_total": objective_total,
        "has_subjective": has_subjective, "graded_answers": graded_answers,
        "submitted_at": submitted_at,
    }
