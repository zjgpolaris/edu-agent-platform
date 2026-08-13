"""Learning-assistant v2 routing evaluation with intent, slot and clarification metrics."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DATASET = ROOT / "eval" / "datasets" / "learning_assistant_intent_cases.json"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.learning_assistant_router import deterministic_route, route_learning_request


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _slot_value(route, key: str):
    primary = route.tasks[0]
    return getattr(primary, key, None)


def _semantic_safety_eval() -> tuple[int, int]:
    class _Response:
        def __init__(self, payload: dict):
            self.content = json.dumps(payload, ensure_ascii=False)

    class _LLM:
        def __init__(self, payload: dict):
            self.payload = payload

        def invoke(self, messages):
            return _Response(self.payload)

    base = {"schema_version": 2, "mode": "semantic", "confidence": 0.91, "needs_clarification": False, "clarification_question": None, "missing_slots": [], "reason_code": "semantic_test"}
    reordered, _ = route_learning_request(
        {"message": "帮我处理一下后续学习"},
        llm=_LLM({**base, "tasks": [
            {"task_id": "x", "intent": "timeline_game", "topic": "洋务运动", "depends_on": []},
            {"task_id": "y", "intent": "history_search", "topic": "洋务运动", "depends_on": ["x"]},
        ]}),
        semantic_enabled=True,
        shadow_mode=False,
    )
    high_risk_blocked, _ = route_learning_request(
        {"message": "帮我处理一下后续学习"},
        llm=_LLM({**base, "tasks": [{"task_id": "x", "intent": "memory_delete_demo", "depends_on": []}]}),
        semantic_enabled=True,
        shadow_mode=False,
    )
    low_confidence, _ = route_learning_request(
        {"message": "帮我处理一下后续学习"},
        llm=_LLM({**base, "confidence": 0.4, "tasks": [{"task_id": "x", "intent": "chat", "depends_on": []}]}),
        semantic_enabled=True,
        shadow_mode=False,
    )
    checks = [
        [task.intent.value for task in reordered.tasks] == ["history_search", "timeline_game"] and reordered.tasks[1].depends_on == ["task_1"],
        all(task.intent.value != "memory_delete_demo" for task in high_risk_blocked.tasks),
        low_confidence.needs_clarification and low_confidence.mode == "clarification",
    ]
    return sum(checks), len(checks)


def main() -> None:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    labels = sorted({str(case["expected_primary_intent"]) for case in cases})
    confusion: Counter[tuple[str, str]] = Counter()
    failures: list[dict] = []
    correct = 0
    slot_total = 0
    slot_correct = 0
    clarification_tp = clarification_fp = clarification_fn = 0
    exact_multi_total = exact_multi_correct = 0
    mode_counts: Counter[str] = Counter()

    for case in cases:
        request = dict(case.get("request") or {})
        route = deterministic_route(request)
        expected = str(case["expected_primary_intent"])
        predicted = route.tasks[0].intent.value
        confusion[(expected, predicted)] += 1
        mode_counts[route.mode] += 1
        if expected == predicted:
            correct += 1
        else:
            failures.append({"id": case["id"], "message": request.get("message"), "expected": expected, "predicted": predicted, "reason": route.reason_code})

        expected_slots = case.get("expected_slots") or {}
        for key, value in expected_slots.items():
            slot_total += 1
            if _slot_value(route, key) == value:
                slot_correct += 1

        expected_clarification = bool(case.get("expected_clarification"))
        if route.needs_clarification and expected_clarification:
            clarification_tp += 1
        elif route.needs_clarification:
            clarification_fp += 1
        elif expected_clarification:
            clarification_fn += 1

        expected_intents = case.get("expected_intents") or [expected]
        if len(expected_intents) > 1:
            exact_multi_total += 1
            if [task.intent.value for task in route.tasks] == expected_intents:
                exact_multi_correct += 1

    total = len(cases)
    accuracy = correct / total if total else 0.0
    per_intent: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for label in labels:
        tp = confusion[(label, label)]
        fp = sum(value for (expected, predicted), value in confusion.items() if predicted == label and expected != label)
        fn = sum(value for (expected, predicted), value in confusion.items() if expected == label and predicted != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        score = _f1(tp, fp, fn)
        f1_values.append(score)
        per_intent[label] = {"support": tp + fn, "precision": precision, "recall": recall, "f1": score}

    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0
    slot_accuracy = slot_correct / slot_total if slot_total else 1.0
    clarification_precision = clarification_tp / (clarification_tp + clarification_fp) if clarification_tp + clarification_fp else 1.0
    clarification_recall = clarification_tp / (clarification_tp + clarification_fn) if clarification_tp + clarification_fn else 1.0
    multi_exact = exact_multi_correct / exact_multi_total if exact_multi_total else 1.0
    high_risk_total = sum(1 for case in cases if case["expected_primary_intent"] == "memory_delete_demo")
    high_risk_correct = confusion[("memory_delete_demo", "memory_delete_demo")]
    high_risk_recall = high_risk_correct / high_risk_total if high_risk_total else 1.0
    semantic_safety_passed, semantic_safety_total = _semantic_safety_eval()

    print(f"Running v2 intent accuracy eval on {total} labeled cases...\n")
    if failures:
        print("=== Misclassified cases (first 20) ===")
        for failure in failures[:20]:
            print("  " + json.dumps(failure, ensure_ascii=False))
        print()
    print("=== Routing Metrics ===")
    print(f"accuracy={accuracy:.4f}")
    print(f"macro_f1={macro_f1:.4f}")
    print(f"slot_accuracy={slot_accuracy:.4f}")
    print(f"clarification_precision={clarification_precision:.4f}")
    print(f"clarification_recall={clarification_recall:.4f}")
    print(f"multi_intent_exact_match={multi_exact:.4f}")
    print(f"high_risk_intent_recall={high_risk_recall:.4f}")
    print(f"semantic_schema_safety={semantic_safety_passed / semantic_safety_total if semantic_safety_total else 1.0:.4f}")
    print("routing_mode_distribution=" + json.dumps(mode_counts, ensure_ascii=False, sort_keys=True))
    print("confusion_matrix=" + json.dumps({f"{expected}->{predicted}": value for (expected, predicted), value in sorted(confusion.items())}, ensure_ascii=False))
    print()
    print("=== Per-Intent Metrics ===")
    for label, metrics in per_intent.items():
        print(f"{label}: support={metrics['support']} precision={metrics['precision']:.3f} recall={metrics['recall']:.3f} f1={metrics['f1']:.3f}")

    failed_thresholds = []
    if accuracy < 0.90:
        failed_thresholds.append(f"accuracy {accuracy:.1%} < 90%")
    if macro_f1 < 0.88:
        failed_thresholds.append(f"macro_f1 {macro_f1:.3f} < 0.88")
    if slot_accuracy < 0.88:
        failed_thresholds.append(f"slot_accuracy {slot_accuracy:.1%} < 88%")
    if clarification_precision < 0.85:
        failed_thresholds.append(f"clarification_precision {clarification_precision:.1%} < 85%")
    if high_risk_recall < 1.0:
        failed_thresholds.append(f"high_risk_recall {high_risk_recall:.1%} < 100%")
    if semantic_safety_passed != semantic_safety_total:
        failed_thresholds.append(f"semantic_schema_safety {semantic_safety_passed}/{semantic_safety_total}")
    if failed_thresholds:
        raise SystemExit("FAIL: " + "; ".join(failed_thresholds))
    print(f"intent_accuracy_eval={correct}/{total}")


if __name__ == "__main__":
    main()
