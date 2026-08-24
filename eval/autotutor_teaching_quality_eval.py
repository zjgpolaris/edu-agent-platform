"""Deterministic AutoTutor teaching-content quality evaluation.

This suite complements trajectory tests: it checks that offline fallback teaching
retains source facts, rejects retrieved prompt injection, is structurally useful,
and actually changes after a re-teach decision.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.autotutor_content import (
    FORBIDDEN_PLACEHOLDERS,
    answer_feedback,
    build_learning_objective,
    prepare_content,
)

DATASET = ROOT / "eval" / "datasets" / "autotutor_teaching_cases.json"


def evaluate_case(case: dict) -> tuple[bool, str, dict]:
    objective = build_learning_objective(case["knowledge_point"], grade="八年级上册")
    prepared = prepare_content(objective, {}, kind="practice")
    teaching = prepared.teaching
    assessment = prepared.assessment
    explanation = teaching.explanation if teaching else ""
    detail = {"case": case["id"], "teaching": teaching.model_dump(mode="json") if teaching else None}
    if prepared.validation.status != "verified" or teaching is None or assessment is None:
        return False, "content gate blocked a pilot case", detail
    if not 20 <= len(explanation) <= 500:
        return False, "explanation length out of bounds", detail
    if not 2 <= len(teaching.key_points) <= 3:
        return False, "expected 2-3 key points", detail
    if not str(teaching.example or "").strip():
        return False, "teaching example missing", detail
    missing = [fact for fact in case.get("required_facts", []) if fact not in explanation]
    if missing:
        return False, f"source facts missing: {missing}", detail
    leaked = [term for term in case.get("forbidden_terms", []) if term.lower() in explanation.lower()]
    if leaked:
        return False, f"untrusted instructions leaked: {leaked}", detail
    if any(marker in option.text for option in assessment.options for marker in FORBIDDEN_PLACEHOLDERS):
        return False, "placeholder assessment option found", detail
    return True, "ok", detail


def evaluate_reteach_change() -> tuple[bool, str, dict]:
    objective = build_learning_objective("戊戌变法失败原因")
    prepared = prepare_content(objective, {}, kind="practice")
    wrong = next(option for option in prepared.assessment.options if option.misconception_code == "cause_impact_confusion")
    feedback = answer_feedback(prepared.assessment, wrong.option_id)
    detail = {"selected": wrong.text, "feedback": feedback}
    if feedback["is_correct"] or feedback["misconception_code"] != "cause_impact_confusion":
        return False, "wrong option was not tied to its misconception", detail
    if "影响" not in feedback["message"] or not feedback["correction"]:
        return False, "reteach feedback is not specific enough", detail
    return True, "ok", detail


def evaluate_v135_content_gate() -> tuple[bool, str, dict]:
    objective = build_learning_objective("戊戌变法失败原因", grade="八年级上册")
    prepared = prepare_content(objective, {}, kind="practice")
    teaching = prepared.teaching
    assessment = prepared.assessment
    detail = {
        "objective": objective.model_dump(mode="json"),
        "validation": prepared.validation.model_dump(mode="json"),
        "assessment_id": assessment.assessment_id if assessment else None,
    }
    if prepared.validation.status != "verified" or teaching is None or assessment is None:
        return False, "pilot content did not pass the mandatory gate", detail
    if not all(claim.objective_aspect == "cause" and claim.source_ids for claim in teaching.claims):
        return False, "teaching claim source/aspect binding invalid", detail
    if not any(term in teaching.explanation for term in ("原因", "阻挠", "力量弱小", "依赖")):
        return False, "cause objective explanation does not explain a cause", detail
    if any(marker in option.text for marker in FORBIDDEN_PLACEHOLDERS for option in assessment.options):
        return False, "forbidden placeholder option served", detail
    return True, "ok", detail


def main() -> None:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    results: list[tuple[str, bool, str, dict]] = []
    for case in cases:
        ok, reason, detail = evaluate_case(case)
        results.append((case["id"], ok, reason, detail))
    ok, reason, detail = evaluate_reteach_change()
    results.append(("reteach_semantic_change", ok, reason, detail))
    ok, reason, detail = evaluate_v135_content_gate()
    results.append(("v135_objective_evidence_assessment_gate", ok, reason, detail))

    for name, passed, reason, detail in results:
        if passed:
            print(f"OK {name}")
        else:
            print(f"FAIL {name}: {reason}")
            print("FAILED_CASE_DETAIL=" + json.dumps({"name": name, "reason": reason, **detail}, ensure_ascii=False))

    passed = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    supplemental = {"reteach_semantic_change", "v135_objective_evidence_assessment_gate"}
    grounded = sum(1 for name, ok, _, _ in results if ok and name not in supplemental)
    print(f"autotutor_teaching_quality={passed}/{total}")
    print(f"teaching_groundedness_rate={round(grounded / len(cases), 4)}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
