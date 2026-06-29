"""Teacher feature smoke tests — class analytics, materials, and teaching suggestions."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_DB = Path(tempfile.gettempdir()) / "edu-agent-teacher-features-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

from fastapi.testclient import TestClient

from api.main import app
from security.auth import create_token
from services.weakpoint_service import get_weakpoints
from student_profile import LearningEvent, list_learning_events, record_learning_event

client = TestClient(app)
TEACHER_HEADERS = {"Authorization": f"Bearer {create_token('teacher_test', 'teacher')}"}


class _FakeResponse:
    content = '{"suggestions":["围绕洋务运动讲评典型错因。"],"activities":["同类题即时练习"],"key_topics":["洋务运动"],"homework_suggestions":["基础：整理洋务运动口号。","提高：比较洋务运动与戊戌变法。"]}'


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def seed_class_profile() -> None:
    record_learning_event(
        LearningEvent(
            student_id="teacher-smoke-a",
            feature="textbook_learning",
            event_type="quiz_submitted",
            grade="八年级上册",
            topic="洋务运动",
            score=0.4,
            success=False,
        )
    )
    record_learning_event(
        LearningEvent(
            student_id="teacher-smoke-b",
            feature="history_game",
            event_type="timeline_game_submitted",
            grade="八年级上册",
            topic="洋务运动",
            score=0.5,
            success=False,
        )
    )
    record_learning_event(
        LearningEvent(
            student_id="teacher-smoke-c",
            feature="textbook_learning",
            event_type="quiz_submitted",
            grade="八年级上册",
            topic="鸦片战争",
            score=0.9,
            success=True,
        )
    )


def class_analytics_returns_schema() -> None:
    seed_class_profile()
    response = client.get("/api/teacher/class-analytics", headers=TEACHER_HEADERS)
    assert response.status_code == 200, response.text
    data = response.json()
    for field in [
        "total_students",
        "active_students",
        "average_quiz_score",
        "average_game_score",
        "weak_topics_distribution",
        "strong_topics_distribution",
        "top_weak_topics",
        "activity_by_day",
    ]:
        assert field in data, f"missing field {field}"
    assert data["weak_topics_distribution"].get("洋务运动") == 2
    assert data["top_weak_topics"][0][0] == "洋务运动"


def teacher_materials_returns_list() -> None:
    response = client.get("/api/teacher/materials", headers=TEACHER_HEADERS)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "materials" in data
    assert isinstance(data["materials"], list)


def teaching_suggestions_returns_schema() -> None:
    with patch("api.main.llm_fast.invoke", return_value=_FakeResponse()):
        response = client.post(
            "/api/teacher/teaching-suggestions",
            headers={**TEACHER_HEADERS, "Content-Type": "application/json"},
            json={"focus": "weak_topics"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    for field in ["suggestions", "activities", "key_topics", "homework_suggestions"]:
        assert field in data, f"missing field {field}"
        assert isinstance(data[field], list)
    assert "洋务运动" in data["key_topics"]


def _save_review(student_id: str, *, weak_tag: str, item_tag: str) -> str:
    response = client.post(
        "/api/homework/reviews",
        headers={**TEACHER_HEADERS, "Content-Type": "application/json"},
        json={
            "grade_request": {
                "student_id": student_id,
                "grade": "八年级上册",
                "task_type": "history_homework",
            },
            "grade_result": {
                "normalized_score": 0.42,
                "needs_human_review": True,
                "weak_points": [weak_tag],
                "items": [
                    {
                        "question": "简述洋务运动的局限。",
                        "answer": "只学习技术。",
                        "score": 1,
                        "max_score": 5,
                        "is_correct": False,
                        "knowledge_tags": [item_tag],
                    }
                ],
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["review_id"]


def teacher_review_accept_syncs_learning_signals() -> None:
    student_id = "teacher-review-accepted"
    review_id = _save_review(student_id, weak_tag="洋务运动局限", item_tag="洋务运动")

    response = client.post(
        f"/api/teacher/homework-reviews/{review_id}/decision",
        headers={**TEACHER_HEADERS, "Content-Type": "application/json"},
        json={"decision": "accepted", "teacher_note": "确认该错因", "teacher_score": 55},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["event_id"], "missing learning event id"

    events = list_learning_events(student_id=student_id, event_type="teacher_review_accepted", limit=5)
    assert events, "teacher review event not recorded"
    assert events[0]["metadata"]["review_id"] == review_id
    assert events[0]["metadata"]["teacher_note_present"] is True
    assert events[0]["score"] == 0.55
    assert events[0]["success"] is False

    weakpoints = get_weakpoints(student_id)
    by_tag = {item["knowledge_tag"]: item for item in weakpoints}
    assert by_tag["洋务运动局限"]["source"] == "homework_teacher_review"
    assert by_tag["洋务运动"]["source"] == "homework_teacher_review"


def teacher_review_edit_syncs_learning_signals() -> None:
    student_id = "teacher-review-edited"
    review_id = _save_review(student_id, weak_tag="辛亥革命影响", item_tag="辛亥革命")

    response = client.post(
        f"/api/teacher/homework-reviews/{review_id}/decision",
        headers={**TEACHER_HEADERS, "Content-Type": "application/json"},
        json={"decision": "edited", "teacher_note": "教师修正后确认", "teacher_score": 65},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["event_id"], "missing learning event id"

    events = list_learning_events(student_id=student_id, event_type="teacher_review_edited", limit=5)
    assert events, "teacher edited event not recorded"
    assert events[0]["success"] is True

    weakpoints = get_weakpoints(student_id)
    assert {item["knowledge_tag"] for item in weakpoints} == {"辛亥革命影响", "辛亥革命"}
    assert all(item["source"] == "homework_teacher_review" for item in weakpoints)


def teacher_review_reject_skips_weakpoints() -> None:
    student_id = "teacher-review-rejected"
    review_id = _save_review(student_id, weak_tag="戊戌变法误区", item_tag="戊戌变法")

    response = client.post(
        f"/api/teacher/homework-reviews/{review_id}/decision",
        headers={**TEACHER_HEADERS, "Content-Type": "application/json"},
        json={"decision": "rejected", "teacher_note": "AI 误判", "teacher_score": 80},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["event_id"], "missing learning event id"

    events = list_learning_events(student_id=student_id, event_type="teacher_review_rejected", limit=5)
    assert events, "teacher rejection event not recorded"
    assert events[0]["success"] is True
    assert get_weakpoints(student_id) == []


def main() -> None:
    cases = [
        ("class_analytics_returns_schema", class_analytics_returns_schema),
        ("teacher_materials_returns_list", teacher_materials_returns_list),
        ("teaching_suggestions_returns_schema", teaching_suggestions_returns_schema),
        ("teacher_review_accept_syncs_learning_signals", teacher_review_accept_syncs_learning_signals),
        ("teacher_review_edit_syncs_learning_signals", teacher_review_edit_syncs_learning_signals),
        ("teacher_review_reject_skips_weakpoints", teacher_review_reject_skips_weakpoints),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"teacher_features_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
