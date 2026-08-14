"""Generate deterministic seed datasets; teacher review status remains explicit."""
from __future__ import annotations

import json
from pathlib import Path


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
QUERY_TEMPLATES = (
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


def main() -> None:
    query_cases = []
    retrieval_cases = []
    for entity, entity_type in ENTITIES:
        for index, (template, aspect) in enumerate(QUERY_TEMPLATES, start=1):
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
            retrieval_cases.append({
                "id": case_id,
                "query": query,
                "expected_entity": entity,
                "expected_aspect": aspect,
                "relevance_scale": {"0": "unrelated", "1": "entity_only", "2": "answer_bearing"},
                "review_status": "seed_pending_teacher_review",
            })

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

    outputs = {
        "history_query_cases.json": query_cases,
        "history_retrieval_cases.json": retrieval_cases,
        "history_no_answer_cases.json": no_answer_cases,
        "history_answer_grounding_cases.json": grounding_cases,
    }
    for name, rows in outputs.items():
        target = DATASET_DIR / name
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}={len(rows)}")


if __name__ == "__main__":
    main()
