"""意图识别准确率评测

量化评测 learning_assistant 意图分类的准确率、置信度分布和工具命中率。
对应文章 L1 组件评测：意图识别准确率和澄清率 / 工具 Top-K 命中率。

运行方式：
    python3 eval/intent_accuracy_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.learning_assistant import detect_learning_intent

# ---------------------------------------------------------------------------
# 标注数据集：(query, grade, expected_intent)
# ---------------------------------------------------------------------------
LABELED_CASES = [
    # ── character_recommendation ──────────────────────────────────────────
    ("推荐一个能讲汉代的历史人物", "七年级下册", "character_recommendation"),
    ("我想和历史人物对话，了解三国时期", "七年级下册", "character_recommendation"),
    ("推荐适合七年级的历史人物", "七年级上册", "character_recommendation"),
    # ── timeline_game ─────────────────────────────────────────────────────
    ("来一局历史时间线排序游戏", "八年级上册", "timeline_game"),
    ("开始时间排序小游戏", "七年级上册", "timeline_game"),
    ("玩个历史排序", "八年级下册", "timeline_game"),
    # ── quiz_generation ───────────────────────────────────────────────────
    ("帮我出 5 道练习题", "八年级上册", "quiz_generation"),
    ("出几道关于鸦片战争的选择题", "八年级上册", "quiz_generation"),
    ("给我出测验题", "九年级上册", "quiz_generation"),
    # ── review_plan ───────────────────────────────────────────────────────
    ("我最近错了很多题，帮我安排复习", "八年级上册", "review_plan"),
    ("生成今天的复习计划", "七年级下册", "review_plan"),
    # ── history_search ────────────────────────────────────────────────────
    ("鸦片战争的原因是什么？", "八年级上册", "history_search"),
    ("辛亥革命有什么意义？", "八年级上册", "history_search"),
    ("商鞅变法对秦国有哪些影响？", "七年级上册", "history_search"),
    ("五四运动是怎么发生的", "八年级上册", "history_search"),
    # ── textbook_qa ───────────────────────────────────────────────────────
    ("这节课讲了什么？", "七年级上册", "textbook_qa"),
    # ── chat / fallback ──────────────────────────────────────────────────
    ("你好", "七年级上册", "chat"),
    ("今天天气怎么样", "七年级上册", "chat"),
]

# 意图 → 预期触发的工具名（空表示不调用工具）
INTENT_TO_TOOL: dict[str, str | None] = {
    "character_recommendation": "recommend_character",
    "timeline_game": "start_timeline_game",
    "quiz_generation": "generate_quiz",
    "review_plan": "suggest_review_plan",
    "history_search": "search_history_knowledge",
    "textbook_qa": "get_textbook_lesson",
    "memory_delete_demo": "delete_demo_memory",
    "chat": None,
}

# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def run() -> None:
    total = len(LABELED_CASES)
    correct = 0
    wrong_cases: list[dict] = []
    confidence_sum = 0.0
    low_conf_count = 0  # < 0.7

    print(f"Running intent accuracy eval on {total} labeled cases...\n")

    for query, grade, expected in LABELED_CASES:
        result = detect_learning_intent({"message": query, "grade": grade})
        predicted = result.get("intent", "chat")
        confidence = float(result.get("confidence", 0.0))
        confidence_sum += confidence

        if confidence < 0.7:
            low_conf_count += 1

        if predicted == expected:
            correct += 1
        else:
            wrong_cases.append({
                "query": query,
                "expected": expected,
                "predicted": predicted,
                "confidence": round(confidence, 3),
                "reason": result.get("reason", ""),
            })

    accuracy = correct / total
    avg_confidence = confidence_sum / total

    # ── 打印每个错误 ────────────────────────────────────────────────────
    if wrong_cases:
        print("=== Misclassified cases ===")
        for wc in wrong_cases:
            print(f"  WRONG  query={wc['query']!r}")
            print(f"         expected={wc['expected']}  predicted={wc['predicted']}  conf={wc['confidence']}")
            print(f"         reason={wc['reason']}")
        print()

    # ── 汇总指标 ────────────────────────────────────────────────────────
    print("=== Intent Accuracy Metrics ===")
    print(f"  accuracy:          {correct}/{total} = {accuracy:.1%}")
    print(f"  avg_confidence:    {avg_confidence:.3f}")
    print(f"  low_conf_rate:     {low_conf_count}/{total} (conf < 0.70)")
    print(f"  wrong_count:       {len(wrong_cases)}")
    print()

    # ── 按意图分组准确率 ───────────────────────────────────────────────
    from collections import defaultdict
    per_intent: dict[str, list[bool]] = defaultdict(list)
    for query, grade, expected in LABELED_CASES:
        result = detect_learning_intent({"message": query, "grade": grade})
        predicted = result.get("intent", "chat")
        per_intent[expected].append(predicted == expected)

    print("=== Per-Intent Accuracy ===")
    for intent, results in sorted(per_intent.items()):
        n = len(results)
        n_correct = sum(results)
        print(f"  {intent:<30} {n_correct}/{n} = {n_correct/n:.0%}")

    print()
    if accuracy < 0.80:
        raise SystemExit(
            f"FAIL: intent accuracy {accuracy:.1%} is below threshold 80%"
        )
    print(f"PASS: intent accuracy {accuracy:.1%}")


if __name__ == "__main__":
    run()
