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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.history_retrieval_review import validate_reviewed_case
from tools.history_search import search_history_knowledge


def _dcg(values: list[int]) -> float:
    return sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(values))


def reviewed_relevance(
    sources: list[dict],
    judgments: dict[str, int],
) -> tuple[list[int], int]:
    """Grade retrieved sources only from human labels, never system flags."""
    relevance: list[int] = []
    unjudged = 0
    for source in sources:
        source_id = str(source.get("source_id") or "")
        if not source_id or source_id not in judgments:
            unjudged += 1
            relevance.append(0)
            continue
        relevance.append(int(judgments[source_id]))
    return relevance, unjudged


def main() -> None:
    if os.getenv("HISTORY_RETRIEVAL_PRODUCTION_EVAL", "").lower() not in {"1", "true", "yes"}:
        print("SKIP history_retrieval_quality_eval: set HISTORY_RETRIEVAL_PRODUCTION_EVAL=1 after teacher review")
        return
    cases = json.loads((ROOT / "eval" / "datasets" / "history_retrieval_cases.json").read_text(encoding="utf-8"))
    invalid_reviews = [validate_reviewed_case(case) for case in cases]
    invalid_reviews = [failures for failures in invalid_reviews if failures]
    if invalid_reviews:
        reason_counts: dict[str, int] = {}
        for failures in invalid_reviews:
            for reason in failures:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        summary = ",".join(f"{reason}:{count}" for reason, count in sorted(reason_counts.items()))
        raise SystemExit(
            f"history_retrieval_quality_eval=NOT_RUN invalid_teacher_reviews={len(invalid_reviews)} reasons={summary}"
        )

    entity_hits = 0
    aspect_hits = 0
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    retrieved_source_count = 0
    judged_source_count = 0
    unjudged_source_count = 0
    for case in cases:
        judgments = {
            str(item["source_id"]): int(item["relevance"])
            for item in case["source_judgments"]
        }
        result = search_history_knowledge({
            "query": case["query"],
            "topic": case["expected_entity"],
            "k": 5,
        }).model_dump()
        sources = result["data"]["sources"]
        source_ids = [str(source.get("source_id") or "") for source in sources]
        retrieved_source_count += len(source_ids)
        judged_source_count += sum(source_id in judgments for source_id in source_ids)
        relevance, unjudged = reviewed_relevance(sources, judgments)
        unjudged_source_count += unjudged
        entity_hits += any(value >= 1 for value in relevance)
        aspect_hits += any(value == 2 for value in relevance)
        first_answer = next((index for index, value in enumerate(relevance, start=1) if value == 2), None)
        reciprocal_ranks.append(1.0 / first_answer if first_answer else 0.0)
        ideal = (sorted(judgments.values(), reverse=True) + [0] * len(relevance))[: len(relevance)]
        ideal_dcg = _dcg(ideal)
        ndcgs.append(_dcg(relevance) / ideal_dcg if ideal_dcg else 0.0)

    total = len(cases)
    entity_recall = entity_hits / total if total else 0.0
    aspect_recall = aspect_hits / total if total else 0.0
    mrr = sum(reciprocal_ranks) / total if total else 0.0
    ndcg = sum(ndcgs) / total if total else 0.0
    judged_coverage = judged_source_count / retrieved_source_count if retrieved_source_count else 0.0
    print(f"history_entity_recall_at_5={entity_recall:.4f}")
    print(f"history_aspect_recall_at_5={aspect_recall:.4f}")
    print(f"history_mrr_at_5={mrr:.4f}")
    print(f"history_ndcg_at_5={ndcg:.4f}")
    print(f"history_judged_source_coverage={judged_coverage:.4f}")
    print(f"history_unjudged_source_count={unjudged_source_count}")
    if unjudged_source_count or judged_coverage < 1.0:
        raise SystemExit("history_retrieval_quality_eval=NOT_RUN current_top_sources_require_teacher_review")
    if entity_recall < 0.98 or aspect_recall < 0.92 or mrr < 0.88 or ndcg < 0.85:
        raise SystemExit("history_retrieval_quality_eval=FAIL")
    print(f"history_retrieval_quality_eval=PASS cases={total}")


if __name__ == "__main__":
    main()
