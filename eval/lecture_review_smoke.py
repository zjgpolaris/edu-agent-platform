"""Smoke test: 讲评课 AI 辅助

覆盖场景：
1. aggregate_teacher_errors 无作业时返回空列表
2. aggregate_teacher_errors 有作业答题数据时正确聚合
3. _build_topic_prompt 包含知识点信息
4. _parse_topic_llm JSON 解析正常路径
5. _parse_topic_llm 降级路径（解析失败）
6. generate_lecture_review LLM mock 路径，结构完整
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-lecture-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

TEACHER = "smoke-lecture-teacher"
STUDENT_A = "smoke-lecture-sa"
STUDENT_B = "smoke-lecture-sb"


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK  {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        import traceback
        traceback.print_exc()
        return False


# ── helpers ─────────────────────────────────────────────────────────────────
def _create_assignment_with_submissions() -> str:
    """创建一份作业并写入两份提交（一对一错），返回 assignment_id。"""
    from services.assignment_service import create_assignment, submit_assignment, _ensure_tables
    _ensure_tables()

    questions = [
        {"type": "single_choice", "prompt": "鸦片战争起于哪年？",
         "options": ["A.1840", "B.1850", "C.1860", "D.1870"], "answer": "A",
         "knowledge_tag": "鸦片战争"},
        {"type": "single_choice", "prompt": "洋务运动的核心主张是？",
         "options": ["A.科技救国", "B.变法图强", "C.中体西用", "D.民主共和"], "answer": "C",
         "knowledge_tag": "洋务运动"},
    ]
    aid = create_assignment(TEACHER, "讲评测试作业", questions, [STUDENT_A, STUDENT_B])
    aid = aid["id"]  # create_assignment 返回 dict，取 id 字段
    # STUDENT_A 全对
    submit_assignment(STUDENT_A, aid, ["A", "C"])
    # STUDENT_B 两题都错
    submit_assignment(STUDENT_B, aid, ["B", "A"])
    return aid


# ── Case 1: 无作业时返回空列表 ────────────────────────────────────────────────
def c1_no_assignments() -> None:
    from services.lecture_review_service import aggregate_teacher_errors
    result = aggregate_teacher_errors("unknown-teacher-xyz")
    assert result == [], f"期望空列表，得到 {result}"


# ── Case 2: 有数据时聚合正确 ──────────────────────────────────────────────────
def c2_aggregate_with_data() -> None:
    from services.lecture_review_service import aggregate_teacher_errors
    _create_assignment_with_submissions()
    result = aggregate_teacher_errors(TEACHER)
    assert len(result) >= 1, "应有至少一个知识点"
    tags = [r["tag"] for r in result]
    assert "鸦片战争" in tags or "洋务运动" in tags, f"高频错误知识点未出现在结果中：{tags}"
    for r in result:
        assert "error_count" in r and "student_count" in r and "accuracy" in r
        assert isinstance(r["wrong_options"], list)
        assert isinstance(r["question_prompts"], list)
    # student_count 降序
    counts = [r["student_count"] for r in result]
    assert counts == sorted(counts, reverse=True), "结果应按 student_count 降序"


# ── Case 3: prompt 包含知识点名 ───────────────────────────────────────────────
def c3_prompt_contains_tag() -> None:
    from services.lecture_review_service import _build_topic_prompt
    topic = {
        "tag": "甲午战争", "student_count": 5, "accuracy": 30.0,
        "wrong_options": [{"option": "B", "count": 4}],
        "question_prompts": ["甲午战争爆发于哪年？"],
    }
    prompt = _build_topic_prompt(topic)
    assert "甲午战争" in prompt
    assert "lecture_tip" in prompt
    assert "board_keywords" in prompt


# ── Case 4: _parse_topic_llm 正常解析 ─────────────────────────────────────────
def c4_parse_llm_ok() -> None:
    from services.lecture_review_service import _parse_topic_llm
    raw = '{"lecture_tip":"这是讲解提示","board_keywords":"关键词1,关键词2","sample_exercise":"即时选择题练习"}'
    result = _parse_topic_llm(raw, "测试知识点")
    assert result["lecture_tip"] == "这是讲解提示"
    assert "关键词" in result["board_keywords"]
    assert result["sample_exercise"] == "即时选择题练习"


# ── Case 5: _parse_topic_llm 降级路径 ─────────────────────────────────────────
def c5_parse_llm_fallback() -> None:
    from services.lecture_review_service import _parse_topic_llm
    result = _parse_topic_llm("INVALID JSON %%##", "鸦片战争")
    # 降级仍返回完整结构
    assert isinstance(result["lecture_tip"], str) and result["lecture_tip"]
    assert isinstance(result["board_keywords"], str) and result["board_keywords"]
    assert isinstance(result["sample_exercise"], str) and result["sample_exercise"]


# ── Case 6: generate_lecture_review mock LLM，结构完整 ───────────────────────
def c6_generate_structure() -> None:
    import unittest.mock as mock
    from services.lecture_review_service import generate_lecture_review

    fake_content = json.dumps({
        "lecture_tip": "注意时间线，1840年是关键节点。学生容易混淆1840/1860。",
        "board_keywords": "1840年,英国,虎门销烟,南京条约",
        "sample_exercise": "补充填空：鸦片战争签署了《___》",
    })
    mock_resp = type("R", (), {"content": fake_content})()

    with mock.patch("llm_config.llm_fast") as mock_llm:
        mock_llm.invoke.return_value = mock_resp
        result = generate_lecture_review(TEACHER)

    assert "topics" in result, "缺少 topics 字段"
    assert "generated_at" in result
    assert isinstance(result["topics"], list)
    for t in result["topics"]:
        assert "tag" in t
        assert "lecture_tip" in t and t["lecture_tip"]
        assert "board_keywords" in t and t["board_keywords"]
        assert "sample_exercise" in t and t["sample_exercise"]
        assert "student_count" in t and "accuracy" in t


if __name__ == "__main__":
    cases = [
        ("C1 无作业返回空列表", c1_no_assignments),
        ("C2 有数据时聚合正确", c2_aggregate_with_data),
        ("C3 prompt 包含知识点名", c3_prompt_contains_tag),
        ("C4 _parse_topic_llm 正常解析", c4_parse_llm_ok),
        ("C5 _parse_topic_llm 降级路径", c5_parse_llm_fallback),
        ("C6 generate_lecture_review 结构完整", c6_generate_structure),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
