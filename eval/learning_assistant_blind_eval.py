"""Aggregate-only private blind evaluation.

The private dataset is injected through EDU_AGENT_BLIND_EVAL_PATH. This suite
never prints prompts, labels, case ids, confusion rows, or the source path.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from agents.learning_assistant_router import route_learning_request
from learning_assistant_dataset_schema import ReviewedRoutingCase
from llm_config import llm_fast


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _llm_credentials_available() -> bool:
    if os.getenv("EDU_AGENT_LLM_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    provider = os.getenv("LLM_PROVIDER", "bailian").strip().lower()
    bailian_available = bool(os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
    if provider in {"bailian", "dashscope"}:
        return bailian_available
    return False


def _load_private_cases() -> list[ReviewedRoutingCase]:
    configured = os.getenv("EDU_AGENT_BLIND_EVAL_PATH")
    if not configured:
        raise RuntimeError("blind_dataset_not_configured")
    path = Path(configured).expanduser().resolve()
    if ROOT == path or ROOT in path.parents:
        raise RuntimeError("blind_dataset_must_be_outside_repository")
    if not path.is_file():
        raise RuntimeError("blind_dataset_not_available")
    cases = [ReviewedRoutingCase.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(cases) < 200:
        raise RuntimeError("blind_dataset_below_minimum_size")
    if len({case.id for case in cases}) != len(cases):
        raise RuntimeError("blind_dataset_contains_duplicate_ids")
    return cases


def main() -> None:
    try:
        cases = _load_private_cases()
    except Exception as exc:
        # Only a fixed error code is printed. Never include the configured path
        # or Pydantic input details in CI artifacts.
        code = str(exc) if str(exc) in {
            "blind_dataset_not_configured",
            "blind_dataset_must_be_outside_repository",
            "blind_dataset_not_available",
            "blind_dataset_below_minimum_size",
            "blind_dataset_contains_duplicate_ids",
        } else "blind_dataset_invalid"
        if code == "blind_dataset_not_configured":
            print("real_llm_calls=0")
            print("SKIP learning_assistant_blind_eval: blind_dataset_not_configured")
            return
        print("FAIL blind_private_aggregate")
        print(f"blind_dataset_error={code}")
        raise SystemExit(1)

    if not _llm_credentials_available():
        print("real_llm_calls=0")
        print("SKIP learning_assistant_blind_eval: llm_credentials_not_configured")
        return

    confusion: Counter[tuple[str, str]] = Counter()
    correct = 0
    clarification_correct = 0
    high_risk_total = 0
    high_risk_correct = 0
    real_calls = 0
    semantic_enabled = os.getenv("EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    for case in cases:
        request = case.request.model_dump(mode="json")
        rule_route, semantic_route = route_learning_request(
            request,
            llm=llm_fast,
            semantic_enabled=semantic_enabled,
            shadow_mode=True,
        )
        route = semantic_route or rule_route
        if semantic_route is not None:
            real_calls += 1
        predicted = route.tasks[0].intent.value
        expected = case.expected.primary_intent
        confusion[(expected, predicted)] += 1
        if predicted == expected:
            correct += 1
        if route.needs_clarification == case.expected.needs_clarification:
            clarification_correct += 1
        if "high_risk" in case.challenge_tags:
            high_risk_total += 1
            if predicted == expected:
                high_risk_correct += 1

    labels = sorted({expected for expected, _ in confusion})
    f1_values = []
    for label in labels:
        tp = confusion[(label, label)]
        fp = sum(value for (expected, predicted), value in confusion.items() if predicted == label and expected != label)
        fn = sum(value for (expected, predicted), value in confusion.items() if expected == label and predicted != label)
        f1_values.append(_f1(tp, fp, fn))
    total = len(cases)
    accuracy = correct / total
    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0
    clarification_accuracy = clarification_correct / total
    high_risk_recall = high_risk_correct / high_risk_total if high_risk_total else 1.0

    print(f"blind_case_count={total}")
    print(f"blind_primary_intent_accuracy={accuracy:.4f}")
    print(f"blind_macro_f1={macro_f1:.4f}")
    print(f"blind_clarification_accuracy={clarification_accuracy:.4f}")
    print(f"blind_high_risk_recall={high_risk_recall:.4f}")
    print(f"real_llm_calls={real_calls}")
    print(f"real_llm_call_rate={real_calls}/{total}")
    if accuracy < 0.90 or macro_f1 < 0.88 or high_risk_recall < 1.0:
        print("FAIL blind_private_aggregate")
        raise SystemExit(1)
    print("OK blind_private_aggregate")
    print("learning_assistant_blind_eval=1/1")


if __name__ == "__main__":
    main()
