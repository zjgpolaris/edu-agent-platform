"""Smoke test: 错题变式生成

覆盖场景：
1. generate_variant 离线降级（无 LLM）返回合法结构
2. get_or_create_variant 首次生成并落库
3. get_or_create_variant 当天再次调用命中缓存（不二次生成）
4. should_use_variant 阈值判断
5. review_service create_today_session 在 wrong_count>=2 时走变式路径
6. 变式题与"普通题"结构兼容（含 is_variant 字段）
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-variant-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from datetime import date

STUDENT = "smoke-variant"
TODAY = date.today().isoformat()
TAG = "鸦片战争"


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


# ── Case 1: 降级生成结构合法 ────────────────────────────────────────────────────
def c1_fallback_structure() -> None:
    """mock llm_fast.invoke 抛异常，验证降级题目结构完整。"""
    import unittest.mock as mock
    from services import variant_service

    with mock.patch("services.variant_service.generate_variant", wraps=variant_service.generate_variant):
        # 直接用内部降级逻辑：patch llm_fast.invoke 抛异常
        pass

    # 直接测试降级路径：llm_fast 不可用时 generate_variant 应返回合法 dict
    import importlib
    import types
    fake_llm = types.SimpleNamespace(invoke=lambda msgs: (_ for _ in ()).throw(RuntimeError("no llm")))
    with mock.patch.dict(sys.modules, {"llm_config": types.SimpleNamespace(llm_fast=fake_llm)}):
        # 由于 llm_config 已被真实导入，直接 patch generate_variant 内部 llm_fast
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        pass

    # 退而求其次：直接构造异常场景，验证返回结构
    from services.variant_service import generate_variant
    import unittest.mock as mock

    with mock.patch("llm_config.llm_fast") as mock_llm:
        mock_llm.invoke.side_effect = RuntimeError("mock lm failure")
        result = generate_variant(TAG, seed_question=None)

    _check_question_structure(result, expect_variant=True)


def _check_question_structure(q: dict, *, expect_variant: bool = False) -> None:
    assert isinstance(q.get("question"), str) and q["question"], "question 字段缺失或为空"
    assert isinstance(q.get("options"), list) and len(q["options"]) >= 2, "options 字段异常"
    assert isinstance(q.get("answer"), str) and q["answer"], "answer 字段缺失"
    assert isinstance(q.get("explanation"), str), "explanation 字段缺失"
    assert q.get("tag") == TAG, f"tag 字段不符，期望 {TAG!r}，实际 {q.get('tag')!r}"
    if expect_variant:
        assert q.get("is_variant") is True, "缺少 is_variant=True 标记"


# ── Case 2: get_or_create_variant 首次落库 ──────────────────────────────────────
def c2_create_and_persist() -> None:
    from services.variant_service import get_or_create_variant, get_cached_variant
    import unittest.mock as mock

    fake_q = {
        "question": "【变式】关于鸦片战争的叙述，下列正确的是？",
        "options": ["A. 1840年英国发动", "B. 1850年法国发动", "C. 1860年俄国发动", "D. 以上都不对"],
        "answer": "A",
        "explanation": "鸦片战争始于1840年，由英国发动。",
        "is_variant": True,
        "tag": TAG,
        "done": False,
        "correct": None,
    }
    with mock.patch("services.variant_service.generate_variant", return_value=fake_q):
        result = get_or_create_variant(STUDENT, TAG, today=TODAY)

    _check_question_structure(result, expect_variant=True)

    # 验证已落库
    cached = get_cached_variant(STUDENT, TAG, TODAY)
    assert cached is not None, "落库后 get_cached_variant 应返回非 None"
    assert cached["question"] == fake_q["question"], "缓存内容与生成内容不一致"


# ── Case 3: 当天缓存命中，不再调用 generate_variant ────────────────────────────
def c3_cache_hit() -> None:
    from services.variant_service import get_or_create_variant
    import unittest.mock as mock

    call_count = {"n": 0}
    def counting_generate(tag, seed_question=None):
        call_count["n"] += 1
        return {"question": "SHOULD NOT BE CALLED", "options": [], "answer": "", "explanation": "", "is_variant": True, "tag": tag, "done": False, "correct": None}

    with mock.patch("services.variant_service.generate_variant", side_effect=counting_generate):
        result = get_or_create_variant(STUDENT, TAG, today=TODAY)

    assert call_count["n"] == 0, f"缓存命中时不应调用 generate_variant，但实际调用了 {call_count['n']} 次"
    assert result is not None, "缓存命中应返回非 None"


# ── Case 4: should_use_variant 阈值 ─────────────────────────────────────────────
def c4_threshold() -> None:
    from services.variant_service import should_use_variant, VARIANT_THRESHOLD
    assert not should_use_variant(0), "wrong_count=0 不应触发变式"
    assert not should_use_variant(VARIANT_THRESHOLD - 1), f"wrong_count={VARIANT_THRESHOLD-1} 不应触发变式"
    assert should_use_variant(VARIANT_THRESHOLD), f"wrong_count={VARIANT_THRESHOLD} 应触发变式"
    assert should_use_variant(VARIANT_THRESHOLD + 5), "wrong_count 超过阈值应触发变式"


# ── Case 5: review_service 高 wrong_count 触发变式路径 ───────────────────────────
def c5_review_uses_variant() -> None:
    from services.weakpoint_service import _ensure_table as wp_ensure, record_weakpoint
    from services.review_service import create_today_session
    import unittest.mock as mock

    STUDENT2 = "smoke-variant-review"
    wp_ensure()
    # 模拟该学生在 TAG 上答错 3 次（超过阈值）
    for _ in range(3):
        record_weakpoint(STUDENT2, TAG, source="assignment")

    variant_calls = {"n": 0}
    original_calls = {"n": 0}

    def fake_variant(sid, tag, seed_question=None, *, today=None):
        variant_calls["n"] += 1
        return {"question": f"变式题-{tag}", "options": ["A", "B", "C", "D"], "answer": "A",
                "explanation": "解析", "is_variant": True, "tag": tag, "done": False, "correct": None}

    def fake_generate(tag):
        original_calls["n"] += 1
        return {"question": f"普通题-{tag}", "options": ["A", "B", "C", "D"], "answer": "A",
                "explanation": "解析", "is_variant": False, "tag": tag, "done": False, "correct": None}

    with mock.patch("services.review_service.get_or_create_variant", fake_variant), \
         mock.patch("services.review_service._generate_question", fake_generate):
        session = create_today_session(STUDENT2, TODAY)

    assert session["total"] >= 1, "应有至少一道复习题"
    assert variant_calls["n"] >= 1, f"wrong_count>={3} 应调用变式生成，实际 variant_calls={variant_calls['n']}"
    # 任务列表中应包含变式题
    variant_tasks = [t for t in session["tasks"] if t.get("is_variant")]
    assert len(variant_tasks) >= 1, "session tasks 中应有 is_variant=True 的任务"


# ── Case 6: 变式题结构与复习 session 兼容 ──────────────────────────────────────
def c6_variant_compatible_with_session() -> None:
    """变式题应包含 done/correct 字段，与 review submit_answer 兼容。"""
    from services.variant_service import generate_variant
    import unittest.mock as mock

    fake_content = '{"question":"测试变式题","options":["A.一","B.二","C.三","D.四"],"answer":"B","explanation":"解析","is_variant":true}'
    mock_resp = type("R", (), {"content": fake_content})()

    with mock.patch("llm_config.llm_fast") as mock_llm:
        mock_llm.invoke.return_value = mock_resp
        result = generate_variant(TAG)

    assert "done" in result, "变式题应含 done 字段（供 review session 用）"
    assert "correct" in result, "变式题应含 correct 字段"
    assert result["tag"] == TAG


if __name__ == "__main__":
    cases = [
        ("C1 降级生成结构合法", c1_fallback_structure),
        ("C2 首次生成并落库", c2_create_and_persist),
        ("C3 当天缓存命中", c3_cache_hit),
        ("C4 should_use_variant 阈值", c4_threshold),
        ("C5 review_service 触发变式路径", c5_review_uses_variant),
        ("C6 变式题结构与 session 兼容", c6_variant_compatible_with_session),
    ]
    passed = sum(run_case(name, fn) for name, fn in cases)
    total = len(cases)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)
