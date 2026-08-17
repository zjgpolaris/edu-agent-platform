"""Generate deterministic history eval datasets without erasing valid reviews."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATASET_DIR = Path(__file__).resolve().parent / "datasets"
ENTITIES = (
    ("长平之战", "event"),
    ("赤壁之战", "event"),
    ("鸦片战争", "event"),
    ("洋务运动", "event"),
    ("商鞅变法", "event"),
    ("苏轼", "person"),
    ("辛弃疾", "person"),
    ("贞观之治", "event"),
    ("张骞出使西域", "event"),
    ("虎门销烟", "event"),
)
EVENT_QUERY_TEMPLATES = (
    ("{entity}是什么", "definition"),
    ("{entity}发生的背景是什么", "background"),
    ("{entity}的主要原因是什么", "cause"),
    ("简述{entity}的经过", "process"),
    ("{entity}的结果是什么", "result"),
    ("{entity}有什么影响", "impact"),
    ("{entity}有什么历史意义", "significance"),
    ("如何评价{entity}", "evaluation"),
    ("介绍一下{entity}", "definition"),
    ("为什么会发生{entity}", "cause"),
    ("{entity}带来了什么变化", "impact"),
    ("{entity}为什么重要", "significance"),
)

# Keep the case indexes that were already valid stable. Only the six event-only
# prompts are replaced so their old teacher-rejected fingerprints cannot leak
# into the corrected person cases.
PERSON_QUERY_TEMPLATES = (
    ("{entity}是谁", "definition"),
    ("{entity}生活在什么时代", "background"),
    ("{entity}有哪些主要成就", "contribution"),
    ("{entity}的创作风格有什么特点", "feature"),
    ("{entity}在文学史上的地位如何", "evaluation"),
    ("{entity}有什么影响", "impact"),
    ("{entity}有什么历史意义", "significance"),
    ("如何评价{entity}", "evaluation"),
    ("介绍一下{entity}", "definition"),
    ("{entity}对宋词发展有什么贡献", "contribution"),
    ("{entity}带来了什么变化", "impact"),
    ("{entity}为什么重要", "significance"),
)

RETRIEVAL_FINGERPRINT_FIELDS = (
    "id",
    "query",
    "expected_entity",
    "expected_aspect",
    "relevance_scale",
)


def _query_templates(entity_type: str) -> tuple[tuple[str, str], ...]:
    return PERSON_QUERY_TEMPLATES if entity_type == "person" else EVENT_QUERY_TEMPLATES


def _preserve_matching_review(seed: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    if not existing:
        return seed
    if all(existing.get(field) == seed.get(field) for field in RETRIEVAL_FINGERPRINT_FIELDS):
        return existing
    return seed


def build_datasets(existing_retrieval_cases: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    existing_by_id = {
        str(case.get("id")): case
        for case in (existing_retrieval_cases or [])
        if isinstance(case, dict) and case.get("id")
    }

    query_cases = []
    retrieval_cases = []
    for entity, entity_type in ENTITIES:
        for index, (template, aspect) in enumerate(_query_templates(entity_type), start=1):
            query = template.format(entity=entity)
            case_id = f"{entity_type}-{entity}-{index}"
            query_cases.append({
                "id": case_id,
                "query": query,
                "expected_entity": entity,
                "expected_entity_type": entity_type,
                "expected_aspect": aspect,
                "review_status": "seed_pending_teacher_review",
            })
            retrieval_seed = {
                "id": case_id,
                "query": query,
                "expected_entity": entity,
                "expected_aspect": aspect,
                "relevance_scale": {"0": "unrelated", "1": "entity_only", "2": "answer_bearing"},
                "review_status": "seed_pending_teacher_review",
            }
            retrieval_cases.append(_preserve_matching_review(retrieval_seed, existing_by_id.get(case_id)))

    no_answer_cases = []
    suffixes = ("精确伤亡名单", "所有参战者姓名", "教材未记载的私人谈话", "逐日行军路线")
    for entity, _ in ENTITIES:
        for index, suffix in enumerate(suffixes, start=1):
            no_answer_cases.append({
                "id": f"no-answer-{entity}-{index}",
                "query": f"请根据教材说明{entity}的{suffix}",
                "expected_entity": entity,
                "expected_retrieval_status": "none_or_partial",
                "review_status": "seed_pending_teacher_review",
            })

    grounding_cases = []
    grounding_aspects = ("背景", "原因", "经过", "结果", "影响", "意义")
    for entity, _ in ENTITIES:
        for index, aspect in enumerate(grounding_aspects, start=1):
            claim = f"{entity}的{aspect}可由当前教材材料直接确认。"
            grounding_cases.append({
                "id": f"grounding-{entity}-{index}",
                "entity": entity,
                "aspect": aspect,
                "claim": claim,
                "supporting_text": claim,
                "review_status": "contract_seed_pending_teacher_review",
            })

    return {
        "history_query_cases.json": query_cases,
        "history_retrieval_cases.json": retrieval_cases,
        "history_no_answer_cases.json": no_answer_cases,
        "history_answer_grounding_cases.json": grounding_cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild history eval seeds while preserving unchanged human reviews.")
    parser.add_argument("--reset-reviews", action="store_true", help="Discard every existing retrieval review.")
    args = parser.parse_args()
    retrieval_path = DATASET_DIR / "history_retrieval_cases.json"
    existing_retrieval_cases: list[dict[str, Any]] = []
    if retrieval_path.exists() and not args.reset_reviews:
        payload = json.loads(retrieval_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            existing_retrieval_cases = [row for row in payload if isinstance(row, dict)]

    outputs = build_datasets(existing_retrieval_cases)
    for name, rows in outputs.items():
        target = DATASET_DIR / name
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}={len(rows)}")


if __name__ == "__main__":
    main()
