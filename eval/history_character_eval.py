import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from agents.history_character import build_character_graph, detect_mode, generate_fact_card
from llm_config import llm_fast
from rag.knowledge_base import get_retriever

DATASET_PATH = Path(__file__).parent / "datasets" / "history_character_cases.json"
REQUIRED_SECTIONS = ["【回答】", "【史料依据】", "【学习提示】"]


def _source_text(source: dict[str, Any]) -> str:
    return " ".join(str(value or "") for value in source.values())


def _any_keyword_hit(text: str, keywords: list[str]) -> bool:
    return not keywords or any(keyword in text for keyword in keywords)


def llm_judge(character: str, question: str, response: str, facts: list[str]) -> dict[str, Any]:
    facts_text = "\n".join(facts[:3])
    prompt = (
        f"你是历史教学质量评审员。请对以下历史人物模拟回答打分（1-5分），输出JSON。\n"
        f"字段：factual_accuracy（事实准确性）、educational_value（教学价值）、"
        f"hallucination_risk（幻觉风险，1=低风险，5=高风险）、comment（一句话评语）\n\n"
        f"人物：{character}\n问题：{question}\n"
        f"参考史料：\n{facts_text}\n\n回答：\n{response[:800]}"
    )
    try:
        from structured_output import invoke_structured
        result = invoke_structured(
            llm_fast,
            [{"role": "user", "content": prompt}],
            fallback={"factual_accuracy": 0, "educational_value": 0, "hallucination_risk": 5, "comment": "评审失败"},
        )
        return result
    except Exception:
        return {"factual_accuracy": 0, "educational_value": 0, "hallucination_risk": 5, "comment": "评审失败"}


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    retriever = get_retriever("history")
    graph = build_character_graph(retriever)
    state = {
        "character": case["character"],
        "messages": [{"role": "user", "content": case["message"]}],
        "retrieved_facts": [],
        "retrieved_sources": [],
        "response_draft": "",
        "verified": False,
        "mode": case.get("mode") or detect_mode(case["message"]),
    }
    result = await graph.ainvoke(state)
    response = result.get("response_draft", "")
    sources = result.get("retrieved_sources", [])
    source_blob = "\n".join(_source_text(source) for source in sources)

    fact_card_parse_success = False
    try:
        card = generate_fact_card({**state, **result})
        fact_card_parse_success = bool(card.get("question_summary") or card.get("key_facts"))
    except Exception:
        fact_card_parse_success = False

    judge = llm_judge(
        case["character"], case["message"], response,
        result.get("retrieved_facts", []),
    )

    min_sources = int(case.get("min_sources", 1))
    return {
        "name": case["name"],
        "verified": result.get("verified") is True,
        "answer_structure_pass": all(section in response for section in REQUIRED_SECTIONS),
        "source_presence": len(sources) >= min_sources,
        "citation_keyword_hit": _any_keyword_hit(source_blob, case.get("expected_source_keywords") or []),
        "answer_keyword_hit": _any_keyword_hit(response, case.get("expected_response_keywords") or []),
        "fact_card_parse_success": fact_card_parse_success,
        "sources": len(sources),
        "judge_factual_accuracy": judge.get("factual_accuracy", 0),
        "judge_educational_value": judge.get("educational_value", 0),
        "judge_hallucination_risk": judge.get("hallucination_risk", 5),
        "judge_comment": judge.get("comment", ""),
    }


async def main() -> None:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    results = [await run_case(case) for case in cases]

    for result in results:
        passed = all(
            [
                result["verified"],
                result["answer_structure_pass"],
                result["source_presence"],
                result["citation_keyword_hit"],
                result["answer_keyword_hit"],
            ]
        )
        status = "OK" if passed else "FAIL"
        print(
            f"{status} {result['name']}: "
            f"verified={result['verified']} structure={result['answer_structure_pass']} "
            f"sources={result['sources']} citation_hit={result['citation_keyword_hit']} "
            f"answer_hit={result['answer_keyword_hit']} fact_card={result['fact_card_parse_success']} "
            f"judge_accuracy={result['judge_factual_accuracy']} "
            f"judge_hallucination={result['judge_hallucination_risk']} "
            f"judge_comment={result['judge_comment']}"
        )

    total = len(results)
    metrics = {
        "verified_pass_rate": sum(item["verified"] for item in results),
        "answer_structure_pass_rate": sum(item["answer_structure_pass"] for item in results),
        "source_presence_rate": sum(item["source_presence"] for item in results),
        "citation_keyword_hit_rate": sum(item["citation_keyword_hit"] for item in results),
        "answer_keyword_hit_rate": sum(item["answer_keyword_hit"] for item in results),
        "fact_card_parse_success_rate": sum(item["fact_card_parse_success"] for item in results),
        "avg_judge_factual_accuracy": round(sum(item["judge_factual_accuracy"] for item in results) / total, 2),
        "avg_judge_hallucination_risk": round(sum(item["judge_hallucination_risk"] for item in results) / total, 2),
    }
    print()
    for name, value in metrics.items():
        if isinstance(value, float):
            print(f"{name}={value}")
        else:
            print(f"{name}={value}/{total}")

    failures = [
        item["name"]
        for item in results
        if not (
            item["verified"]
            and item["answer_structure_pass"]
            and item["source_presence"]
            and item["citation_keyword_hit"]
            and item["answer_keyword_hit"]
        )
    ]
    if failures:
        raise SystemExit(f"failed cases: {', '.join(failures)}")


if __name__ == "__main__":
    asyncio.run(main())

