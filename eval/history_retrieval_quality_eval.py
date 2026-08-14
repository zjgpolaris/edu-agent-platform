"""Real history retrieval quality gate.

This suite is intentionally opt-in until the seed labels receive teacher review.
It exercises the actual pgvector/embedding/reranker stack rather than mocks.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tools.history_search import search_history_knowledge


def _dcg(values: list[int]) -> float:
    return sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(values))


def main() -> None:
    if os.getenv("HISTORY_RETRIEVAL_PRODUCTION_EVAL", "").lower() not in {"1", "true", "yes"}:
        print("SKIP history_retrieval_quality_eval: set HISTORY_RETRIEVAL_PRODUCTION_EVAL=1 after teacher review")
        return
    cases = json.loads((ROOT / "eval" / "datasets" / "history_retrieval_cases.json").read_text(encoding="utf-8"))
    pending = [case["id"] for case in cases if case.get("review_status") != "teacher_reviewed"]
    if pending and os.getenv("HISTORY_RETRIEVAL_ALLOW_PENDING_REVIEW", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit(f"history_retrieval_quality_eval=NOT_RUN pending_teacher_review={len(pending)}")

    entity_hits = 0
    aspect_hits = 0
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    for case in cases:
        result = search_history_knowledge({
            "query": case["query"],
            "topic": case["expected_entity"],
            "k": 5,
        }).model_dump()
        sources = result["data"]["sources"]
        entity_hits += any(source.get("entity_match") for source in sources)
        aspect_hits += any(source.get("answer_bearing") for source in sources)
        relevance = [2 if source.get("answer_bearing") else 1 if source.get("entity_match") else 0 for source in sources]
        first_answer = next((index for index, value in enumerate(relevance, start=1) if value == 2), None)
        reciprocal_ranks.append(1.0 / first_answer if first_answer else 0.0)
        ideal = sorted(relevance, reverse=True)
        ideal_dcg = _dcg(ideal)
        ndcgs.append(_dcg(relevance) / ideal_dcg if ideal_dcg else 0.0)

    total = len(cases)
    entity_recall = entity_hits / total if total else 0.0
    aspect_recall = aspect_hits / total if total else 0.0
    mrr = sum(reciprocal_ranks) / total if total else 0.0
    ndcg = sum(ndcgs) / total if total else 0.0
    print(f"history_entity_recall_at_5={entity_recall:.4f}")
    print(f"history_aspect_recall_at_5={aspect_recall:.4f}")
    print(f"history_mrr_at_5={mrr:.4f}")
    print(f"history_ndcg_at_5={ndcg:.4f}")
    if entity_recall < 0.98 or aspect_recall < 0.92 or mrr < 0.88 or ndcg < 0.85:
        raise SystemExit("history_retrieval_quality_eval=FAIL")
    print(f"history_retrieval_quality_eval=PASS cases={total}")


if __name__ == "__main__":
    main()

