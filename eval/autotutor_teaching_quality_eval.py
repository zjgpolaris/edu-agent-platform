"""Deterministic AutoTutor teaching-content quality evaluation.

Checks curated content contracts and actual polluted input isolation. This is
not an LLM injection evaluation; Graph re-teaching has its own trajectory suite.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

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
    from agents import autotutor_content as content
    inputs, expected = case["input"], case["expected"]
    retrieval = inputs["retrieval_data"]
    # Spy at the actual boundary inside prepare_content, not the caller alone.
    with patch.object(content, "evidence_decision", wraps=content.evidence_decision) as boundary:
        prepared = prepare_content(objective, retrieval, kind="practice",
                                   target_difficulty=inputs["target_difficulty"])
    detail = {"case_id": case["id"], "boundary": "content_gate",
              "assertion_scope": case["assertion_scope"], "expected": expected["status"],
              "actual": prepared.validation.status}
    if boundary.call_count != 1 or boundary.call_args.args[1] != retrieval:
        return False, "retrieval input did not reach evidence boundary", detail
    if case["scenario"] == "polluted_source" and "V151_INJECTION_SENTINEL" not in json.dumps(boundary.call_args.args[1]):
        return False, "polluted input was not exercised", detail
    if expected["status"] == "blocked":
        ok = prepared.validation.status == "blocked" and prepared.blocked_reason == expected["blocked_reason"] and prepared.assessment is None
        if case["scenario"] == "missing_content":
            ok = ok and prepared.teaching is None
        return ok, "ok" if ok else "unsupported content was served", detail
    teaching = prepared.teaching
    assessment = prepared.assessment
    explanation = teaching.explanation if teaching else ""
    if prepared.validation.status != "verified" or teaching is None or assessment is None:
        return False, "content gate blocked a pilot case", detail
    if objective.aspect != case["objective_aspect"]:
        return False, "objective aspect mismatch", detail
    if assessment.difficulty != inputs["target_difficulty"]:
        return False, "selected difficulty differs from explicit target", {**detail, "boundary": "assessment_selection", "expected": inputs["target_difficulty"], "actual": assessment.difficulty}
    if not teaching.claims or not all(set(claim.source_ids) & set(prepared.evidence.answer_bearing_source_ids) for claim in teaching.claims):
        return False, "teaching claims lack evidence binding", detail
    if not 20 <= len(explanation) <= 500:
        return False, "explanation length out of bounds", detail
    if not 2 <= len(teaching.key_points) <= 3:
        return False, "expected 2-3 key points", detail
    if not str(teaching.example or "").strip():
        return False, "teaching example missing", detail
    missing = [fact for fact in expected.get("required_facts", []) if fact not in explanation]
    if missing:
        return False, f"source facts missing: {missing}", detail
    public_content = json.dumps({"teaching": teaching.model_dump(mode="json"), "stem": assessment.stem, "options": [o.text for o in assessment.options]}, ensure_ascii=False)
    leaked = [term for term in expected.get("forbidden_terms", []) if term.lower() in public_content.lower()]
    if leaked:
        return False, f"untrusted instructions leaked: {leaked}", detail
    if any(marker in option.text for option in assessment.options for marker in FORBIDDEN_PLACEHOLDERS):
        return False, "placeholder assessment option found", detail
    return True, "ok", detail


def evaluate_misconception_feedback() -> tuple[bool, str, dict]:
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
    ok, reason, detail = evaluate_misconception_feedback()
    results.append(("misconception_feedback_specificity", ok, reason, detail))
    ok, reason, detail = evaluate_v135_content_gate()
    results.append(("v135_objective_evidence_assessment_gate", ok, reason, detail))

    for name, passed, reason, detail in results:
        if passed:
            print(f"OK {name}")
        else:
            print(f"FAIL {name}: {reason}")
            print("FAILED_CASE_DETAIL=" + json.dumps({"name": name, "case_id": name, "boundary": "misconception_feedback" if name == "misconception_feedback_specificity" else "content_gate", "expected": "contract satisfied", "actual": reason, "reason": reason, **detail}, ensure_ascii=False))

    passed = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    content_ids = {c["id"] for c in cases if c["expected"]["status"] == "verified"}
    grounded = sum(1 for name, ok, _, _ in results if ok and name in content_ids)
    print(f"autotutor_teaching_quality={passed}/{total}")
    print(f"teaching_groundedness_rate={round(grounded / len(content_ids), 4)}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
