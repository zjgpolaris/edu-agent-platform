"""Smoke test: AI 出题结构质检（确定性）+ 语义质检合并（stub LLM，离线）"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.question_quality import (
    check_question,
    check_question_semantic,
    merge_quality,
    summarize_quality,
)


class _StubLLM:
    """离线桩：invoke 返回预置 JSON 内容，模拟 LLM 语义判定。"""
    def __init__(self, payload: dict):
        self._payload = payload

    def invoke(self, messages):
        class _Resp:
            content = json.dumps(self._payload, ensure_ascii=False)
        return _Resp()


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


VALID_SC = {"type": "single_choice", "prompt": "鸦片战争爆发于哪一年？",
            "options": ["1840", "1842", "1856", "1860"], "answer": "A"}


def valid_single_choice_ok() -> None:
    r = check_question(VALID_SC)
    assert r["level"] == "ok", r
    assert r["issues"] == []


def three_options_is_error() -> None:
    r = check_question({**VALID_SC, "options": ["1840", "1842", "1856"]})
    assert r["level"] == "error", r
    assert any("选项" in i for i in r["issues"])


def invalid_answer_letter_is_error() -> None:
    r = check_question({**VALID_SC, "answer": "E"})
    assert r["level"] == "error", r
    assert any("答案" in i for i in r["issues"])


def duplicate_options_is_warn() -> None:
    r = check_question({**VALID_SC, "options": ["1840", "1840", "1856", "1860"]})
    # 重复是 warn，但答案与选项数仍合法
    assert r["level"] == "warn", r
    assert any("重复" in i for i in r["issues"])


def empty_prompt_is_error() -> None:
    r = check_question({**VALID_SC, "prompt": "   "})
    assert r["level"] == "error", r
    assert any("题干" in i for i in r["issues"])


def true_false_bad_answer_is_error() -> None:
    r = check_question({"type": "true_false", "prompt": "《南京条约》割让香港岛。", "answer": "对"})
    assert r["level"] == "error", r
    assert any("判断题" in i for i in r["issues"])


def true_false_valid_ok() -> None:
    r = check_question({"type": "true_false", "prompt": "《南京条约》割让香港岛。", "answer": "正确"})
    assert r["level"] == "ok", r


def subjective_missing_ref_is_warn() -> None:
    r = check_question({"type": "subjective", "prompt": "简述鸦片战争的历史影响。", "reference_answer": ""})
    assert r["level"] == "warn", r
    assert any("参考答案" in i for i in r["issues"])


def subjective_with_ref_ok() -> None:
    r = check_question({"type": "subjective", "prompt": "简述鸦片战争的历史影响。",
                        "explanation": "中国开始沦为半殖民地半封建社会。"})
    assert r["level"] == "ok", r


def summarize_counts() -> None:
    questions = [
        VALID_SC,                                                  # ok
        {**VALID_SC, "options": ["1", "2", "3"]},                  # error
        {**VALID_SC, "options": ["1840", "1840", "1856", "1860"]},  # warn
        {"type": "true_false", "prompt": "xxxxxx", "answer": "对"},   # error
    ]
    s = summarize_quality(questions)
    assert s == {"error_count": 2, "warn_count": 1}, s


# ── 语义质检（stub LLM）────────────────────────────────────────────────
def semantic_no_llm_is_unchecked() -> None:
    # 不传 llm → 降级，checked=False，不误报
    r = check_question_semantic(VALID_SC)
    assert r == {"level": "ok", "issues": [], "checked": False}, r


def semantic_detects_issue_error() -> None:
    llm = _StubLLM({"has_issue": True, "severity": "error", "issues": ["正确答案标注错误，1842 才对"]})
    r = check_question_semantic(VALID_SC, llm=llm)
    assert r["level"] == "error" and r["checked"] is True, r
    assert any("1842" in i for i in r["issues"]), r


def semantic_no_issue_ok() -> None:
    llm = _StubLLM({"has_issue": False, "severity": "warn", "issues": []})
    r = check_question_semantic(VALID_SC, llm=llm)
    assert r == {"level": "ok", "issues": [], "checked": True}, r


def merge_prefixes_and_takes_max_level() -> None:
    structural = {"level": "warn", "issues": ["存在重复选项"]}
    semantic = {"level": "error", "issues": ["答案错误"], "checked": True}
    m = merge_quality(structural, semantic)
    assert m["level"] == "error", m
    assert "存在重复选项" in m["issues"]
    assert "语义：答案错误" in m["issues"], m
    assert m["semantic_checked"] is True


def merge_ok_when_both_clean() -> None:
    m = merge_quality({"level": "ok", "issues": []}, {"level": "ok", "issues": [], "checked": True})
    assert m["level"] == "ok" and m["issues"] == [], m


if __name__ == "__main__":
    cases = [
        ("valid_single_choice_ok", valid_single_choice_ok),
        ("three_options_is_error", three_options_is_error),
        ("invalid_answer_letter_is_error", invalid_answer_letter_is_error),
        ("duplicate_options_is_warn", duplicate_options_is_warn),
        ("empty_prompt_is_error", empty_prompt_is_error),
        ("true_false_bad_answer_is_error", true_false_bad_answer_is_error),
        ("true_false_valid_ok", true_false_valid_ok),
        ("subjective_missing_ref_is_warn", subjective_missing_ref_is_warn),
        ("subjective_with_ref_ok", subjective_with_ref_ok),
        ("summarize_counts", summarize_counts),
        ("semantic_no_llm_is_unchecked", semantic_no_llm_is_unchecked),
        ("semantic_detects_issue_error", semantic_detects_issue_error),
        ("semantic_no_issue_ok", semantic_no_issue_ok),
        ("merge_prefixes_and_takes_max_level", merge_prefixes_and_takes_max_level),
        ("merge_ok_when_both_clean", merge_ok_when_both_clean),
    ]
    passed = sum(run_case(n, fn) for n, fn in cases)
    print(f"question_quality_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)
