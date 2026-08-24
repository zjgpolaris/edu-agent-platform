"""Deterministic objective/evidence/content alignment gate for AutoTutor v1.35."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_content import build_learning_objective, prepare_content


def main() -> None:
    cases = json.loads((ROOT / "eval/datasets/autotutor_content_alignment_cases.json").read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        objective = build_learning_objective(case["input"], grade="八年级上册")
        prepared = prepare_content(objective, {}, kind="practice")
        actual = prepared.validation.status
        ok = objective.entity == case["entity"] and objective.aspect == case["aspect"] and actual == case["expected"]
        print(("OK" if ok else "FAIL"), case["id"], objective.entity, objective.aspect, actual)
        passed += int(ok)
    print(f"autotutor_objective_alignment={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
