from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-homework-grading-smoke.sqlite3")
try:
    Path(os.environ["EDU_AGENT_DB_PATH"]).unlink()
except FileNotFoundError:
    pass

class _SmokeSplitter:
    def split_documents(self, docs):
        return docs

fake_rag = types.ModuleType("rag.knowledge_base")
fake_rag.BGE_QUERY_PREFIX = ""
fake_rag.add_documents_to_collection = lambda *args, **kwargs: 0
fake_rag.build_chroma_where = lambda metadata_filter: metadata_filter
fake_rag.delete_documents_by_filter = lambda *args, **kwargs: 0
fake_rag.keyword_score = lambda *args, **kwargs: 0
fake_rag.load_vectorstore = lambda *args, **kwargs: None
fake_rag.splitter = _SmokeSplitter()
sys.modules["rag.knowledge_base"] = fake_rag

from homework_grading.schema import ExtractedHomeworkItem, HomeworkGradeRequest, HomeworkGradedItem, HomeworkGradeResponse
from homework_grading.service import _fallback_grade, _normalize_grade_response, _record_learning_signals
from services.weakpoint_service import clear_weakpoints, get_weakpoints


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def choice_schema_accepts_options() -> None:
    item = ExtractedHomeworkItem(
        item_id="q1",
        question="洋务运动的主要主张是？",
        student_answer="B",
        reference_context="",
        question_type="history_single_choice",
        options=["A. 变法维新", "B. 学习西方技术", "C. 推翻清朝", "D. 平均地权"],
        correct_answer="B",
        knowledge_tags=["洋务运动"],
        confidence="high",
    )
    req = HomeworkGradeRequest(task_type="history_single_choice", items=[item])
    assert req.items[0].options[1].startswith("B")
    assert req.items[0].correct_answer == "B"


def fallback_marks_review_for_choice() -> None:
    item = ExtractedHomeworkItem(
        item_id="q1",
        question="洋务运动的主要主张是？",
        student_answer="",
        question_type="history_single_choice",
        options=[],
        knowledge_tags=["洋务运动"],
        confidence="low",
    )
    req = HomeworkGradeRequest(task_type="history_single_choice", items=[item])
    response = _normalize_grade_response(req, _fallback_grade(req, "需要教师复核。"))
    assert response.needs_human_review is True
    assert response.review_reason
    assert response.items[0].correct_answer is None


def learning_signals_record_weakpoints() -> None:
    student_id = "homework-smoke-student"
    clear_weakpoints(student_id)
    item = HomeworkGradedItem(
        item_id="q1",
        question="洋务运动的主要主张是？",
        student_answer="A",
        score=0,
        max_score=10,
        grade_level="待改进",
        is_correct=False,
        strengths=[],
        issues=["没有识别洋务运动学习西方技术的特点"],
        missing_points=["自强、求富"],
        knowledge_tags=["洋务运动"],
        correct_answer="B",
        explanation="洋务运动主张学习西方先进技术。",
        revision_suggestion="复习洋务派的主要口号和代表企业。",
    )
    req = HomeworkGradeRequest(
        task_type="history_single_choice",
        student_id=student_id,
        grade="八年级上册",
        items=[ExtractedHomeworkItem(item_id="q1", question=item.question, student_answer="A", question_type="history_single_choice", options=["A. 变法", "B. 学技术"], knowledge_tags=["洋务运动"], confidence="high")],
    )
    response = HomeworkGradeResponse(
        total_score=0,
        max_score=10,
        normalized_score=0,
        grade_level="待改进",
        items=[item],
        overall_feedback="需要复习洋务运动。",
        weak_points=["洋务运动"],
        follow_up_quiz=[],
        needs_human_review=False,
        warnings=[],
    )
    event_id = _record_learning_signals(req, response)
    assert event_id
    points = get_weakpoints(student_id)
    assert any(point.get("knowledge_tag") == "洋务运动" for point in points)


def main() -> None:
    cases = [
        ("choice_schema_accepts_options", choice_schema_accepts_options),
        ("fallback_marks_review_for_choice", fallback_marks_review_for_choice),
        ("learning_signals_record_weakpoints", learning_signals_record_weakpoints),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"homework_grading_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
