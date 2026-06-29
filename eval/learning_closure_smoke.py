from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_DB = Path(tempfile.gettempdir()) / "edu-agent-learning-closure-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

from fastapi.testclient import TestClient

from api.main import app
from services.weakpoint_service import record_weakpoint
from student_profile import LearningEvent, get_student_profile, record_learning_event

client = TestClient(app)
STUDENT_ID = "closure-smoke-student"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def homework_like_event_updates_profile() -> None:
    record_learning_event(
        LearningEvent(
            student_id=STUDENT_ID,
            feature="homework_grading",
            event_type="submission_graded",
            grade="八年级上册",
            topic="洋务运动",
            score=0.4,
            success=False,
            metadata={"source": "learning_closure_smoke"},
        )
    )
    profile = get_student_profile(STUDENT_ID)
    assert "洋务运动" in profile.weak_topics
    assert profile.grade == "八年级上册"


def weakpoints_prioritize_review_plan() -> None:
    record_weakpoint(STUDENT_ID, "洋务运动", "homework_grading")
    record_weakpoint(STUDENT_ID, "洋务运动", "homework_grading")
    record_weakpoint(STUDENT_ID, "鸦片战争", "quiz")

    response = client.get(f"/api/students/{STUDENT_ID}/review-plan")
    assert response.status_code == 200, response.text
    plan = response.json()["review_plan"]
    assert plan["weakpoints"][0]["knowledge_tag"] == "洋务运动"
    assert plan["priority_topics"][0] == "洋务运动"
    assert plan["recommended_actions"]


def learning_path_contains_weakpoints() -> None:
    response = client.get(f"/api/students/{STUDENT_ID}/learning-path")
    assert response.status_code == 200, response.text
    path = response.json()
    assert path["weakpoints"][0]["knowledge_tag"] == "洋务运动"
    assert path["priority_topics"][0] == "洋务运动"
    assert path["milestones"]
    assert path["progress"]["洋务运动"] <= 0.5


def teacher_analytics_reads_json_schema() -> None:
    record_learning_event(
        LearningEvent(
            student_id="closure-analytics-student",
            feature="textbook_learning",
            event_type="quiz_submitted",
            grade="八年级上册",
            topic="鸦片战争",
            score=0.9,
            success=True,
        )
    )
    record_learning_event(
        LearningEvent(
            student_id="closure-analytics-student",
            feature="history_game",
            event_type="timeline_game_submitted",
            grade="八年级上册",
            topic="辛亥革命",
            score=0.5,
            success=False,
        )
    )

    response = client.get("/api/teacher/class-analytics")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["average_quiz_score"] is not None
    assert data["average_game_score"] is not None
    assert "辛亥革命" in data["weak_topics_distribution"]


def main() -> None:
    cases = [
        ("homework_like_event_updates_profile", homework_like_event_updates_profile),
        ("weakpoints_prioritize_review_plan", weakpoints_prioritize_review_plan),
        ("learning_path_contains_weakpoints", learning_path_contains_weakpoints),
        ("teacher_analytics_reads_json_schema", teacher_analytics_reads_json_schema),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"learning_closure_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
