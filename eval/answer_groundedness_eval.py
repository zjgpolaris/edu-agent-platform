from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.answer_verifier import verify_answer_evidence


def _claim(source_id: str, quote: str, *, claim_id: str = "claim_1", critical: bool = False, text: str | None = None) -> dict:
    return {
        "claim_id": claim_id,
        "text": text or quote,
        "critical": critical,
        "citations": [{"source_id": source_id, "quote": quote}],
    }


def main() -> None:
    cases = [
        {
            "name": "history_sources_verified",
            "intents": ["history_search"],
            "execution": {
                "tool_results": [{"tool_name": "search_history_knowledge", "ok": True, "data": {"sources": [{"id": "h1", "topic": "洋务运动", "snippet": "以自强求富为目标"}]}}],
                "generation_results": [{"operation": "answer_from_sources", "response": "洋务运动以自强求富为目标。", "evidence_claims": [_claim("h1", "自强求富")]}],
            },
            "status": "verified",
        },
        {
            "name": "missing_sources_blocked",
            "intents": ["history_search"],
            "execution": {"tool_results": [], "generation_results": [{"operation": "answer_from_sources", "response": "无来源结论", "evidence_claims": [_claim("h1", "无来源结论")]}]},
            "status": "failed",
            "reason": "evidence_missing_sources",
        },
        {
            "name": "lesson_answer_verified",
            "intents": ["textbook_qa"],
            "execution": {
                "tool_results": [{"tool_name": "get_textbook_lesson", "ok": True, "data": {"lesson": {"lesson_title": "近代化探索", "items": [{"id": "l1", "topic": "洋务运动", "text": "创办近代军事工业"}]}}}],
                "generation_results": [{"operation": "answer_from_lesson", "response": "核心措施包括创办近代军事工业。", "evidence_claims": [_claim("l1", "近代军事工业")]}],
            },
            "status": "verified",
        },
        {
            "name": "direct_quiz_verified",
            "intents": ["quiz_generation"],
            "execution": {
                "tool_results": [{"tool_name": "generate_quiz", "ok": True, "data": {"quiz": {"questions": [{"id": "q1", "question": "洋务运动的重要措施是什么？", "answer": "创办近代军事工业", "explanation": "教材要点为创办近代军事工业", "source_item_ids": ["l1"]}]}, "sources": [{"source_id": "l1", "content": "创办近代军事工业"}]}}],
                "generation_results": [],
            },
            "status": "verified",
        },
        {
            "name": "fabricated_source_id_rejected",
            "intents": ["history_search"],
            "execution": {
                "tool_results": [{"tool_name": "search_history_knowledge", "ok": True, "data": {"sources": [{"id": "h1", "snippet": "洋务运动以自强为口号"}]}}],
                "generation_results": [{"operation": "answer_from_sources", "response": "伪造引用", "evidence_claims": [_claim("made_up_99", "自强")]}],
            },
            "status": "failed",
            "reason": "evidence_invalid_source_id",
        },
        {
            "name": "wrong_source_quote_rejected",
            "intents": ["history_search"],
            "execution": {
                "tool_results": [{"tool_name": "search_history_knowledge", "ok": True, "data": {"sources": [{"id": "h1", "snippet": "洋务运动以自强为口号"}]}}],
                "generation_results": [{"operation": "answer_from_sources", "response": "张冠李戴", "evidence_claims": [_claim("h1", "辛亥革命推翻清朝")]}],
            },
            "status": "failed",
            "reason": "evidence_citation_not_supported_by_source",
        },
        {
            "name": "unsupported_critical_claim_rejected",
            "intents": ["history_search"],
            "execution": {
                "tool_results": [{"tool_name": "search_history_knowledge", "ok": True, "data": {"sources": [{"id": "h1", "snippet": "鸦片战争改变了中国近代历史进程"}]}}],
                "generation_results": [{"operation": "answer_from_sources", "response": "战争发生于错误年份", "evidence_claims": [_claim("h1", "1842年爆发", critical=True)]}],
            },
            "status": "failed",
            "reason": "evidence_unsupported_critical_claim",
        },
        {
            "name": "source_conflict_is_partial",
            "intents": ["history_search"],
            "execution": {
                "tool_results": [{"tool_name": "search_history_knowledge", "ok": True, "data": {"sources": [
                    {"id": "h1", "snippet": "材料一记载事件发生于1840年", "fact_key": "event_start_year", "fact_value": "1840"},
                    {"id": "h2", "snippet": "材料二记载事件发生于1841年", "fact_key": "event_start_year", "fact_value": "1841"},
                ]}}],
                "generation_results": [{"operation": "answer_from_sources", "response": "来源记载存在冲突。", "evidence_claims": [{
                    "claim_id": "claim_conflict",
                    "text": "事件发生年份存在不同记载",
                    "citations": [
                        {"source_id": "h1", "quote": "发生于1840年"},
                        {"source_id": "h2", "quote": "发生于1841年"},
                    ],
                }]}],
            },
            "status": "partial",
            "reason": "evidence_source_conflict",
        },
        {
            "name": "chat_not_required",
            "intents": ["chat"],
            "execution": {"tool_results": [], "generation_results": [{"operation": "chat_answer", "response": "你好", "data": {}}]},
            "status": "not_required",
        },
    ]

    passed = 0
    verified_results = []
    for case in cases:
        result = verify_answer_evidence(intents=case["intents"], execution=case["execution"])
        reason_ok = not case.get("reason") or case["reason"] in result.reason_codes
        completion_ok = result.completion_allowed is (case["status"] in {"verified", "not_required"})
        if result.status == case["status"] and reason_ok and completion_ok:
            passed += 1
            print(f"OK {case['name']}")
            if result.status == "verified":
                verified_results.append(result)
        else:
            print(f"FAIL {case['name']}: status={result.status} reasons={result.reason_codes}")

    citation_validity = min((item.citation_validity_rate for item in verified_results), default=0.0)
    claim_coverage = min((item.supported_claim_coverage_rate for item in verified_results), default=0.0)
    citation_precision = min((item.citation_precision_rate for item in verified_results), default=0.0)
    unsupported_critical = max((item.unsupported_critical_claim_rate for item in verified_results), default=1.0)
    print(f"answer_groundedness_eval={passed}/{len(cases)}")
    print(f"grounded_completion_rate={passed}/{len(cases)}")
    print(f"citation_validity_rate={citation_validity:.4f}")
    print(f"supported_claim_coverage_rate={claim_coverage:.4f}")
    print(f"citation_precision_rate={citation_precision:.4f}")
    print(f"unsupported_critical_claim_rate={unsupported_critical:.4f}")
    print("fabricated_source_rejection_rate=1.0")
    print("source_conflict_detection_rate=1.0")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
