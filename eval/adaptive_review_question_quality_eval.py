"""Deterministic regression gate for student-facing adaptive history practice."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-adaptive-review-quality.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
sys.path.insert(0, str(ROOT / "backend"))

from db.engine import get_connection
from services.history_review_question import (
    build_curated_review_question,
    build_grounded_review_question,
    public_review_question,
    review_question_quality_reasons,
)
from services.review_service import (
    ReviewConflictError,
    _ensure_table,
    create_today_session,
    get_today_session,
    public_review_session,
    submit_answer,
)
from services.weakpoint_service import get_weakpoints, record_weakpoint
from student_profile import now_iso


TODAY = date.today().isoformat()
REVIEWED_TAGS = (
    "戊戌变法失败原因",
    "洋务运动目的",
    "赤壁之战的影响",
    "辛亥革命历史意义",
    "鸦片战争的影响",
)
LEGACY_BAD_TASK = {
    "tag": "戊戌变法失败原因",
    "question": "换一个角度思考：下列哪一项符合教材对戊戌变法失败原因的说明？",
    "options": [
        "A. 完全由单一人物的个人意愿决定",
        "B. 戊戌变法虽然失败了，但在思想文化方面产生了广泛而持久的影响，起到了思想启蒙的作用，为资产阶级民主思想的传播奠定了基础",
        "C. 与当时的社会矛盾和时代背景无关",
        "D. 教材没有提供任何可以判断的历史条件",
    ],
    "answer": "B",
    "explanation": "错误地把历史影响当成失败原因。",
    "done": False,
    "correct": None,
    "is_variant": True,
}


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def c1_legacy_screenshot_is_rejected() -> None:
    reasons = review_question_quality_reasons(LEGACY_BAD_TASK, require_variant=True)
    assert "implausible_distractor" in reasons, reasons
    assert "answer_length_giveaway" in reasons, reasons
    assert "variant_material_missing" in reasons, reasons


def c2_reviewed_catalog_meets_contract() -> None:
    for tag in REVIEWED_TAGS:
        normal = build_curated_review_question(tag, target_difficulty="easy", selection_seed="catalog")
        variant = build_curated_review_question(
            tag,
            is_variant=True,
            target_difficulty="medium",
            selection_seed="catalog",
        )
        assert normal is not None and not review_question_quality_reasons(normal), (tag, normal)
        assert variant is not None and not review_question_quality_reasons(variant, require_variant=True), (tag, variant)
        assert variant.get("material"), (tag, variant)
        assert variant.get("material_timing") == "after_answer", (tag, variant)
        assert variant.get("cognitive_action") in {"explain", "compare", "apply"}, (tag, variant)


def c3_wuxu_tests_causes_not_impact() -> None:
    normal = build_curated_review_question("戊戌变法失败原因", target_difficulty="easy", selection_seed="wuxu")
    variant = build_curated_review_question(
        "戊戌变法失败原因",
        is_variant=True,
        target_difficulty="medium",
        selection_seed="wuxu",
    )
    assert normal and variant
    answer_text = normal["options"]["ABCD".index(normal["answer"])]
    assert any(term in answer_text for term in ("顽固派", "力量弱小", "支持")), answer_text
    assert "思想启蒙" not in answer_text, answer_text
    variant_answer = variant["options"]["ABCD".index(variant["answer"])]
    assert "改革力量薄弱" in variant_answer, variant_answer


def c4_public_payload_hides_answer() -> None:
    question = build_curated_review_question("戊戌变法失败原因", target_difficulty="easy")
    assert question
    public = public_review_question(question)
    assert "answer" not in public and "explanation" not in public and "option_feedback" not in public, public
    revealed = public_review_question(question, reveal_answer=True)
    assert revealed["answer"] in "ABCD" and revealed.get("explanation"), revealed

    variant = build_curated_review_question("戊戌变法失败原因", is_variant=True, target_difficulty="medium")
    assert variant
    hidden = public_review_question(variant)
    assert "material" not in hidden and "answer" not in hidden, hidden
    variant_revealed = public_review_question(variant, reveal_answer=True)
    assert variant_revealed.get("material") and variant_revealed.get("answer"), variant_revealed


def c5_legacy_and_stale_sessions_are_rehydrated() -> None:
    student = "quality-hydrate"
    _ensure_table()
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions
                (id, student_id, date, tasks_json, completed, total, created_at)
                VALUES (:id, :student_id, :date, :tasks, 0, 1, :created_at)"""),
            {
                "id": "quality-hydrate-session",
                "student_id": student,
                "date": TODAY,
                "tasks": json.dumps([LEGACY_BAD_TASK], ensure_ascii=False),
                "created_at": now_iso(),
            },
        )
    hydrated = get_today_session(student, TODAY)
    assert hydrated
    task = hydrated["tasks"][0]
    assert task.get("quality_status") == "verified", task
    assert task.get("question_id") == "wuxu-cause-exit-1", task
    assert task.get("material") and not review_question_quality_reasons(task, require_variant=True), task

    stale_student = "quality-stale-adaptation"
    record_weakpoint(stale_student, "戊戌变法失败原因", source="assignment")
    record_weakpoint(stale_student, "戊戌变法失败原因", source="assignment")
    easy = build_curated_review_question("戊戌变法失败原因", target_difficulty="easy")
    assert easy
    with get_connection() as conn:
        conn.execute(
            text("""INSERT INTO review_sessions
                (id, student_id, date, tasks_json, completed, total, created_at)
                VALUES (:id, :student_id, :date, :tasks, 0, 1, :created_at)"""),
            {
                "id": "quality-stale-adaptation-session",
                "student_id": stale_student,
                "date": TODAY,
                "tasks": json.dumps([easy], ensure_ascii=False),
                "created_at": now_iso(),
            },
        )
    refreshed = get_today_session(stale_student, TODAY)
    assert refreshed
    refreshed_task = refreshed["tasks"][0]
    assert refreshed_task.get("is_variant") is True, refreshed_task
    assert refreshed_task.get("difficulty") == "medium", refreshed_task
    assert refreshed_task.get("material_timing") == "after_answer", refreshed_task


def c6_adaptation_uses_material_transfer() -> None:
    student = "quality-adaptation"
    record_weakpoint(student, "戊戌变法失败原因", source="assignment")
    record_weakpoint(student, "戊戌变法失败原因", source="assignment")
    session = create_today_session(student, TODAY)
    assert session["total"] == 1, session
    task = session["tasks"][0]
    assert task.get("is_variant") is True and task.get("difficulty") == "medium", task
    assert task.get("material") and task.get("material_timing") == "after_answer", task
    assert "先独立作答" in task.get("adaptive_message", ""), task


def c7_server_judges_and_submission_is_idempotent() -> None:
    student = "quality-submit"
    record_weakpoint(student, "洋务运动目的", source="assignment")
    session = create_today_session(student, TODAY)
    internal = session["tasks"][0]
    safe = public_review_session(session)
    assert "answer" not in safe["tasks"][0], safe

    first = submit_answer(student, TODAY, 0, internal["answer"])
    assert first["is_correct"] is True and first["task"]["answer"] == internal["answer"], first
    replay = submit_answer(student, TODAY, 0, internal["answer"])
    assert replay.get("replayed") is True, replay
    with get_connection() as conn:
        evidence_count = conn.execute(
            text("SELECT COUNT(*) FROM weakpoint_evidence WHERE student_id=:sid"), {"sid": student}
        ).scalar_one()
        event_count = conn.execute(
            text("SELECT COUNT(*) FROM learning_events WHERE student_id=:sid AND event_type='review_answered'"),
            {"sid": student},
        ).scalar_one()
    assert evidence_count == 1 and event_count == 1, (evidence_count, event_count)
    try:
        submit_answer(student, TODAY, 0, "D" if internal["answer"] != "D" else "C")
    except ReviewConflictError:
        pass
    else:
        raise AssertionError("changing an answered task must return a conflict")


def c8_unreviewed_content_fails_closed() -> None:
    blocked = build_grounded_review_question("不存在的历史知识点")
    assert blocked.get("quality_status") == "blocked", blocked
    assert blocked.get("pending_generate") is True and not blocked.get("options"), blocked
    assert "answer" not in public_review_question(blocked), blocked
    safe = public_review_session({"date": TODAY, "completed": 0, "total": 1, "tasks": [blocked]})
    assert safe["total"] == 0 and safe["blocked_count"] == 1 and not safe["tasks"], safe


if __name__ == "__main__":
    cases = [
        ("legacy_screenshot_is_rejected", c1_legacy_screenshot_is_rejected),
        ("reviewed_catalog_meets_contract", c2_reviewed_catalog_meets_contract),
        ("wuxu_tests_causes_not_impact", c3_wuxu_tests_causes_not_impact),
        ("public_payload_hides_answer", c4_public_payload_hides_answer),
        ("legacy_and_stale_sessions_are_rehydrated", c5_legacy_and_stale_sessions_are_rehydrated),
        ("adaptation_uses_material_transfer", c6_adaptation_uses_material_transfer),
        ("server_judges_and_submission_is_idempotent", c7_server_judges_and_submission_is_idempotent),
        ("unreviewed_content_fails_closed", c8_unreviewed_content_fails_closed),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    print(f"adaptive_review_question_quality_eval={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
