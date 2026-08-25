"""自适应复习调度服务"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import inspect, text

from db.engine import get_connection
from student_profile import (
    LearningEvent,
    init_db as init_profile_db,
    now_iso,
    record_learning_event_with_connection,
)
from services.history_review_question import (
    QUALITY_CONTRACT_VERSION,
    build_curated_review_question,
    build_grounded_review_question,
    is_usable_choice_question,
    public_review_question,
)
from services.weakpoint_service import apply_weakpoint_evidence_with_connection, get_weakpoints
from services.review_mastery_service import (
    add_retention_interval,
    ensure_review_mastery_schema,
    evidence_rows_with_connection,
    get_mastery_state_with_connection,
    list_retention_states_with_connection,
    request_hash,
    set_mastery_state_with_connection,
    stable_chain_id,
    validate_retention_chain,
)
from services.variant_service import should_use_variant


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS review_sessions (
            id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            date TEXT NOT NULL,
            tasks_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            last_idempotency_key TEXT,
            last_request_hash TEXT,
            last_response_json TEXT,
            UNIQUE(student_id, date))"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_review_sessions_student ON review_sessions(student_id)"))
        if conn.dialect.name == "sqlite":
            columns = {column["name"] for column in inspect(conn).get_columns("review_sessions")}
            additions = {
                "revision": "INTEGER NOT NULL DEFAULT 0",
                "status": "TEXT NOT NULL DEFAULT 'active'",
                "last_idempotency_key": "TEXT",
                "last_request_hash": "TEXT",
                "last_response_json": "TEXT",
            }
            for name, ddl in additions.items():
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE review_sessions ADD COLUMN {name} {ddl}"))
        ensure_review_mastery_schema(conn)


def _decay_weight(last_wrong_at: str) -> float:
    """Returns 0.1–1.0 based on how many days since last wrong answer."""
    try:
        ts = time.strptime(last_wrong_at[:19], "%Y-%m-%dT%H:%M:%S")
        days = (time.time() - time.mktime(ts)) / 86400
    except Exception:
        return 1.0
    if days < 1: return 0.1
    if days < 3: return 0.4
    if days < 7: return 0.7
    return 1.0


class ReviewConflictError(ValueError):
    """The same review task was already answered with another option."""

    def __init__(self, message: str, *, code: str = "review_conflict") -> None:
        super().__init__(message)
        self.code = code


def _generate_question(
    tag: str,
    *,
    is_variant: bool = False,
    seed_question: dict[str, Any] | None = None,
    target_difficulty: str = "easy",
    selection_seed: str = "",
    task_role: str | None = None,
    excluded_assessment_ids: set[str] | None = None,
    excluded_fingerprints: set[str] | None = None,
) -> dict[str, Any]:
    curated = build_curated_review_question(
        tag,
        is_variant=is_variant,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
        task_role=task_role,
        excluded_assessment_ids=excluded_assessment_ids,
        excluded_fingerprints=excluded_fingerprints,
    )
    if curated is not None:
        return curated
    # 当前只有审定内容包能同时证明题干、答案和干扰项质量。教材段落可用于
    # 讲解或后续出题草稿，但不能自动证明一道选择题达到学生发布标准。
    return build_grounded_review_question(
        tag,
        is_variant=is_variant,
        seed_question=seed_question,
        target_difficulty=target_difficulty,
        selection_seed=selection_seed,
    )


def get_today_session(
    student_id: str,
    today: str,
    *,
    hydrate: bool = True,
    at: str | None = None,
) -> dict | None:
    """读取今日复习 session。

    hydrate=True（默认，复习页）：从审定题包补齐占位题并升级不合格旧题。
    hydrate=False（徽标轮询等只需计数的场景）：不做题目升级，直接返回已有任务。
    """
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("""SELECT id, tasks_json, completed, total, revision, status
                FROM review_sessions WHERE student_id=:sid AND date=:date"""),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
    if not row:
        return None
    session_id = str(row["id"])
    tasks = json.loads(row["tasks_json"])
    if hydrate:
        tasks = _hydrate_pending_tasks(student_id, today, tasks, session_id=session_id)
        tasks, revision = _attach_due_retention_tasks(
            student_id, today, session_id, tasks, int(row.get("revision") or 0), at=at
        )
    else:
        revision = int(row.get("revision") or 0)
    with get_connection() as conn:
        _, scheduled = list_retention_states_with_connection(conn, student_id, at=at)
    scoreable = [task for task in tasks if not is_unusable_question(task)]
    return {
        "id": session_id,
        "date": today,
        "completed": (
            sum(1 for task in scoreable if task.get("done")) if hydrate else int(row["completed"] or 0)
        ),
        "total": len(scoreable) if hydrate else int(row["total"] or 0),
        "tasks": tasks,
        "revision": revision,
        "status": row.get("status") or "active",
        "scheduled_reviews": scheduled,
    }


def is_unusable_question(task: dict[str, Any]) -> bool:
    """判断一道已落库的复习题是否无法作答（占位、生成失败或选项残缺）。

    历史上生成失败的题目会被直接写库，因此读取时必须重新判定，
    不能只信任写入时的标记。
    """
    if task.get("pending_generate") or task.get("_generation_failed"):
        return True
    if int(task.get("quality_contract_version") or 0) != QUALITY_CONTRACT_VERSION:
        return True
    if task.get("quality_status") != "verified":
        return True
    return not is_usable_choice_question(task)


def _adaptive_profile(wp: dict[str, Any]) -> tuple[bool, str, str]:
    wrong_count = int(wp.get("wrong_count") or 0)
    correct_streak = int(wp.get("correct_streak") or 0)
    if wrong_count < 4 and (should_use_variant(wrong_count) or correct_streak >= 1):
        message = (
            "已完成一次基础辨析，先独立作答，再用对照材料确认是否真正理解。"
            if correct_streak >= 1
            else "这个知识点近期反复出错，先独立作答，再用对照材料检查理解。"
        )
        return True, "medium", message
    message = (
        "这个知识点错误较多，先用基础辨析稳住核心史实。"
        if wrong_count >= 4
        else "根据近期错题安排一道基础辨析。"
    )
    return False, "easy", message


def _task_effect_key(session_id: str, task: dict[str, Any]) -> str:
    role = str(task.get("task_role") or "retrieval")
    task_id = str(task.get("question_id") or "unknown")
    return f"review:{session_id}:{task_id}:{role}:{task_id}"


def _decorate_task(
    task: dict[str, Any],
    *,
    student_id: str,
    session_id: str,
    task_role: str,
    parent_task: dict[str, Any] | None = None,
    retrieval_evidence_key: str | None = None,
    due_at: str | None = None,
) -> dict[str, Any]:
    task["task_role"] = task_role
    task["phase"] = "answering"
    task["feedback_acknowledged"] = False
    task["parent_task_id"] = parent_task.get("question_id") if parent_task else None
    task["due_at"] = due_at
    if task_role == "retrieval":
        retrieval_key = _task_effect_key(session_id, task)
    else:
        retrieval_key = retrieval_evidence_key or str((parent_task or {}).get("retrieval_evidence_key") or "")
    if retrieval_key:
        task["retrieval_evidence_key"] = retrieval_key
        task["evidence_chain_id"] = stable_chain_id(student_id, str(task.get("tag") or ""), retrieval_key)
    return task


def _hydrate_pending_tasks(
    student_id: str,
    today: str,
    tasks: list[dict],
    *,
    session_id: str,
) -> list[dict]:
    """为无法作答的未答题目按需生成真实题目并落库。

    覆盖两类：作业错题追加的 pending_generate 占位题，以及早先已写库但
    不满足质量合同的题。缺少审定题时保留 blocked 状态，不向学生发布。
    """
    weakpoints = {item["knowledge_tag"]: item for item in get_weakpoints(student_id)}
    changed = False
    for index, task in enumerate(tasks):
        if task.get("done"):
            continue
        wp = weakpoints.get(str(task.get("tag") or ""))
        if wp:
            is_variant, target_difficulty, adaptive_message = _adaptive_profile(wp)
        else:
            is_variant = bool(task.get("is_variant"))
            target_difficulty = str(task.get("target_difficulty") or task.get("difficulty") or ("medium" if is_variant else "easy"))
            adaptive_message = str(task.get("adaptive_message") or "")
        role = str(task.get("task_role") or "retrieval")
        adaptive_mismatch = bool(wp) and role == "retrieval" and (
            bool(task.get("is_variant")) != is_variant
            or str(task.get("difficulty") or "") != target_difficulty
        )
        contract_missing = not task.get("task_role") or not task.get("assessment_fingerprint")
        if not is_unusable_question(task) and not adaptive_mismatch and not contract_missing:
            continue
        generated = _generate_question(
            str(task.get("tag") or ""),
            is_variant=is_variant,
            seed_question=task,
            target_difficulty=target_difficulty,
            selection_seed=f"{student_id}:{today}:{index}",
            task_role=role,
        )
        replacement = {
            **generated,
            **({"adaptive_message": adaptive_message} if adaptive_message else {}),
        }
        _decorate_task(
            replacement,
            student_id=student_id,
            session_id=session_id,
            task_role=role,
            retrieval_evidence_key=str(task.get("retrieval_evidence_key") or "") or None,
            due_at=task.get("due_at"),
        )
        if replacement != task:
            task.clear()
            task.update(replacement)
            changed = True
    if changed:
        with get_connection() as conn:
            conn.execute(
                text("UPDATE review_sessions SET tasks_json=:tasks WHERE student_id=:sid AND date=:date"),
                {"tasks": json.dumps(tasks, ensure_ascii=False), "sid": student_id, "date": today},
            )
    return tasks


def _pick_question(student_id: str, today: str, wp: dict[str, Any]) -> dict[str, Any]:
    """Pick a reviewed assessment using the student's current evidence state."""
    tag = wp["knowledge_tag"]
    is_variant, target_difficulty, adaptive_message = _adaptive_profile(wp)
    task = _generate_question(
        tag,
        is_variant=is_variant,
        target_difficulty=target_difficulty,
        selection_seed=f"{student_id}:{today}:{tag}",
        task_role="retrieval",
    )
    task["adaptive_message"] = adaptive_message
    return task


def _build_retention_task(
    student_id: str,
    today: str,
    session_id: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    with get_connection() as conn:
        evidence = evidence_rows_with_connection(conn, [
            state.get("retrieval_evidence_key"), state.get("verification_evidence_key"),
        ])
    excluded_ids = {str(row.get("assessment_id")) for row in evidence if row.get("assessment_id")}
    excluded_prints = {
        str(row.get("assessment_fingerprint")) for row in evidence if row.get("assessment_fingerprint")
    }
    task = _generate_question(
        str(state.get("knowledge_tag") or ""),
        target_difficulty="medium",
        selection_seed=f"{student_id}:{today}:{state.get('knowledge_tag')}:retention",
        task_role="retention",
        excluded_assessment_ids=excluded_ids,
        excluded_fingerprints=excluded_prints,
    )
    if is_unusable_question(task):
        return None
    return _decorate_task(
        task,
        student_id=student_id,
        session_id=session_id,
        task_role="retention",
        retrieval_evidence_key=str(state.get("retrieval_evidence_key") or "") or None,
        due_at=state.get("retention_due_at"),
    )


def _attach_due_retention_tasks(
    student_id: str,
    today: str,
    session_id: str,
    tasks: list[dict[str, Any]],
    revision: int,
    *,
    at: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    with get_connection() as conn:
        due_states, _ = list_retention_states_with_connection(conn, student_id, at=at)
    existing_tags = {
        str(task.get("tag") or "") for task in tasks if task.get("task_role") == "retention"
    }
    additions: list[dict[str, Any]] = []
    blocked_states: list[dict[str, Any]] = []
    for state in due_states:
        if state["knowledge_tag"] in existing_tags:
            continue
        task = _build_retention_task(student_id, today, session_id, state)
        if task is None:
            blocked_states.append(state)
        else:
            additions.append(task)
    if not additions and not blocked_states:
        return tasks, revision
    merged = [*additions, *tasks]
    with get_connection() as conn:
        for state in blocked_states:
            set_mastery_state_with_connection(
                conn,
                student_id=student_id,
                knowledge_tag=state["knowledge_tag"],
                status="content_blocked",
                retrieval_evidence_key=state.get("retrieval_evidence_key"),
                verification_evidence_key=state.get("verification_evidence_key"),
                retention_due_at=state.get("retention_due_at"),
            )
        if additions:
            updated = conn.execute(text("""UPDATE review_sessions SET
                tasks_json=:tasks, total=:total, revision=revision+1
                WHERE id=:session_id AND revision=:revision"""), {
                "tasks": json.dumps(merged, ensure_ascii=False),
                "total": len(merged),
                "session_id": session_id,
                "revision": revision,
            })
            if updated.rowcount == 1:
                return merged, revision + 1
    return tasks, revision


def create_today_session(student_id: str, today: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    with get_connection() as conn:
        due_states, scheduled_states = list_retention_states_with_connection(conn, student_id)
        active_rows = conn.execute(
            text("""SELECT knowledge_tag FROM review_mastery_state
                WHERE student_id=:sid AND status IN ('awaiting_feedback','verification_pending','retention_due')"""),
            {"sid": student_id},
        ).scalars().all()
    active_tags = set(active_rows)
    top = sorted(
        [wp for wp in weakpoints if wp["knowledge_tag"] not in active_tags],
        key=lambda w: w["wrong_count"] * _decay_weight(w["last_wrong_at"]),
        reverse=True,
    )[: max(0, 8 - len(due_states))]
    session_id = str(uuid.uuid4())
    tasks = [_pick_question(student_id, today, w) for w in top]
    for task in tasks:
        _decorate_task(task, student_id=student_id, session_id=session_id, task_role="retrieval")
    for state in due_states:
        task = _build_retention_task(student_id, today, session_id, state)
        if task is not None:
            tasks.insert(0, task)
    # 生成失败的题标记为待重试，下次打开复习页会重新生成，而不是固化成占位题
    for t in tasks:
        if is_unusable_question(t):
            t["pending_generate"] = True
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions (id, student_id, date, tasks_json, completed, total, created_at)
                 VALUES (:id, :sid, :date, :tasks, 0, :total, :ts)
                 ON CONFLICT(student_id, date) DO NOTHING"""),
            {"id": session_id, "sid": student_id, "date": today,
             "tasks": json.dumps(tasks, ensure_ascii=False), "total": len(tasks), "ts": now_iso()},
        )
    return {
        "id": session_id,
        "date": today,
        "completed": 0,
        "total": len(tasks),
        "tasks": tasks,
        "revision": 0,
        "status": "active",
        "scheduled_reviews": scheduled_states,
    }


def public_review_session(session: dict[str, Any]) -> dict[str, Any]:
    """Serialize a review session without pre-disclosing answers or feedback."""
    public_tasks: list[dict[str, Any]] = []
    blocked_tags: list[str] = []
    for task_index, task in enumerate(session.get("tasks") or []):
        if is_unusable_question(task):
            blocked_tags.append(str(task.get("tag") or "历史知识点"))
            continue
        reveal_feedback = bool(
            task.get("done")
            and task.get("task_role") == "retrieval"
            and not task.get("feedback_acknowledged")
        )
        public = public_review_question(task, reveal_answer=reveal_feedback)
        public["task_index"] = task_index
        public["session_revision"] = int(session.get("revision") or 0)
        public["phase"] = "awaiting_feedback" if reveal_feedback else str(task.get("phase") or "answering")
        public_tasks.append(public)
    scheduled_reviews = [
        {
            "knowledge_tag": str(item.get("knowledge_tag") or "历史知识点"),
            "available_at": item.get("retention_due_at"),
            "message": "明天再确认一次，看看是否真正记住。",
        }
        for item in session.get("scheduled_reviews") or []
    ]
    return {
        "session_id": session.get("id"),
        "date": session.get("date"),
        "completed": sum(1 for task in public_tasks if task.get("done")),
        "total": len(public_tasks),
        "tasks": public_tasks,
        "blocked_count": len(blocked_tags),
        "blocked_tags": blocked_tags,
        "session_revision": int(session.get("revision") or 0),
        "status": session.get("status") or "active",
        "scheduled_reviews": scheduled_reviews,
    }


def merge_new_weakpoints_to_today(student_id: str, new_tags: list[str], today: str) -> None:
    """作业提交后，将新增错误知识点追加到今日复习 session（若 session 已存在）。

    - 若今日 session 不存在：忽略（用户主动打开复习页时会创建）。
    - 若 session 已存在：只追加尚未在 session 中的 tag，避免重复。
    - 不调用 LLM，只生成占位任务；题目在用户打开复习页时按需生成即可。
    """
    if not new_tags:
        return
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            text("SELECT tasks_json, total FROM review_sessions WHERE student_id=:sid AND date=:date"),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
        if not row:
            return  # 今日 session 尚未创建，跳过
        tasks: list[dict] = json.loads(row["tasks_json"])
        existing_tags = {t.get("tag") for t in tasks}
        additions = [
            {"tag": tag, "question": f"关于「{tag}」的复习题", "options": [], "answer": "", "explanation": "", "done": False, "correct": None, "pending_generate": True}
            for tag in new_tags if tag not in existing_tags
        ]
        if not additions:
            return
        merged = tasks + additions
        conn.execute(
            text("UPDATE review_sessions SET tasks_json=:tasks, total=:total WHERE student_id=:sid AND date=:date"),
            {"tasks": json.dumps(merged, ensure_ascii=False), "total": len(merged), "sid": student_id, "date": today},
        )


def _submit_answer_once(
    student_id: str,
    today: str,
    task_idx: int,
    selected_answer: str,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
    *,
    occurred_at: str | None = None,
    fault_hook: Any | None = None,
) -> dict:
    selected = str(selected_answer or "").strip().upper()[:1]
    if selected not in "ABCD":
        raise ValueError("selected_answer must be A, B, C or D")
    _ensure_table()
    init_profile_db()
    timestamp = occurred_at or now_iso()
    idem_key = str(idempotency_key or f"legacy:{student_id}:{today}:{task_idx}:{selected}")
    req_hash = request_hash("submit", {"task_index": task_idx, "selected_answer": selected})

    def checkpoint(name: str) -> None:
        if fault_hook is not None:
            fault_hook(name)

    with get_connection() as conn:
        row = conn.execute(
            text("""SELECT id, tasks_json, completed, total, revision,
                last_idempotency_key, last_request_hash, last_response_json
                FROM review_sessions WHERE student_id=:sid AND date=:date"""),
            {"sid": student_id, "date": today},
        ).mappings().fetchone()
        if not row:
            raise ValueError("review session not found")
        if row.get("last_idempotency_key") == idem_key:
            if row.get("last_request_hash") != req_hash:
                raise ReviewConflictError("idempotency key was used for another request", code="idempotency_payload_conflict")
            if row.get("last_response_json"):
                return {**json.loads(row["last_response_json"]), "replayed": True}
        revision = int(row.get("revision") or 0)
        if expected_revision is not None and expected_revision != revision:
            raise ReviewConflictError("review session revision is stale", code="stale_review_revision")
        original_tasks_json = row["tasks_json"]
        tasks = json.loads(original_tasks_json)
        if not 0 <= task_idx < len(tasks):
            raise ValueError("invalid task_index")
        task = tasks[task_idx]
        if is_unusable_question(task):
            raise ValueError("review question is not answerable")
        if task.get("done"):
            if task.get("selected_answer") != selected:
                raise ReviewConflictError("review task already answered with another option", code="idempotency_payload_conflict")
            scoreable = [item for item in tasks if not is_unusable_question(item)]
            return {
                "completed": sum(1 for item in scoreable if item.get("done")),
                "total": len(scoreable),
                "is_correct": bool(task.get("correct")),
                "replayed": True,
                "task": public_review_question(task, reveal_answer=True),
                "session_revision": revision,
            }

        role = str(task.get("task_role") or "retrieval")
        if role not in {"retrieval", "verification", "retention"}:
            raise ValueError("invalid_review_transition")
        tag = str(task.get("tag") or "").strip()
        question_id = str(task.get("question_id") or f"task-{task_idx}")
        fingerprint = str(task.get("assessment_fingerprint") or "")
        if not tag or not fingerprint:
            raise ValueError("review question has no stable evidence identity")
        state = get_mastery_state_with_connection(conn, student_id, tag)
        if role == "verification":
            if not state or state.get("status") != "verification_pending":
                raise ValueError("invalid_review_transition")
            prior = evidence_rows_with_connection(conn, [state.get("retrieval_evidence_key")])
            if not prior or question_id == prior[0].get("assessment_id") or fingerprint == prior[0].get("assessment_fingerprint"):
                raise ReviewConflictError("verification assessment is not independent", code="evidence_chain_conflict")
        elif role == "retention":
            if not state:
                raise ReviewConflictError("retention evidence chain is missing", code="evidence_chain_conflict")
            chain_rows = evidence_rows_with_connection(conn, [
                state.get("retrieval_evidence_key"), state.get("verification_evidence_key"),
            ])
            try:
                validate_retention_chain(
                    state=state,
                    evidence_rows=chain_rows,
                    retention_assessment_id=question_id,
                    retention_fingerprint=fingerprint,
                    occurred_at=timestamp,
                )
            except ValueError as exc:
                code = str(exc)
                raise ReviewConflictError(code, code=code) from exc

        answer = str(task.get("answer") or "").strip().upper()[:1]
        is_correct = selected == answer
        feedback = task.get("option_feedback") if isinstance(task.get("option_feedback"), dict) else {}
        task.update(
            done=True,
            correct=is_correct,
            selected_answer=selected,
            selected_feedback=str(feedback.get(selected) or task.get("explanation") or "").strip(),
        )
        completed = sum(1 for t in tasks if t.get("done"))
        if role == "retention":
            chain_id = str(task.get("evidence_chain_id") or "")
            effect_key = f"review:{chain_id}:retention:{question_id}"
        else:
            effect_key = _task_effect_key(str(row["id"]), task)
        parent_key = None
        if role == "verification":
            parent_key = str(state.get("retrieval_evidence_key") or "")
        elif role == "retention":
            parent_key = str(state.get("verification_evidence_key") or "")
        correct_types = {
            "retrieval": "retrieval_correct",
            "verification": "independent_correct",
            "retention": "retention_correct",
        }
        evidence_type = correct_types[role] if is_correct else "wrong"
        apply_weakpoint_evidence_with_connection(
            conn,
            evidence_key=effect_key,
            student_id=student_id,
            knowledge_tag=tag,
            evidence_type=evidence_type,
            source_feature="review",
            source_session_id=str(row["id"]),
            assessment_id=question_id,
            evidence_stage=role,
            assessment_fingerprint=fingerprint,
            parent_evidence_key=parent_key,
            eligible_at=state.get("retention_due_at") if state else None,
            occurred_at=timestamp,
            mastery_eligible=role == "retention" and is_correct,
        )
        checkpoint("after_weakpoint_evidence")

        phase = "awaiting_feedback"
        mastery: dict[str, str] | None = None
        available_at: str | None = None
        if role == "retrieval":
            task["phase"] = "awaiting_feedback"
            task["retrieval_evidence_key"] = effect_key
            task["evidence_chain_id"] = stable_chain_id(student_id, tag, effect_key)
            set_mastery_state_with_connection(
                conn,
                student_id=student_id,
                knowledge_tag=tag,
                status="awaiting_feedback",
                retrieval_evidence_key=effect_key,
                updated_at=timestamp,
            )
        elif role == "verification":
            task["phase"] = "answered"
            if is_correct:
                available_at = add_retention_interval(timestamp)
                phase = "retention_scheduled"
                mastery = {
                    "status": "not_yet_retained",
                    "student_message": "这次已经理解，明天再确认一次是否真正记住。",
                }
                set_mastery_state_with_connection(
                    conn,
                    student_id=student_id,
                    knowledge_tag=tag,
                    status="retention_due",
                    retrieval_evidence_key=state.get("retrieval_evidence_key"),
                    verification_evidence_key=effect_key,
                    retention_due_at=available_at,
                    updated_at=timestamp,
                )
            else:
                phase = "needs_support"
                mastery = {"status": "needs_support", "student_message": "这个知识点还需要再巩固。"}
                set_mastery_state_with_connection(
                    conn,
                    student_id=student_id,
                    knowledge_tag=tag,
                    status="needs_support",
                    retrieval_evidence_key=state.get("retrieval_evidence_key"),
                    updated_at=timestamp,
                )
        else:
            task["phase"] = "answered"
            if is_correct:
                phase = "retention_verified"
                mastery = {
                    "status": "retention_verified",
                    "student_message": "经过间隔复测，你已经稳定掌握这个知识点。",
                }
                set_mastery_state_with_connection(
                    conn,
                    student_id=student_id,
                    knowledge_tag=tag,
                    status="retention_verified",
                    retrieval_evidence_key=state.get("retrieval_evidence_key"),
                    verification_evidence_key=state.get("verification_evidence_key"),
                    retention_evidence_key=effect_key,
                    retention_due_at=state.get("retention_due_at"),
                    updated_at=timestamp,
                )
            else:
                phase = "needs_retrieval"
                mastery = {"status": "needs_retrieval", "student_message": "隔一段时间后还不稳定，重新巩固一次。"}
                set_mastery_state_with_connection(
                    conn,
                    student_id=student_id,
                    knowledge_tag=tag,
                    status="needs_retrieval",
                    updated_at=timestamp,
                )
        checkpoint("after_mastery_state")

        event_type = {
            "retrieval": "review_retrieval_answered",
            "verification": "review_verification_answered",
            "retention": "review_retention_answered",
        }[role]
        record_learning_event_with_connection(
            conn,
            LearningEvent(
                student_id=student_id,
                session_id=str(row["id"]),
                feature="review",
                event_type=event_type,
                topic=tag,
                score=1.0 if is_correct else 0.0,
                success=is_correct,
                metadata={
                    "assessment_id": question_id,
                    "task_role": role,
                    "difficulty": task.get("difficulty"),
                    "cognitive_action": task.get("cognitive_action"),
                },
            ),
            effect_key=f"{effect_key}:event",
        )
        checkpoint("after_learning_event")

        next_revision = revision + 1
        response: dict[str, Any] = {
            "completed": sum(1 for item in tasks if item.get("done") and not is_unusable_question(item)),
            "total": len([item for item in tasks if not is_unusable_question(item)]),
            "is_correct": is_correct,
            "replayed": False,
            "phase": phase,
            "task": public_review_question(task, reveal_answer=True),
            "session_revision": next_revision,
        }
        if role == "retrieval":
            response["next_action"] = {
                "type": "acknowledge_feedback",
                "label": "看完了，做一道验证题",
            }
        if mastery:
            response["mastery"] = mastery
        if available_at:
            response["available_at"] = available_at
        updated = conn.execute(text("""UPDATE review_sessions SET
            tasks_json=:tasks, completed=:completed, total=:total, revision=revision+1,
            last_idempotency_key=:idempotency_key, last_request_hash=:request_hash,
            last_response_json=:response
            WHERE id=:session_id AND revision=:revision AND tasks_json=:expected_tasks"""), {
            "tasks": json.dumps(tasks, ensure_ascii=False),
            "completed": response["completed"],
            "total": response["total"],
            "idempotency_key": idem_key,
            "request_hash": req_hash,
            "response": json.dumps(response, ensure_ascii=False),
            "session_id": row["id"],
            "revision": revision,
            "expected_tasks": original_tasks_json,
        })
        if updated.rowcount != 1:
            raise ReviewConflictError("review task changed while submitting", code="stale_review_revision")
        checkpoint("after_session_cas")
    return response


def _replayed_transition_response(
    student_id: str,
    today: str,
    *,
    idempotency_key: str,
    expected_request_hash: str,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(text("""SELECT last_idempotency_key, last_request_hash,
            last_response_json FROM review_sessions WHERE student_id=:sid AND date=:date"""),
            {"sid": student_id, "date": today}).mappings().first()
    if not row or row.get("last_idempotency_key") != idempotency_key:
        return None
    if row.get("last_request_hash") != expected_request_hash:
        raise ReviewConflictError(
            "idempotency key was used for another request",
            code="idempotency_payload_conflict",
        )
    if not row.get("last_response_json"):
        return None
    return {**json.loads(row["last_response_json"]), "replayed": True}


def submit_answer(
    student_id: str,
    today: str,
    task_idx: int,
    selected_answer: str,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
    *,
    occurred_at: str | None = None,
    fault_hook: Any | None = None,
) -> dict:
    idem_key = str(idempotency_key or f"legacy:{student_id}:{today}:{task_idx}:{str(selected_answer).upper()[:1]}")
    req_hash = request_hash("submit", {
        "task_index": task_idx,
        "selected_answer": str(selected_answer or "").strip().upper()[:1],
    })
    try:
        return _submit_answer_once(
            student_id,
            today,
            task_idx,
            selected_answer,
            expected_revision,
            idem_key,
            occurred_at=occurred_at,
            fault_hook=fault_hook,
        )
    except ReviewConflictError as exc:
        replay = _replayed_transition_response(
            student_id,
            today,
            idempotency_key=idem_key,
            expected_request_hash=req_hash,
        )
        if replay is not None:
            return replay
        raise


def _advance_after_feedback_once(
    student_id: str,
    today: str,
    task_idx: int,
    expected_revision: int,
    idempotency_key: str,
) -> dict[str, Any]:
    """Acknowledge retrieval feedback and persist one independent verification task."""
    _ensure_table()
    req_hash = request_hash("advance", {"task_index": task_idx, "action": "continue_after_feedback"})
    with get_connection() as conn:
        snapshot = conn.execute(text("""SELECT id, tasks_json FROM review_sessions
            WHERE student_id=:sid AND date=:date"""), {"sid": student_id, "date": today}).mappings().first()
    if not snapshot:
        raise ValueError("review session not found")
    snapshot_tasks = json.loads(snapshot["tasks_json"])
    if not 0 <= task_idx < len(snapshot_tasks):
        raise ValueError("invalid task_index")
    retrieval = snapshot_tasks[task_idx]
    if retrieval.get("task_role") != "retrieval" or not retrieval.get("done"):
        raise ValueError("invalid_review_transition")
    tag = str(retrieval.get("tag") or "")
    excluded_ids = {str(retrieval.get("question_id") or "")}
    excluded_prints = {str(retrieval.get("assessment_fingerprint") or "")}
    verification = _generate_question(
        tag,
        target_difficulty="medium",
        selection_seed=f"{student_id}:{today}:{tag}:verification",
        task_role="verification",
        excluded_assessment_ids=excluded_ids,
        excluded_fingerprints=excluded_prints,
    )

    with get_connection() as conn:
        row = conn.execute(text("""SELECT id, tasks_json, revision, last_idempotency_key,
            last_request_hash, last_response_json FROM review_sessions WHERE id=:id"""),
            {"id": snapshot["id"]}).mappings().first()
        if not row:
            raise ValueError("review session not found")
        if row.get("last_idempotency_key") == idempotency_key:
            if row.get("last_request_hash") != req_hash:
                raise ReviewConflictError("idempotency key was used for another request", code="idempotency_payload_conflict")
            return {**json.loads(row["last_response_json"]), "replayed": True}
        revision = int(row.get("revision") or 0)
        if revision != expected_revision:
            raise ReviewConflictError("review session revision is stale", code="stale_review_revision")
        tasks = json.loads(row["tasks_json"])
        if not 0 <= task_idx < len(tasks):
            raise ValueError("invalid task_index")
        current = tasks[task_idx]
        if current.get("feedback_acknowledged"):
            raise ReviewConflictError("feedback was already acknowledged", code="stale_review_revision")
        state = get_mastery_state_with_connection(conn, student_id, tag)
        if not state or state.get("status") != "awaiting_feedback":
            raise ReviewConflictError("feedback evidence state changed", code="evidence_chain_conflict")
        next_revision = revision + 1
        current["feedback_acknowledged"] = True
        current["phase"] = "answered"
        if is_unusable_question(verification):
            set_mastery_state_with_connection(
                conn,
                student_id=student_id,
                knowledge_tag=tag,
                status="content_blocked",
                retrieval_evidence_key=state.get("retrieval_evidence_key"),
            )
            response = {
                "phase": "content_blocked",
                "content_blocked": {"message": "当前没有合适的新验证题，本次不会计入掌握结果。"},
                "session_revision": next_revision,
                "replayed": False,
            }
        else:
            _decorate_task(
                verification,
                student_id=student_id,
                session_id=str(row["id"]),
                task_role="verification",
                parent_task=current,
                retrieval_evidence_key=state.get("retrieval_evidence_key"),
            )
            tasks.append(verification)
            set_mastery_state_with_connection(
                conn,
                student_id=student_id,
                knowledge_tag=tag,
                status="verification_pending",
                retrieval_evidence_key=state.get("retrieval_evidence_key"),
            )
            response = {
                "phase": "verification_pending",
                "task_index": len(tasks) - 1,
                "task": public_review_question(verification),
                "session_revision": next_revision,
                "replayed": False,
            }
        updated = conn.execute(text("""UPDATE review_sessions SET tasks_json=:tasks,
            total=:total, revision=revision+1, last_idempotency_key=:idempotency_key,
            last_request_hash=:request_hash, last_response_json=:response
            WHERE id=:session_id AND revision=:revision"""), {
            "tasks": json.dumps(tasks, ensure_ascii=False),
            "total": len([task for task in tasks if not is_unusable_question(task)]),
            "idempotency_key": idempotency_key,
            "request_hash": req_hash,
            "response": json.dumps(response, ensure_ascii=False),
            "session_id": row["id"],
            "revision": revision,
        })
        if updated.rowcount != 1:
            raise ReviewConflictError("review session revision is stale", code="stale_review_revision")
    return response


def advance_after_feedback(
    student_id: str,
    today: str,
    task_idx: int,
    expected_revision: int,
    idempotency_key: str,
) -> dict[str, Any]:
    req_hash = request_hash("advance", {"task_index": task_idx, "action": "continue_after_feedback"})
    try:
        return _advance_after_feedback_once(
            student_id,
            today,
            task_idx,
            expected_revision,
            idempotency_key,
        )
    except ReviewConflictError as exc:
        replay = _replayed_transition_response(
            student_id,
            today,
            idempotency_key=idempotency_key,
            expected_request_hash=req_hash,
        )
        if replay is not None:
            return replay
        raise


def get_mastery_overview(student_id: str) -> dict:
    _ensure_table()
    weakpoints = get_weakpoints(student_id)
    heatmap = [
        {"tag": w["knowledge_tag"],
         # 强度 = 错误次数惩罚 + 近期连续答对加成（掌握度证据），钳制在 0.1–1.0
         "strength": round(min(1.0, max(0.1, 1.0 - min(w["wrong_count"] * 0.15, 0.9) + int(w.get("correct_streak") or 0) * 0.2)), 2),
         "wrong_count": w["wrong_count"],
         "correct_streak": int(w.get("correct_streak") or 0),
         "last_reviewed": w["last_wrong_at"]}
        for w in weakpoints
    ]
    mastered = sum(1 for h in heatmap if h["strength"] >= 0.7)
    learning = sum(1 for h in heatmap if 0.4 <= h["strength"] < 0.7)
    weak = len(heatmap) - mastered - learning

    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT date FROM review_sessions WHERE student_id=:sid AND completed >= total AND total > 0 ORDER BY date DESC LIMIT 30"),
            {"sid": student_id},
        ).mappings().fetchall()
    streak = 0
    for i, row in enumerate(rows):
        if row["date"] == (date.today() - timedelta(days=i)).isoformat():
            streak += 1
        else:
            break

    return {"total_tags": len(heatmap), "mastered": mastered, "learning": learning, "weak": weak,
            "streak_days": streak, "heatmap": heatmap}
