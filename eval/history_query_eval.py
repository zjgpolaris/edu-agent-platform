"""Deterministic evaluation for HistoryQuery entity/aspect contracts."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from rag.history_query import parse_history_query


def main() -> None:
    path = ROOT / "eval" / "datasets" / "history_query_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    entity_hits = 0
    type_hits = 0
    aspect_hits = 0
    failures = []
    for case in cases:
        parsed = parse_history_query(case["query"])
        entity_ok = parsed.entity == case["expected_entity"]
        type_ok = parsed.entity_type == case["expected_entity_type"]
        aspect_ok = parsed.aspect == case["expected_aspect"]
        entity_hits += entity_ok
        type_hits += type_ok
        aspect_hits += aspect_ok
        if not (entity_ok and type_ok and aspect_ok):
            failures.append({
                "id": case["id"],
                "actual": {"entity": parsed.entity, "entity_type": parsed.entity_type, "aspect": parsed.aspect},
                "expected": {key: case[key] for key in ("expected_entity", "expected_entity_type", "expected_aspect")},
            })

    total = len(cases)
    print(f"history_query_entity_accuracy={entity_hits}/{total}")
    print(f"history_query_entity_type_accuracy={type_hits}/{total}")
    print(f"history_query_aspect_accuracy={aspect_hits}/{total}")
    if failures:
        raise SystemExit("history_query_eval=FAIL " + json.dumps(failures[:8], ensure_ascii=False))
    print(f"history_query_eval=PASS cases={total}")


if __name__ == "__main__":
    main()

