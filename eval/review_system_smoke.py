"""Smoke test: 自适应复习系统"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-review-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from datetime import date

from services.review_service import (
    _generate_question,
    create_today_session,
    get_mastery_overview,
    get_today_session,
    is_unusable_question,
    submit_answer,
)
from services.variant_service import generate_variant

STUDENT = "smoke-review"
TODAY = date.today().isoformat()


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def no_session_initially() -> None:
    s = get_today_session(STUDENT, TODAY)
    assert s is None, f"expected None, got {s}"


def mastery_overview_empty() -> None:
    o = get_mastery_overview(STUDENT)
    assert "total_tags" in o
    assert "streak_days" in o
    assert "heatmap" in o


def create_empty_session() -> None:
    # No weakpoints for smoke student → 0 tasks, still valid session
    s = create_today_session(STUDENT, TODAY)
    assert s["date"] == TODAY
    assert isinstance(s["tasks"], list)
    assert s["total"] == len(s["tasks"])


def session_cached() -> None:
    create_today_session(STUDENT, TODAY)  # idempotent
    s = get_today_session(STUDENT, TODAY)
    assert s is not None
    assert s["date"] == TODAY


def detects_placeholder_questions() -> None:
    """出题失败留下的占位题必须被判为不可作答，否则会被当正常题发给学生。"""
    placeholder = {
        "tag": "辛亥革命历史意义",
        "question": "关于「辛亥革命历史意义」，以下说法正确的是？",
        "options": ["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"],
        "answer": "A",
    }
    assert is_unusable_question(placeholder), "占位选项未被识别"

    generation_failed = {
        "tag": "洋务运动目的",
        "question": "关于「洋务运动目的」，以下说法正确的是？（题目生成失败，请刷新重试）",
        "options": ["A. 暂无选项", "B. 暂无选项", "C. 暂无选项", "D. 暂无选项"],
        "answer": "A",
    }
    assert is_unusable_question(generation_failed), "生成失败题未被识别"

    pending = {"tag": "戊戌变法失败原因", "question": "关于「戊戌变法失败原因」的复习题",
               "options": [], "answer": "", "pending_generate": True}
    assert is_unusable_question(pending), "待生成占位题未被识别"

    short_options = {"tag": "x", "question": "正常题面？", "options": ["A.甲", "B.乙"], "answer": "A"}
    assert is_unusable_question(short_options), "选项数量不足未被识别"


def accepts_valid_questions() -> None:
    """正常题不能被误判，否则会被反复重新生成。"""
    valid = {
        "tag": "唐朝",
        "question": "武则天是哪个朝代的皇帝？",
        "options": ["A.汉朝", "B.唐朝", "C.宋朝", "D.明朝"],
        "answer": "B",
        "difficulty": "easy",
        "cognitive_action": "recall",
        "quality_contract_version": 3,
        "quality_status": "verified",
    }
    assert not is_unusable_question(valid), "正常题被误判为占位题"


def reviewed_questions_do_not_need_model() -> None:
    """审定题选择不依赖外部模型，离线也能稳定出题。"""
    purpose = _generate_question("洋务运动目的")
    significance = _generate_question("辛亥革命历史意义")
    variant = generate_variant("洋务运动目的", purpose)

    assert not is_unusable_question(purpose), purpose
    assert "清政府的统治" in " ".join(purpose["options"]), purpose
    assert purpose["answer"] in "ABCD", purpose
    assert purpose.get("generation_source") == "curriculum_reviewed", purpose
    assert not is_unusable_question(significance), significance
    assert "君主专制制度" in " ".join(significance["options"]), significance
    assert not is_unusable_question(variant) and variant.get("is_variant") is True, variant
    assert variant.get("material"), variant
    assert "题目生成失败" not in str(purpose) + str(significance)


if __name__ == "__main__":
    cases = [
        ("no_session_initially", no_session_initially),
        ("mastery_overview_empty", mastery_overview_empty),
        ("create_empty_session", create_empty_session),
        ("session_cached", session_cached),
        ("detects_placeholder_questions", detects_placeholder_questions),
        ("accepts_valid_questions", accepts_valid_questions),
        ("reviewed_questions_do_not_need_model", reviewed_questions_do_not_need_model),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"review_system_smoke={passed}/{len(cases)}")
