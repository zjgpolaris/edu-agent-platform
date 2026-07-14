"""Offline smoke coverage for the debate supervisor multi-agent trajectory."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import agents.debate_supervisor as debate
from trace_store import get_trace_store, trace_context


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class FakeModel:
    model = "fake-debate-model"

    def invoke(self, prompt: str) -> FakeResponse:
        if "事实核查员" in prompt:
            return FakeResponse("[史料1] 该论据得到史料支持。")
        if "获胜方" in prompt:
            return FakeResponse("正方论据更完整，正方获胜。")
        if "关键历史知识点" in prompt:
            return FakeResponse("知识点一、知识点二、知识点三；建议复习教材。")
        if "反方立场" in prompt:
            return FakeResponse("反方论点。")
        return FakeResponse("正方论点。")


class FailingModel:
    model = "fake-failing-model"

    def invoke(self, _prompt: str) -> FakeResponse:
        raise RuntimeError("expected role failure")


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def complete_trajectory_has_one_event_per_stage() -> None:
    trace_id = "debate_multi_agent_complete"
    original_fast = debate.llm
    original_quality = debate.llm_judge
    original_rounds = debate.MAX_ROUNDS
    original_search = debate._search_history_sources
    debate.llm = FakeModel()
    debate.llm_judge = FakeModel()
    debate.MAX_ROUNDS = 1
    debate._search_history_sources = lambda _topic: (
        [{
            "citation_label": "[史料1]",
            "topic": "测试史料",
            "source": "offline-smoke",
            "snippet": "测试史料内容",
            "score": 0.9,
        }],
        "[史料1] 测试史料内容",
    )

    async def collect() -> list[dict]:
        return [item async for item in debate.stream_debate("测试辩题", trace_id=trace_id)]

    try:
        events = asyncio.run(collect())
    finally:
        debate.llm = original_fast
        debate.llm_judge = original_quality
        debate.MAX_ROUNDS = original_rounds
        debate._search_history_sources = original_search

    event_names = [item["event"] for item in events]
    assert event_names == ["trace", "round", "round", "fact_check", "verdict", "coach_summary", "done"], event_names
    assert events[3]["data"]["sources"][0]["citation_label"] == "[史料1]"
    assert events[-1]["data"] == {"trace_id": trace_id, "round_count": 1, "source_count": 1}

    trace_events = get_trace_store().get_trace(trace_id)
    assert [item["agent_name"] for item in trace_events] == [
        "pro_debater",
        "con_debater",
        "fact_checker",
        "judge",
        "learning_coach",
        "debate_supervisor",
    ]
    assert all(item["status"] == "success" for item in trace_events)


def role_failure_is_traced() -> None:
    trace_id = "debate_multi_agent_failure"

    async def invoke() -> None:
        with trace_context(trace_id):
            try:
                await debate._invoke_role("fact_checker", "fact_check", FailingModel(), "prompt")
            except RuntimeError:
                return
        raise AssertionError("expected role failure was not raised")

    asyncio.run(invoke())
    trace_events = get_trace_store().get_trace(trace_id)
    assert len(trace_events) == 1
    assert trace_events[0]["agent_name"] == "fact_checker"
    assert trace_events[0]["status"] == "error"
    assert trace_events[0]["metadata"]["error_type"] == "RuntimeError"


def main() -> None:
    cases = [
        ("complete_trajectory_has_one_event_per_stage", complete_trajectory_has_one_event_per_stage),
        ("role_failure_is_traced", role_failure_is_traced),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"debate_multi_agent={passed}/{len(cases)}")
    print(f"multi_agent_trace_coverage={round(passed / len(cases), 4)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
