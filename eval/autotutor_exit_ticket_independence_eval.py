"""Focused independence check for each pilot practice/exit pair."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.autotutor_content import build_learning_objective, load_curated_content, prepare_content, validate_content


def main() -> None:
    passed = 0
    entries = load_curated_content()
    for entry in entries:
        objective = build_learning_objective(f"{entry.entity}{'历史意义' if entry.aspect == 'significance' else {'cause': '失败原因', 'purpose': '目的', 'impact': '影响'}.get(entry.aspect, '')}")
        practice = prepare_content(objective, {}, kind="practice")
        exit_ticket = prepare_content(
            objective,
            {},
            kind="exit_ticket",
            excluded_assessment_id=practice.assessment.assessment_id,
            excluded_assessment=practice.assessment,
        )
        ok = bool(
            exit_ticket.validation.status == "verified"
            and practice.assessment.assessment_id != exit_ticket.assessment.assessment_id
            and practice.assessment.stem != exit_ticket.assessment.stem
            and exit_ticket.assessment.cognitive_action in {"apply", "compare"}
        )
        print(("OK" if ok else "FAIL"), entry.entity, entry.aspect)
        passed += int(ok)
    objective = build_learning_objective("戊戌变法失败原因")
    practice = prepare_content(objective, {}, kind="practice")
    renamed_duplicate = practice.assessment.model_copy(update={
        "assessment_id": "renamed-duplicate-exit",
        "kind": "exit_ticket",
    })
    duplicate_validation = validate_content(
        objective,
        practice.evidence,
        practice.teaching,
        renamed_duplicate,
        excluded_assessment=practice.assessment,
    )
    duplicate_blocked = bool(
        duplicate_validation.status == "blocked"
        and "assessment_not_independent" in duplicate_validation.reason_codes
    )
    print(("OK" if duplicate_blocked else "FAIL"), "renamed_duplicate_blocked")
    passed += int(duplicate_blocked)
    total = len(entries) + 1
    print(f"autotutor_exit_ticket_independence={passed}/{total}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
