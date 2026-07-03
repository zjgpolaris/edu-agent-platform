"""教师布置作业工作流服务

支持教师创建作业（客观题+主观题）、指定学生、学生作答提交与自动批改。
客观题（single_choice / multiple_choice / true_false）自动判分；主观题记录待人工评阅。
表结构见 db/schema.py 的 assignments / assignment_submissions。
"""
from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import inspect, text

from db.engine import get_connection
from student_profile import now_iso

# 自动判分支持的客观题型
OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false"}

# 质检有效性回路：AI 判为合格但真实正确率异常低的客观题 = 质检盲区
BLIND_SPOT_ACCURACY = 40        # 正确率低于此值视为异常低（%）
BLIND_SPOT_MIN_ATTEMPTS = 3     # 作答样本 ≥ 此值才有统计意义


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
        existing_columns = {col["name"] for col in inspect(conn).get_columns("assignment_submissions")}
        if "teacher_feedback" not in existing_columns:
            conn.execute(text("ALTER TABLE assignment_submissions ADD COLUMN teacher_feedback TEXT"))
        if "reviewed_at" not in existing_columns:
            conn.execute(text("ALTER TABLE assignment_submissions ADD COLUMN reviewed_at TEXT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_assignment_submissions_assignment ON assignment_submissions(assignment_id)"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS question_review_flags (
            id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL,
            question_index INTEGER NOT NULL,
            teacher_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(assignment_id, question_index))"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_qrf_assignment ON question_review_flags(assignment_id)"))


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


def _submission_from_row(row: Any) -> dict[str, Any]:
    return {
        "student_id": row["student_id"], "score": row["score"], "status": row["status"],
        "submitted_at": row["submitted_at"], "answers": json.loads(row["answers_json"] or "[]"),
        "teacher_feedback": row.get("teacher_feedback") if hasattr(row, "get") else None,
        "reviewed_at": row.get("reviewed_at") if hasattr(row, "get") else None,
    }


def compute_assignment_insights(
    assignment: dict[str, Any],
    submissions: list[dict[str, Any]],
    *,
    threshold: float = 60.0,
) -> dict[str, Any]:
    """聚合一份作业的讲评洞察：低正确率题、薄弱知识点、低分学生与讲评重点。"""
    questions = assignment.get("questions") or []
    assignee_ids = assignment.get("assignee_ids") or []
    submitted_ids = {s.get("student_id") for s in submissions}
    assignee_count = len(assignee_ids)
    submitted_count = len(submissions)
    score_values = [float(s["score"]) for s in submissions if s.get("score") is not None]
    graded_scores = [float(s["score"]) for s in submissions if s.get("score") is not None and s.get("status") == "graded"]

    q_stats: dict[int, dict[str, Any]] = {}
    tag_stats: dict[str, dict[str, Any]] = {}
    student_missed_tags: dict[str, set[str]] = defaultdict(set)

    def _question(idx: int) -> dict[str, Any]:
        return questions[idx] if 0 <= idx < len(questions) else {}

    def _tag_stat(tag: str) -> dict[str, Any]:
        if tag not in tag_stats:
            tag_stats[tag] = {"knowledge_tag": tag, "wrong_count": 0, "students": set(), "question_indices": set(), "sources": set()}
        return tag_stats[tag]

    for sub in submissions:
        sid = str(sub.get("student_id") or "")
        for ans in sub.get("answers") or []:
            try:
                q_idx = int(ans.get("question_index", -1))
            except Exception:
                q_idx = -1
            q = _question(q_idx)
            if q.get("type") not in OBJECTIVE_TYPES:
                continue
            is_correct = ans.get("is_correct")
            if is_correct not in {True, False}:
                continue
            stat = q_stats.setdefault(q_idx, {
                "question_index": q_idx, "prompt": q.get("prompt", ""), "type": q.get("type", "single_choice"),
                "knowledge_tag": q.get("knowledge_tag"), "attempts": 0, "correct": 0, "wrong": 0,
                "wrong_answers": Counter(),
            })
            stat["attempts"] += 1
            if is_correct:
                stat["correct"] += 1
            else:
                stat["wrong"] += 1
                stat["wrong_answers"][str(ans.get("student_answer"))] += 1
                tag = str(q.get("knowledge_tag") or "").strip()
                if tag:
                    ts = _tag_stat(tag)
                    ts["wrong_count"] += 1
                    ts["students"].add(sid)
                    ts["question_indices"].add(q_idx)
                    ts["sources"].add("objective_wrong")
                    student_missed_tags[sid].add(tag)

    subjective_tags = [str(q.get("knowledge_tag") or "").strip() for q in questions if q.get("type") == "subjective" and q.get("knowledge_tag")]
    for sub in submissions:
        sid = str(sub.get("student_id") or "")
        score = sub.get("score")
        if sub.get("status") == "graded" and score is not None and float(score) < threshold:
            for tag in subjective_tags:
                ts = _tag_stat(tag)
                ts["wrong_count"] += 1
                ts["students"].add(sid)
                ts["sources"].add("review_score")
                student_missed_tags[sid].add(tag)

    lowest_accuracy_questions = []
    for stat in q_stats.values():
        attempts = stat["attempts"] or 1
        accuracy = round(stat["correct"] / attempts * 100)
        q = _question(stat["question_index"])
        predicted_level = (q.get("quality") or {}).get("level")
        lowest_accuracy_questions.append({
            "question_index": stat["question_index"], "prompt": stat["prompt"], "type": stat["type"],
            "knowledge_tag": stat["knowledge_tag"], "attempts": stat["attempts"], "correct": stat["correct"],
            "wrong": stat["wrong"], "accuracy": accuracy, "predicted_level": predicted_level,
            "common_wrong_answers": [{"answer": a, "count": c} for a, c in stat["wrong_answers"].most_common(3)],
        })
    lowest_accuracy_questions.sort(key=lambda x: (x["accuracy"], -x["wrong"], -x["attempts"]))

    # 质检盲区：AI 判为合格（ok/未查）但真实正确率异常低且样本足够的客观题
    quality_blind_spots = [
        {
            "question_index": q["question_index"], "prompt": q["prompt"],
            "accuracy": q["accuracy"], "attempts": q["attempts"],
            "predicted_level": q["predicted_level"],
        }
        for q in lowest_accuracy_questions
        if q["predicted_level"] in (None, "ok")
        and q["accuracy"] < BLIND_SPOT_ACCURACY
        and q["attempts"] >= BLIND_SPOT_MIN_ATTEMPTS
    ][:5]

    top_weak_tags = []
    for stat in tag_stats.values():
        top_weak_tags.append({
            "knowledge_tag": stat["knowledge_tag"], "wrong_count": stat["wrong_count"],
            "student_count": len(stat["students"]), "question_indices": sorted(stat["question_indices"]),
            "sources": sorted(stat["sources"]),
        })
    top_weak_tags.sort(key=lambda x: (-x["student_count"], -x["wrong_count"], x["knowledge_tag"]))

    below_threshold_students = []
    for sub in submissions:
        score = sub.get("score")
        if score is not None and float(score) < threshold:
            sid = str(sub.get("student_id") or "")
            below_threshold_students.append({
                "student_id": sid, "score": score, "status": sub.get("status"),
                "missed_tags": sorted(student_missed_tags.get(sid, set())),
                "needs_review": sub.get("status") != "graded",
            })
    below_threshold_students.sort(key=lambda x: (float(x["score"]), x["student_id"]))

    suggested_reteach_focus = []
    for tag in top_weak_tags[:3]:
        q_nums = [i + 1 for i in tag.get("question_indices", [])]
        q_text = f"，涉及第{'、'.join(str(n) for n in q_nums)}题" if q_nums else ""
        suggested_reteach_focus.append({
            "knowledge_tag": tag["knowledge_tag"], "student_count": tag["student_count"],
            "question_indices": tag.get("question_indices", []),
            "reason": f"{tag['student_count']} 名学生在该知识点暴露问题{q_text}，建议下节课优先讲评。",
        })

    return {
        "submission_rate": {
            "submitted": submitted_count, "assignee_count": assignee_count,
            "percent": round(submitted_count / (assignee_count or 1) * 100),
            "missing_student_ids": [sid for sid in assignee_ids if sid not in submitted_ids],
        },
        "average_score": round(sum(score_values) / len(score_values), 1) if score_values else None,
        "graded_average_score": round(sum(graded_scores) / len(graded_scores), 1) if graded_scores else None,
        "pending_review_count": sum(1 for s in submissions if s.get("status") == "partial"),
        "lowest_accuracy_questions": lowest_accuracy_questions[:5],
        "quality_blind_spots": quality_blind_spots,
        "top_weak_tags": top_weak_tags[:5],
        "below_threshold_students": below_threshold_students,
        "suggested_reteach_focus": suggested_reteach_focus,
    }


def _compact_insights(insights: dict[str, Any]) -> dict[str, Any]:
    return {
        "pending_review_count": insights.get("pending_review_count", 0),
        "top_weak_tags": (insights.get("top_weak_tags") or [])[:3],
        "lowest_accuracy_question": (insights.get("lowest_accuracy_questions") or [None])[0],
        "quality_blind_spot_count": len(insights.get("quality_blind_spots") or []),
        "below_threshold_count": len(insights.get("below_threshold_students") or []),
    }


def list_teacher_assignments(teacher_id: str) -> list[dict[str, Any]]:
    """教师作业列表，附带每份作业的完成率、平均分与讲评洞察摘要。"""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM assignments WHERE teacher_id = :tid ORDER BY created_at DESC"),
            {"tid": teacher_id},
        ).mappings().fetchall()
        assignments = []
        for row in rows:
            full_item = _row_to_assignment(row, include_questions=True)
            subs = conn.execute(
                text("SELECT * FROM assignment_submissions WHERE assignment_id = :aid"),
                {"aid": full_item["id"]},
            ).mappings().fetchall()
            submissions = [_submission_from_row(s) for s in subs]
            insights = compute_assignment_insights(full_item, submissions)
            flag_rows = conn.execute(
                text("SELECT question_index FROM question_review_flags WHERE assignment_id = :aid"),
                {"aid": full_item["id"]},
            ).mappings().fetchall()
            reviewed_idx = {int(r["question_index"]) for r in flag_rows}
            open_blind_spots = sum(
                1 for b in insights.get("quality_blind_spots") or []
                if b["question_index"] not in reviewed_idx
            )
            item = _row_to_assignment(row, include_questions=False)
            item["submitted_count"] = len(submissions)
            item["assignee_count"] = len(item["assignee_ids"])
            item["completion_rate"] = insights["submission_rate"]["percent"]
            item["average_score"] = insights["average_score"]
            item.update(_compact_insights(insights))
            item["open_blind_spot_count"] = open_blind_spots
            assignments.append(item)
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
    submissions = [_submission_from_row(s) for s in subs]
    insights = compute_assignment_insights(assignment, submissions)
    review_flags = get_question_review_flags(assignment_id)
    reviewed_idx = set(review_flags.keys())
    open_blind_spot_count = sum(
        1 for b in insights.get("quality_blind_spots") or []
        if b["question_index"] not in reviewed_idx
    )
    return {
        "assignment": assignment,
        "submissions": submissions,
        "insights": insights,
        "review_flags": {str(k): v for k, v in review_flags.items()},
        "open_blind_spot_count": open_blind_spot_count,
    }


VALID_REVIEW_VERDICTS = {"bad_question", "not_mastered"}


def get_question_review_flags(assignment_id: str) -> dict[int, dict[str, Any]]:
    """返回一份作业已复核的题目标记，按 question_index 索引。"""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT question_index, verdict, note, created_at FROM question_review_flags WHERE assignment_id = :aid"),
            {"aid": assignment_id},
        ).mappings().fetchall()
    return {
        int(r["question_index"]): {"verdict": r["verdict"], "note": r["note"], "created_at": r["created_at"]}
        for r in rows
    }


def get_bad_question_examples(teacher_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """取某教师历史上人工判定为『题目有问题』的题干与备注，供语义质检 few-shot 反例。

    仅本教师、按复核时间倒序、去重题干；无数据返回 []。
    """
    _ensure_tables()
    limit = max(1, min(int(limit), 20))
    # SQL 层限制行数，避免全量加载 questions_json 大字段（limit 已在上方钳位至 [1,20]）
    with get_connection() as conn:
        rows = conn.execute(
            text("""SELECT f.question_index, f.note, a.questions_json
                FROM question_review_flags f
                JOIN assignments a ON a.id = f.assignment_id
                WHERE f.teacher_id = :tid AND f.verdict = 'bad_question'
                ORDER BY f.created_at DESC
                LIMIT :lim"""),
            {"tid": teacher_id, "lim": limit * 4},  # 多取几条以备去重后仍够用
        ).mappings().fetchall()

    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        try:
            questions = json.loads(r["questions_json"] or "[]")
            q_idx = int(r["question_index"])  # NULL → TypeError，统一在此捕获
        except (ValueError, TypeError):
            continue
        if q_idx < 0 or q_idx >= len(questions):
            continue
        prompt = str(questions[q_idx].get("prompt") or "").strip()
        if not prompt or prompt in seen:
            continue
        seen.add(prompt)
        examples.append({"prompt": prompt, "note": (r["note"] or "").strip() or None})
        if len(examples) >= limit:
            break
    return examples


def record_question_review_flag(
    teacher_id: str,
    assignment_id: str,
    question_index: int,
    verdict: str,
    note: str | None = None,
) -> dict[str, Any]:
    """教师对一道（盲区）题给出复核判定：bad_question=题目有问题，not_mastered=学生没掌握。"""
    _ensure_tables()
    verdict = (verdict or "").strip()
    if verdict not in VALID_REVIEW_VERDICTS:
        raise ValueError("verdict 必须是 bad_question 或 not_mastered")
    try:
        q_idx = int(question_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("question_index 必须是整数") from exc

    with get_connection() as conn:
        row = conn.execute(
            text("SELECT teacher_id, questions_json FROM assignments WHERE id = :aid"),
            {"aid": assignment_id},
        ).mappings().fetchone()
        if not row:
            raise LookupError("作业不存在")
        if row["teacher_id"] != teacher_id:
            raise PermissionError("无权复核此作业")
        question_count = len(json.loads(row["questions_json"] or "[]"))
        if q_idx < 0 or q_idx >= question_count:
            raise LookupError("题目序号越界")

        created_at = now_iso()
        flag_id = f"qrf_{uuid.uuid4().hex[:12]}"
        # UPSERT：先删同 (assignment, index) 再插，避免方言差异
        conn.execute(
            text("DELETE FROM question_review_flags WHERE assignment_id = :aid AND question_index = :qi"),
            {"aid": assignment_id, "qi": q_idx},
        )
        conn.execute(
            text("""INSERT INTO question_review_flags
                (id, assignment_id, question_index, teacher_id, verdict, note, created_at)
                VALUES (:id, :aid, :qi, :tid, :verdict, :note, :created_at)"""),
            {"id": flag_id, "aid": assignment_id, "qi": q_idx, "tid": teacher_id,
             "verdict": verdict, "note": (note or "").strip() or None, "created_at": created_at},
        )
    return {
        "assignment_id": assignment_id, "question_index": q_idx,
        "verdict": verdict, "note": (note or "").strip() or None, "created_at": created_at,
    }


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

    # 主观题评阅后按整份作业分数粗粒度回流知识点：低分强化薄弱点，高分累积掌握证据。
    try:
        from services.weakpoint_service import record_correct_evidence, record_weakpoint
        questions = json.loads(assignment_row["questions_json"] or "[]")
        tags = [str(q.get("knowledge_tag") or "").strip() for q in questions if q.get("type") == "subjective"]
        for tag in [t for t in tags if t]:
            if score < 60:
                record_weakpoint(student_id, tag, source="assignment_review")
            else:
                record_correct_evidence(student_id, tag)
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


def get_teacher_badges(teacher_id: str) -> dict[str, int]:
    """教师侧边栏徽标：待评阅主观题数、低分学生数（复用列表聚合，确定性）。"""
    assignments = list_teacher_assignments(teacher_id)
    return {
        "pending_review": sum(int(a.get("pending_review_count") or 0) for a in assignments),
        "below_threshold": sum(int(a.get("below_threshold_count") or 0) for a in assignments),
        "blind_spots_to_review": sum(int(a.get("open_blind_spot_count") or 0) for a in assignments),
    }


def get_student_badges(student_id: str, today: str) -> dict[str, int]:
    """学生侧边栏徽标：未提交作业数、临近/逾期未交数（due_date<=today）。"""
    assignments = list_student_assignments(student_id)
    pending = 0
    due_soon = 0
    for a in assignments:
        if a.get("submission") is not None:
            continue
        pending += 1
        due = (a.get("due_date") or "").strip()
        if due and due <= today:
            due_soon += 1
    return {"pending_assignments": pending, "due_soon": due_soon}


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

    # ── 错题回流：答错写入薄弱点，答对累积掌握证据（连对达阈值才移除）──────
    try:
        from services.weakpoint_service import record_correct_evidence, record_weakpoint
        for tag in wrong_tags:
            record_weakpoint(student_id, tag, source="assignment")
        for tag in correct_tags:
            record_correct_evidence(student_id, tag)
    except Exception:
        pass  # 不因错题回流失败而影响提交结果
    # ──────────────────────────────────────────────────────────────────────

    # ── 今日复习 session 追加新弱点（不阻塞提交）────────────────────────
    if wrong_tags:
        try:
            from services.review_service import merge_new_weakpoints_to_today
            from datetime import date
            merge_new_weakpoints_to_today(student_id, wrong_tags, date.today().isoformat())
        except Exception:
            pass
    # ──────────────────────────────────────────────────────────────────────

    return {
        "submission_id": submission_id, "assignment_id": assignment_id,
        "score": score, "status": status,
        "objective_correct": objective_correct, "objective_total": objective_total,
        "has_subjective": has_subjective, "graded_answers": graded_answers,
        "submitted_at": submitted_at,
        "wrong_tags": wrong_tags,    # 答错知识点，前端用于引导复习
        "correct_tags": correct_tags,
    }
