"""Deterministic no-answer behavior for all seed cases."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tools import history_search


def main() -> None:
    cases = json.loads((ROOT / "eval" / "datasets" / "history_no_answer_cases.json").read_text(encoding="utf-8"))
    original = history_search.search_with_scores_and_diagnostics
    passed = 0
    try:
        history_search.search_with_scores_and_diagnostics = lambda *args, **kwargs: (
            [],
            {"fusion": "rrf", "reranker": {"status": "skipped", "reason_code": "model_not_configured"}},
        )
        for case in cases:
            result = history_search.search_history_knowledge({
                "query": case["query"],
                "topic": case["expected_entity"],
            }).model_dump()
            if result["ok"] is True and result["data"]["retrieval_status"] == "none":
                passed += 1
    finally:
        history_search.search_with_scores_and_diagnostics = original
    if passed != len(cases):
        raise SystemExit(f"history_no_answer_eval=FAIL {passed}/{len(cases)}")
    print(f"history_no_answer_eval=PASS cases={passed}")


if __name__ == "__main__":
    main()

