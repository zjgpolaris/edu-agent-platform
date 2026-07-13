from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-agent-ops-smoke.sqlite3")

from agent_ops import build_agent_ops_summary
from trace_store import create_trace_id, emit_trace_event, trace_context


def main() -> None:
    trace_id = create_trace_id()
    with trace_context(trace_id):
        emit_trace_event(
            agent_name="agent_ops_smoke",
            step_name="rag_retrieval",
            event_type="retrieval",
            status="success",
            latency_ms=88,
            metadata={
                "rag_inspector": {
                    "retrieval_strategy": "textbook_hybrid",
                    "diagnosis_code": "generation_uncited_sources",
                    "failure_stage": "generation",
                },
            },
        )
        emit_trace_event(
            agent_name="agent_ops_smoke",
            step_name="response_generation",
            event_type="llm",
            status="success",
            latency_ms=320,
            metadata={
                "configured_model": "qwen-plus",
                "response_chars": 120,
                "input_tokens_estimated": 80,
                "output_tokens_estimated": 90,
                "cost_usd_estimated": 0.000352,
                "fallback_used": True,
            },
        )
        emit_trace_event(
            agent_name="agent_ops_smoke",
            step_name="tool_result",
            event_type="tool_result",
            status="success",
            latency_ms=42,
            metadata={"tool_name": "search_history_knowledge"},
        )

    summary = build_agent_ops_summary(limit=10)
    production = summary.get("production") or {}
    latency = production.get("latency") or {}
    llm = production.get("llm") or {}
    rag = production.get("rag") or {}
    cost = production.get("cost") or {}

    assert latency.get("p95_ms") is not None
    assert latency.get("llm_p95_ms") == 320
    assert llm.get("calls", 0) >= 1
    assert llm.get("fallback_count", 0) >= 1
    assert (llm.get("models") or {}).get("qwen-plus", 0) >= 1
    assert (rag.get("diagnosis") or {}).get("generation_uncited_sources", 0) >= 1
    assert (rag.get("failure_stage") or {}).get("generation", 0) >= 1
    assert cost.get("total_usd_estimated", 0) >= 0.000352
    print("agent_ops_smoke=PASS")


if __name__ == "__main__":
    main()
