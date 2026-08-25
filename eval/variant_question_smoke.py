"""Smoke test: 错题变式生成

覆盖场景：
1. generate_variant 从审定题包返回合法材料变式
2. get_or_create_variant 首次生成并落库
3. get_or_create_variant 当天再次调用命中缓存（不二次生成）
4. should_use_variant 阈值判断
5. review_service create_today_session 在 wrong_count>=2 时走审定 retrieval 变式路径
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


# ── Case 1: 审定材料变式结构合法 ────────────────────────────────────────────────
def c1_reviewed_structure() -> None:
    from services.variant_service import generate_variant
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
        "question_id": "smoke-opium-variant-1",
        "material": "1840年，英国军舰驶入中国海面，战争由此爆发。",
        "question": "鸦片战争的发动者和开始时间分别是什么？",
        "options": ["A. 1840年英国发动", "B. 1850年法国发动", "C. 1860年俄国发动", "D. 1894年日本发动"],
        "answer": "A",
        "explanation": "鸦片战争始于1840年，由英国发动。",
        "difficulty": "medium",
        "cognitive_action": "apply",
        "quality_contract_version": 3,
        "quality_status": "verified",
        "material_timing": "after_answer",
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
    def counting_generate(tag, seed_question=None, **_kwargs):
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


# ── Case 5: review_service 高 wrong_count 触发审定 retrieval 变式路径 ───────────
def c5_review_uses_variant() -> None:
    from services.weakpoint_service import _ensure_table as wp_ensure, record_weakpoint
    from services.review_service import create_today_session
    import unittest.mock as mock

    STUDENT2 = "smoke-variant-review"
    wp_ensure()
    # 模拟该学生在 TAG 上答错 3 次（超过阈值）
    for _ in range(3):
        record_weakpoint(STUDENT2, TAG, source="assignment")

    generate_calls: list[dict] = []

    def fake_generate(tag, **kwargs):
        generate_calls.append({"tag": tag, **kwargs})
        is_variant = bool(kwargs.get("is_variant"))
        target_difficulty = str(kwargs.get("target_difficulty") or "easy")
        return {
            "question_id": "fake-reviewed-retrieval",
            "assessment_fingerprint": "sha256:fake-reviewed-retrieval",
            "material": "这是一段用于验证审定 retrieval 变式路径的历史对照材料。" if is_variant else None,
            "material_timing": "after_answer" if is_variant else None,
            "question": f"关于{tag}的独立判断题",
            "options": ["A. 甲项", "B. 乙项", "C. 丙项", "D. 丁项"],
            "answer": "A",
            "explanation": "解析",
            "difficulty": target_difficulty,
            "cognitive_action": "apply" if is_variant else "recall",
            "quality_contract_version": 3,
            "quality_status": "verified",
            "is_variant": is_variant,
            "tag": tag,
            "done": False,
            "correct": None,
        }

    with mock.patch("services.review_service._generate_question", fake_generate):
        session = create_today_session(STUDENT2, TODAY)

    assert session["total"] >= 1, "应有至少一道复习题"
    assert len(generate_calls) == 1, f"应只选择一次审定题，实际调用={generate_calls}"
    assert generate_calls[0]["is_variant"] is True, generate_calls[0]
    assert generate_calls[0]["target_difficulty"] == "medium", generate_calls[0]
    assert generate_calls[0]["task_role"] == "retrieval", generate_calls[0]
    # 任务列表中应包含变式题
    variant_tasks = [t for t in session["tasks"] if t.get("is_variant")]
    assert len(variant_tasks) >= 1, "session tasks 中应有 is_variant=True 的任务"
    assert variant_tasks[0].get("task_role") == "retrieval", variant_tasks[0]


# ── Case 6: 变式题结构与复习 session 兼容 ──────────────────────────────────────
def c6_variant_compatible_with_session() -> None:
    """变式题应包含 done/correct 字段，与 review submit_answer 兼容。"""
    from services.variant_service import generate_variant
    result = generate_variant(TAG)

    assert "done" in result, "变式题应含 done 字段（供 review session 用）"
    assert "correct" in result, "变式题应含 correct 字段"
    assert result["tag"] == TAG


if __name__ == "__main__":
    cases = [
        ("C1 审定变式结构合法", c1_reviewed_structure),
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
