"""Validate all reviewed pilot assessments and practice/exit independence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_content import FORBIDDEN_PLACEHOLDERS, build_learning_objective, prepare_content


def main() -> None:
    cases = json.loads((ROOT / "eval/datasets/autotutor_assessment_cases.json").read_text(encoding="utf-8"))
    passed = 0
    answer_positions: set[str] = set()
    for case in cases:
        objective = build_learning_objective(case["objective"], grade="八年级上册")
        practice = prepare_content(objective, {}, kind="practice")
        exit_ticket = prepare_content(
            objective,
            {},
            kind="exit_ticket",
            excluded_assessment_id=practice.assessment.assessment_id if practice.assessment else None,
            excluded_assessment=practice.assessment,
        )
        items = [practice.assessment, exit_ticket.assessment]
        forbidden = [marker for item in items if item for option in item.options for marker in FORBIDDEN_PLACEHOLDERS if marker in option.text]
        correct = [next(option.option_id for option in item.options if option.is_correct) for item in items if item]
        answer_positions.update(correct)
        ok = bool(
            practice.validation.status == "verified"
            and exit_ticket.validation.status == "verified"
            and practice.assessment
            and exit_ticket.assessment
            and practice.assessment.assessment_id == case["practice"]
            and exit_ticket.assessment.assessment_id == case["exit_ticket"]
            and practice.assessment.assessment_id != exit_ticket.assessment.assessment_id
            and practice.assessment.stem != exit_ticket.assessment.stem
            and not forbidden
        )
        print(("OK" if ok else "FAIL"), case["objective"], correct)
        passed += int(ok)
    distribution_ok = len(answer_positions) >= 3
    print(("OK" if distribution_ok else "FAIL"), "answer_position_distribution", sorted(answer_positions))
    passed += int(distribution_ok)
    total = len(cases) + 1
    print(f"autotutor_assessment_validity={passed}/{total}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
