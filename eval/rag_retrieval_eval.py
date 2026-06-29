import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

DATASET_PATH = Path(__file__).parent / "datasets" / "rag_retrieval_cases.json"


def _embedding_ready() -> bool:
    path = os.getenv("EMBED_MODEL_PATH")
    return bool(path and Path(path).exists())


def _haystack(doc) -> str:
    metadata = getattr(doc, "metadata", {}) or {}
    return getattr(doc, "page_content", "") + " " + " ".join(str(value) for value in metadata.values())


def _contains_keyword(doc, keywords: list[str]) -> bool:
    haystack = _haystack(doc)
    return any(keyword in haystack for keyword in keywords)


def _metadata_value_contains(actual, expected: str) -> bool:
    if isinstance(actual, list):
        return any(_metadata_value_contains(item, expected) for item in actual)
    actual_text = str(actual or "")
    return expected in actual_text or actual_text in expected


def _metadata_matches(doc, expected: dict[str, str]) -> bool:
    metadata = getattr(doc, "metadata", {}) or {}
    for key, value in expected.items():
        if not _metadata_value_contains(metadata.get(key), value):
            return False
    return True


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    scored_docs = search_with_scores(
        "history",
        case["query"],
        k=5,
        metadata_filter=case.get("metadata_filter"),
        mode="hybrid",
        metadata_hints=case.get("metadata_hints"),
    )
    docs = [item["document"] for item in scored_docs]
    keywords = case.get("expected_keywords") or []
    expected_metadata = case.get("expected_metadata") or {}
    top = docs[0] if docs else None
    top_scored = scored_docs[0] if scored_docs else None

    return {
        "name": case["name"],
        "source_returned": bool(docs),
        "top1_keyword_hit": bool(top and _contains_keyword(top, keywords)),
        "any_keyword_hit": any(_contains_keyword(doc, keywords) for doc in docs),
        "top1_metadata_hit": bool(top and expected_metadata and _metadata_matches(top, expected_metadata)),
        "any_metadata_hit": bool(expected_metadata and any(_metadata_matches(doc, expected_metadata) for doc in docs)),
        "top_topic": (top.metadata or {}).get("topic", "") if top else "",
        "top_grade": (top.metadata or {}).get("grade", "") if top else "",
        "top_score": round(float(top_scored["score"]), 3) if top_scored else 0.0,
        "top_mode": top_scored["source_mode"] if top_scored else "",
        "sources": len(docs),
    }


def main() -> None:
    if not _embedding_ready():
        print("SKIP rag_retrieval_eval: EMBED_MODEL_PATH is not set or does not exist")
        return
    global search_with_scores
    from rag.knowledge_base import search_with_scores
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    results = [run_case(case) for case in cases]

    for result in results:
        status = "OK" if result["source_returned"] and result["any_keyword_hit"] else "FAIL"
        print(
            f"{status} {result['name']}: "
            f"top_topic={result['top_topic']} top_grade={result['top_grade']} "
            f"top_score={result['top_score']} top_mode={result['top_mode']} "
            f"top1_keyword={result['top1_keyword_hit']} any_keyword={result['any_keyword_hit']} "
            f"top1_metadata={result['top1_metadata_hit']} any_metadata={result['any_metadata_hit']} "
            f"sources={result['sources']}"
        )

    total = len(results)
    metrics = {
        "source_return_rate": sum(item["source_returned"] for item in results),
        "top1_keyword_hit_rate": sum(item["top1_keyword_hit"] for item in results),
        "any_keyword_hit_rate": sum(item["any_keyword_hit"] for item in results),
        "top1_metadata_hit_rate": sum(item["top1_metadata_hit"] for item in results),
        "any_metadata_hit_rate": sum(item["any_metadata_hit"] for item in results),
    }
    print()
    for name, count in metrics.items():
        print(f"{name}={count}/{total}")

    failures = [item["name"] for item in results if not item["source_returned"] or not item["any_keyword_hit"]]
    if failures:
        raise SystemExit(f"failed cases: {', '.join(failures)}")


if __name__ == "__main__":
    main()
