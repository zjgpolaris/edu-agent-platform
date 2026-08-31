"""Small run-scoped real-model routing evaluation used by release evidence."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.learning_assistant_router import route_learning_request
from llm_config import llm_fast


CASES = [
    ({"message": "先解释洋务运动，再给我出两道题"}, ["history_search", "quiz_generation"]),
    ({"message": "先讲清楚辛亥革命，然后考我三道选择题"}, ["history_search", "quiz_generation"]),
    ({"message": "这个我还是不懂，换个说法", "conversation_history": [{"role": "user", "content": "洋务运动为什么失败"}]}, ["history_search"]),
    ({"message": "帮我安排一下后面怎么学"}, ["review_plan"]),
    ({"message": "给我弄点题练练"}, ["quiz_generation"]),
    ({"message": "今天外面热不热"}, ["chat"]),
]


def _llm_credentials_available() -> bool:
    if os.getenv("EDU_AGENT_LLM_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    provider = os.getenv("LLM_PROVIDER", "bailian").strip().lower()
    bailian_available = bool(os.getenv("BAILIAN_API_KEY"))
    if provider in {"bailian", "dashscope"}:
        return bailian_available
    return False


def main() -> None:
    if not _llm_credentials_available():
        print("real_llm_calls=0")
        print("SKIP learning_assistant_semantic_router_eval: llm_credentials_not_configured")
        return

    correct = 0
    real_calls = 0
    for request, expected in CASES:
        route, _ = route_learning_request(request, llm=llm_fast, semantic_enabled=True, shadow_mode=False)
        predicted = [task.intent.value for task in route.tasks]
        if route.mode in {"semantic", "clarification"}:
            real_calls += 1
        if predicted == expected:
            correct += 1
    total = len(CASES)
    print(f"semantic_router_accuracy={correct}/{total}")
    print(f"real_llm_calls={real_calls}")
    print(f"real_llm_call_rate={real_calls}/{total}")
    if real_calls == 0:
        print("FAIL semantic_router_real_model_not_observed")
        raise SystemExit(1)
    if correct / total < 0.80:
        print("FAIL semantic_router_quality_threshold")
        raise SystemExit(1)
    print("OK semantic_router_real_model")
    print("learning_assistant_semantic_router_eval=1/1")


if __name__ == "__main__":
    main()
