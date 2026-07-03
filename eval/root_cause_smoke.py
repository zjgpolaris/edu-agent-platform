#!/usr/bin/env python3
"""
薄弱点根因诊断 smoke test
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-root-cause-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.root_cause_service import (
    analyze_root_cause,
    get_latest_root_cause,
    get_root_cause_summary,
    RootCause,
)


def run_case(name: str, fn):
    print(f"  ⏳ {name}...", end=" ", flush=True)
    try:
        fn()
        print("✅")
    except AssertionError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"❌ unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)


def test_analyze_concept_error():
    """C1: 分析概念模糊类错误"""
    result = analyze_root_cause(
        student_id="rc_c1",
        knowledge_tag="秦始皇统一",
        question_text="秦始皇统一六国后采取的措施中，哪项不属于文化统一？A.统一文字 B.焚书坑儒 C.统一货币 D.统一度量衡",
        student_answer="B",
        correct_answer="C",
        wrong_count=3,
    )
    assert result["root_cause"] in [e.value for e in RootCause]
    assert "label" in result
    assert "icon" in result
    assert "description" in result
    assert "tip" in result
    assert 0 <= result["confidence"] <= 1


def test_analyze_memory_error():
    """C2: 分析知识遗忘类错误"""
    result = analyze_root_cause(
        student_id="rc_c2",
        knowledge_tag="鸦片战争",
        question_text="鸦片战争爆发的时间是？A.1839 B.1840 C.1841 D.1842",
        student_answer="A",
        correct_answer="B",
        wrong_count=1,
    )
    assert result["root_cause"] in [e.value for e in RootCause]
    # 错误次数少，可能是遗忘
    assert result["label"] is not None


def test_analyze_careless_error():
    """C3: 分析粗心大意类错误 — 答案只差一个字符"""
    result = analyze_root_cause(
        student_id="rc_c3",
        knowledge_tag="辛亥革命",
        question_text="辛亥革命推翻了哪个朝代？",
        student_answer="清",  # 接近正确答案
        correct_answer="清朝",
        wrong_count=1,
    )
    # 规则降级应识别为粗心（答案接近）
    assert result["root_cause"] in [e.value for e in RootCause]


def test_get_latest_root_cause():
    """C4: 获取最新根因诊断"""
    # 先分析一次
    analyze_root_cause(
        "rc_c4", "洋务运动", "洋务运动的代表人物？",
        "李鸿章、张之洞", "李鸿章、曾国藩、左宗棠、张之洞", 2
    )

    # 获取最新诊断
    result = get_latest_root_cause("rc_c4", "洋务运动")
    assert result is not None
    assert result["root_cause"] in [e.value for e in RootCause]
    assert "analyzed_at" in result


def test_get_latest_root_cause_not_found():
    """C5: 获取不存在的根因诊断 — 返回 None"""
    result = get_latest_root_cause("rc_c5", "不存在的知识点")
    assert result is None


def test_get_root_cause_summary():
    """C6: 获取根因分布统计"""
    # 先分析多个知识点
    for i, (tag, wrong_count) in enumerate([
        ("知识点A", 4),  # 概念模糊
        ("知识点B", 1),  # 知识遗忘
        ("知识点C", 2),  # 知识遗忘
    ]):
        analyze_root_cause(
            "rc_c6", tag, f"题目{i}", "错答", "正答", wrong_count
        )

    summary = get_root_cause_summary("rc_c6")
    assert isinstance(summary, dict)
    assert "concept" in summary
    assert "memory" in summary
    assert "comprehension" in summary
    assert "careless" in summary
    # 至少有一些记录
    total = sum(summary.values())
    assert total >= 3


def test_multiple_analyses_same_tag():
    """C7: 同一知识点多次分析 — 记录多条"""
    tag = "多次分析测试"
    for i in range(3):
        analyze_root_cause(
            "rc_c7", tag, f"第{i+1}次", "错", "对", i + 1
        )

    # 获取最新的一次
    result = get_latest_root_cause("rc_c7", tag)
    assert result is not None

    # 统计应包含这些记录
    summary = get_root_cause_summary("rc_c7")
    assert sum(summary.values()) >= 3


def test_rule_based_fallback():
    """C8: 规则降级分类 — 无 LLM 时仍能工作"""
    # 错误次数多 → 概念模糊
    result1 = analyze_root_cause(
        "rc_c8", "高错误次数", "题", "错", "对", wrong_count=5
    )
    # 规则降级应该能给出分类
    assert result1["root_cause"] in [e.value for e in RootCause]

    # 错误次数少 → 知识遗忘
    result2 = analyze_root_cause(
        "rc_c8", "低错误次数", "题", "错", "对", wrong_count=1
    )
    assert result2["root_cause"] in [e.value for e in RootCause]


def main():
    print("root_cause_smoke.py — 薄弱点根因诊断 smoke test")
    run_case("C1: 分析概念模糊类错误", test_analyze_concept_error)
    run_case("C2: 分析知识遗忘类错误", test_analyze_memory_error)
    run_case("C3: 分析粗心大意类错误", test_analyze_careless_error)
    run_case("C4: 获取最新根因诊断", test_get_latest_root_cause)
    run_case("C5: 不存在的根因返回None", test_get_latest_root_cause_not_found)
    run_case("C6: 获取根因分布统计", test_get_root_cause_summary)
    run_case("C7: 同一知识点多次分析", test_multiple_analyses_same_tag)
    run_case("C8: 规则降级分类仍可用", test_rule_based_fallback)
    print("✅ 8/8 all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
