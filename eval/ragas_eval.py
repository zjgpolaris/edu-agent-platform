"""Ragas evaluation for RAG pipeline quality."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

DATASET_PATH = Path(__file__).parent / "datasets" / "ragas_cases.json"

try:
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_recall
    from ragas.dataset import Dataset as RagasDataset
    from langchain_anthropic import ChatAnthropic
    RAGAS_AVAILABLE = True
except Exception as exc:
    RAGAS_AVAILABLE = False
    _IMPORT_ERROR = str(exc)

from rag.knowledge_base import search_with_scores
from llm_config import llm_quality


def _doc_to_text(doc: Any) -> str:
    """Extract text from a document object."""
    if hasattr(doc, "page_content"):
        return doc.page_content
    if isinstance(doc, dict):
        return doc.get("text", "") or doc.get("content", "")
    return str(doc)


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run a single Ragas evaluation case."""
    question = case["question"]
    ground_truth = case["ground_truth"]

    # 1. Retrieve contexts if empty
    contexts_input = case.get("contexts", [])
    if not contexts_input:
        scored = search_with_scores("history", question, k=5, mode="hybrid")
        contexts_input = [_doc_to_text(item["document"]) for item in scored]

    # 2. Generate answer if empty
    answer_input = case.get("answer", "")
    if not answer_input:
        messages = [
            {"role": "system", "content": "你是一个历史知识助手，根据提供的史料回答问题。"},
            {"role": "user", "content": f"史料：\n{chr(10).join(contexts_input[:3])}\n\n问题：{question}"},
        ]
        response = llm_quality.invoke(messages)
        answer_input = response.content

    return {
        "name": case["name"],
        "question": question,
        "answer": answer_input,
        "contexts": contexts_input,
        "ground_truth": ground_truth,
    }


def main() -> None:
    if not RAGAS_AVAILABLE:
        print("SKIP ragas_eval: ragas package not installed or import failed")
        print(f"Error: {_IMPORT_ERROR}")
        print("Install with: pip install ragas>=0.2.0 langchain-anthropic>=0.3.0")
        return

    # Configure Ragas LLM judge (Anthropic)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    if not anthropic_key:
        print("SKIP ragas_eval: ANTHROPIC_API_KEY not set for Ragas LLM judge")
        return

    try:
        from ragas.llms import LangchainLLMWrapper
        judge_llm = LangchainLLMWrapper(
            ChatAnthropic(
                model=os.getenv("ANTHROPIC_MODEL_QUALITY", "claude-3-5-sonnet-20241022"),
                api_key=anthropic_key,
                base_url=os.getenv("ANTHROPIC_BASE_URL"),
            )
        )
        faithfulness.llm = judge_llm
        answer_relevancy.llm = judge_llm
        context_recall.llm = judge_llm
    except Exception as exc:
        print(f"SKIP ragas_eval: failed to configure Ragas LLM judge: {exc}")
        return

    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    results = [run_case(case) for case in cases]

    # Build Ragas Dataset (0.2.x API)
    ragas_data = {
        "question": [r["question"] for r in results],
        "answer": [r["answer"] for r in results],
        "contexts": [r["contexts"] for r in results],
        "ground_truth": [r["ground_truth"] for r in results],
    }
    dataset = RagasDataset.from_dict(ragas_data)

    # Run evaluation
    metrics = [faithfulness, answer_relevancy, context_recall]
    try:
        score_result = evaluate(dataset, metrics)
    except Exception as exc:
        print(f"Ragas evaluation failed: {exc}")
        return

    # Print results in X/Y format compatible with run_core_evals.py
    print(f"Ragas evaluation: {len(results)} cases")
    metric_results = {}
    for metric in metrics:
        name = metric.name
        scores = score_result.get(name, [])
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        passed = sum(1 for s in scores if s >= 0.6)
        metric_results[f"{name}_pass_rate"] = passed
        for i, s in enumerate(scores):
            status = "OK" if s >= 0.6 else "FAIL"
            print(f"{status} {results[i]['name']}_{name}: {s:.3f}")
        print(f"{name}_pass_rate={passed}/{len(results)}")

    # Check pass threshold (0.6)
    threshold = 0.6
    failures = []
    for metric in metrics:
        name = metric.name
        scores = score_result.get(name, [])
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        for i, s in enumerate(scores):
            if s < threshold:
                failures.append(f"{results[i]['name']}_{name}")

    if failures:
        print(f"failed cases: {', '.join(failures)}")
        raise SystemExit(f"failed cases: {', '.join(failures)}")


if __name__ == "__main__":
    main()
