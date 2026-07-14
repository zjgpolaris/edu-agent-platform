"""Trajectory eval: measure tool selection accuracy for the learning assistant agent."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")
if not os.environ.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
    os.environ["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.learning_assistant import stream_learning_assistant_events

# Cases: (name, message, grade, expected_tool, expected_intent)
TRAJECTORY_CASES = [
    {
        "name": "history_search_selects_search_tool",
        "message": "鸦片战争的导火索是什么？",
        "grade": "八年级上册",
        "expected_tool": "search_history_knowledge",
        "expected_intent": "history_search",
        "expected_input": {"query": "鸦片战争的导火索是什么？", "grade": "八年级上册", "k": 4},
    },
    {
        "name": "quiz_generation_with_lesson_selects_generate_quiz",
        "message": "帮我出3道本课练习题",
        "grade": "七年级上册",
        "book_id": "history-grade-7a",
        "lesson_id": "lesson-1",
        "expected_tool": "generate_quiz",
        "expected_intent": "quiz_generation",
        "expected_input": {"book_id": "history-grade-7a", "lesson_id": "lesson-1", "count": 3},
    },
    {
        "name": "character_recommendation_selects_recommend_tool",
        "message": "我想了解唐朝，推荐一个历史人物",
        "grade": "七年级下册",
        "expected_tool": "recommend_character",
        "expected_intent": "character_recommendation",
        "expected_input": {"message": "我想了解唐朝，推荐一个历史人物", "grade": "七年级下册", "limit": 3},
    },
    {
        "name": "timeline_game_selects_game_tool",
        "message": "来一局历史时间线排序游戏",
        "grade": "八年级上册",
        "student_id": "trajectory-eval",
        "actor_role": "student",
        "expected_tool": "start_timeline_game",
        "expected_intent": "timeline_game",
        "expected_input": {"grade": "八年级上册", "difficulty": "easy", "student_id": "trajectory-eval", "mode": "llm"},
    },
    {
        "name": "textbook_qa_with_lesson_selects_textbook_tool",
        "message": "这课的重点是什么？",
        "grade": "七年级上册",
        "book_id": "history-grade-7a",
        "lesson_id": "lesson-1",
        "expected_tool": "get_textbook_lesson",
        "expected_intent": "textbook_qa",
        "expected_input": {"book_id": "history-grade-7a", "lesson_id": "lesson-1"},
    },
]


def run_trajectory_case(case: dict) -> tuple[bool, str, dict]:
    """Returns (ok, reason, detail)."""
    request = {
        "message": case["message"],
        "grade": case.get("grade", "八年级上册"),
        "student_id": case.get("student_id", "trajectory-eval"),
        "actor_role": case.get("actor_role", "anonymous"),
        **({"book_id": case["book_id"]} if case.get("book_id") else {}),
        **({"lesson_id": case["lesson_id"]} if case.get("lesson_id") else {}),
    }
    try:
        events = list(stream_learning_assistant_events(request))
    except Exception as exc:
        return False, f"exception: {exc}", {}

    intent_payload = next((data for event, data in events if event == "intent"), {})
    tool_results = [data for event, data in events if event == "tool_result"]
    called_tools = [r.get("tool_name") for r in tool_results if isinstance(r, dict)]
    runtime_steps = [data for event, data in events if event == "runtime_step"]
    selection_step = next((step for step in runtime_steps if step.get("step_id") == "tool_selection"), {})
    synthesis_step = next((step for step in runtime_steps if step.get("step_id") == "answer_synthesis"), {})
    final_payload = next((data for event, data in events if event == "final"), {})

    actual_intent = intent_payload.get("intent")
    expected_intent = case.get("expected_intent")
    expected_tool = case.get("expected_tool")
    expected_input = case.get("expected_input") or {}
    actual_input = (selection_step.get("metadata") or {}).get("input_summary") or {}

    detail = {
        "expected_intent": expected_intent,
        "actual_intent": actual_intent,
        "expected_tool": expected_tool,
        "called_tools": called_tools,
        "expected_input": expected_input,
        "actual_input": actual_input,
        "used_tool_count": (synthesis_step.get("metadata") or {}).get("used_tool_count"),
        "response_chars": len(str(final_payload.get("response") or "")),
    }

    if expected_intent and actual_intent != expected_intent:
        return False, f"intent mismatch: got={actual_intent}", detail
    if expected_tool and expected_tool not in called_tools:
        return False, f"tool not called: expected={expected_tool} got={called_tools}", detail
    mismatched_input = {
        key: {"expected": value, "actual": actual_input.get(key)}
        for key, value in expected_input.items()
        if actual_input.get(key) != value
    }
    if mismatched_input:
        return False, f"tool input mismatch: {mismatched_input}", detail
    if expected_tool and (synthesis_step.get("metadata") or {}).get("used_tool_count") != 1:
        return False, "answer synthesis did not consume the tool result", detail
    final_tools = final_payload.get("tool_results") or []
    if expected_tool and not final_tools:
        return False, "final response omitted tool results", detail
    if not str(final_payload.get("response") or "").strip():
        return False, "final response is empty", detail
    return True, "ok", detail


def print_failed_case(name: str, reason: str, **kw) -> None:
    payload = {"name": name, "reason": reason, **{k: v for k, v in kw.items() if v is not None}}
    print("FAILED_CASE_DETAIL=" + json.dumps(payload, ensure_ascii=False, default=str))


def main() -> None:
    passed = 0
    failed: list[str] = []
    for case in TRAJECTORY_CASES:
        ok, reason, detail = run_trajectory_case(case)
        if ok:
            passed += 1
            print(f"OK {case['name']}")
        else:
            failed.append(case["name"])
            print(f"FAIL {case['name']} {reason}")
            print_failed_case(case["name"], reason, category="trajectory", **detail)

    total = len(TRAJECTORY_CASES)
    correct = passed
    # A passing case now covers intent, tool selection, input correctness, result
    # propagation, and answer synthesis utilization.
    tool_accuracy = round(correct / total, 4) if total else 0.0
    print(f"trajectory_eval={passed}/{total}")
    print(f"tool_call_accuracy={tool_accuracy}")
    print(f"tool_input_accuracy={tool_accuracy}")
    print(f"tool_output_utilization_rate={tool_accuracy}")
    if failed:
        print(f"failed cases: {', '.join(failed)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
