"""Contract eval: supported claims pass; partial retrieval cannot complete."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.answer_verifier import verify_answer_evidence


def _execution(case: dict, retrieval_status: str = "sufficient") -> dict:
    source_id = f"source-{case['id']}"
    source = {
        "source_id": source_id,
        "topic": case["entity"],
        "snippet": case["supporting_text"],
        "source": "历史问答契约评测",
        "source_tier": "L1_TEXTBOOK_DIRECT",
    }
    claim = {
        "claim_id": case["id"],
        "operation": "answer_from_sources",
        "text": case["claim"],
        "critical": False,
        "citations": [{"source_id": source_id, "quote": case["supporting_text"]}],
    }
    return {
        "tool_results": [{
            "tool_name": "search_history_knowledge",
            "ok": True,
            "data": {"sources": [source], "retrieval_status": retrieval_status},
        }],
        "generation_results": [{
            "operation": "answer_from_sources",
            "response": case["claim"],
            "evidence_claims": [claim],
        }],
    }


def main() -> None:
    cases = json.loads((ROOT / "eval" / "datasets" / "history_answer_grounding_cases.json").read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        verification = verify_answer_evidence(intents=["history_search"], execution=_execution(case))
        if verification.status == "verified" and verification.completion_allowed:
            passed += 1
    if passed != len(cases):
        raise SystemExit(f"history_answer_grounding_eval=FAIL {passed}/{len(cases)}")

    blocked = verify_answer_evidence(intents=["history_search"], execution=_execution(cases[0], "partial"))
    assert blocked.completion_allowed is False, blocked
    assert "evidence_retrieval_partial" in blocked.reason_codes, blocked
    print(f"history_answer_grounding_eval=PASS cases={passed} partial_gate=PASS")


if __name__ == "__main__":
    main()

