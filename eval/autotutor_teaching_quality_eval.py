"""Deterministic AutoTutor teaching-content quality evaluation.

This suite complements trajectory tests: it checks that offline fallback teaching
retains source facts, rejects retrieved prompt injection, is structurally useful,
and actually changes after a re-teach decision.
"""
from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents import auto_tutor as at

DATASET = ROOT / "eval" / "datasets" / "autotutor_teaching_cases.json"


def _source(snippet: str) -> dict:
    return {"topic": "教材史料", "source": "offline_eval", "snippet": snippet}


def _generate_offline(step: at.LessonStep, sources: list[dict]) -> dict:
    original = at.invoke_structured
    at.invoke_structured = lambda *args, **kwargs: None
    try:
        return at._generate_teaching(step, sources)
    finally:
        at.invoke_structured = original


def evaluate_case(case: dict) -> tuple[bool, str, dict]:
    sources = [_source(case["source"])]
    if case.get("safe_source"):
        sources.append(_source(case["safe_source"]))
    step = at.LessonStep(
        knowledge_point=case["knowledge_point"],
        difficulty=case["difficulty"],
        strategy="先解释核心史实，再用因果关系帮助理解。",
    )
    teaching = _generate_offline(step, sources)
    explanation = str(teaching.get("explanation") or "")
    detail = {"case": case["id"], "teaching": teaching}
    if not 20 <= len(explanation) <= 500:
        return False, "explanation length out of bounds", detail
    if not 2 <= len(teaching.get("key_points") or []) <= 3:
        return False, "expected 2-3 key points", detail
    if not str(teaching.get("example") or "").strip():
        return False, "teaching example missing", detail
    missing = [fact for fact in case.get("required_facts", []) if fact not in explanation]
    if missing:
        return False, f"source facts missing: {missing}", detail
    leaked = [term for term in case.get("forbidden_terms", []) if term.lower() in explanation.lower()]
    if leaked:
        return False, f"untrusted instructions leaked: {leaked}", detail
    return True, "ok", detail


def evaluate_reteach_change() -> tuple[bool, str, dict]:
    sources = [_source("洋务运动以自强、求富为口号，推动近代工业发展。")]
    first = _generate_offline(
        at.LessonStep(knowledge_point="洋务运动", difficulty="medium", strategy="按时间顺序讲解。"),
        sources,
    )
    second = _generate_offline(
        at.LessonStep(
            knowledge_point="洋务运动",
            difficulty="easy",
            strategy="换成创办工厂的生活化例子重新解释。",
            attempts=1,
            replanned=True,
        ),
        sources,
    )
    before = str(first.get("explanation") or "")
    after = str(second.get("explanation") or "")
    similarity = round(SequenceMatcher(None, before, after).ratio(), 4)
    detail = {"before": before, "after": after, "similarity": similarity}
    if before == after or similarity >= 0.95:
        return False, "reteach did not materially change explanation", detail
    return True, "ok", detail


def main() -> None:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    results: list[tuple[str, bool, str, dict]] = []
    for case in cases:
        ok, reason, detail = evaluate_case(case)
        results.append((case["id"], ok, reason, detail))
    ok, reason, detail = evaluate_reteach_change()
    results.append(("reteach_semantic_change", ok, reason, detail))

    for name, passed, reason, detail in results:
        if passed:
            print(f"OK {name}")
        else:
            print(f"FAIL {name}: {reason}")
            print("FAILED_CASE_DETAIL=" + json.dumps({"name": name, "reason": reason, **detail}, ensure_ascii=False))

    passed = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    grounded = sum(1 for name, ok, _, _ in results if ok and name != "reteach_semantic_change")
    print(f"autotutor_teaching_quality={passed}/{total}")
    print(f"teaching_groundedness_rate={round(grounded / len(cases), 4)}")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
