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

from agents import learning_assistant as la
from agents.learning_assistant import stream_learning_assistant_events
from agents.learning_assistant_planner import build_task_plan
from agents.learning_assistant_router import deterministic_route
from tools.base import ToolResult

COMPOSITION_DATASET = ROOT / "eval" / "datasets" / "learning_assistant_composition_cases.json"
CLARIFICATION_DATASET = ROOT / "eval" / "datasets" / "learning_assistant_clarification_cases.json"

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


def evaluate_composition_plans() -> tuple[int, int, list[dict]]:
    cases = json.loads(COMPOSITION_DATASET.read_text(encoding="utf-8"))
    passed = 0
    failures = []
    for case in cases:
        route = deterministic_route(case["request"])
        plan = build_task_plan(route, case["request"], enable_composition=True)
        actual_intents = [task.intent.value for task in route.tasks]
        actual_operations = [step.operation for step in plan.steps]
        if actual_intents == case["expected_intents"] and actual_operations == case["expected_plan_operations"]:
            passed += 1
        else:
            failures.append({"id": case["id"], "expected_intents": case["expected_intents"], "actual_intents": actual_intents, "expected_operations": case["expected_plan_operations"], "actual_operations": actual_operations})
    return passed, len(cases), failures


def evaluate_clarifications() -> tuple[int, int, list[dict]]:
    cases = json.loads(CLARIFICATION_DATASET.read_text(encoding="utf-8"))
    passed = 0
    failures = []
    for case in cases:
        route = deterministic_route(case["request"])
        ok = route.needs_clarification and all(slot in route.missing_slots for slot in case["expected_missing_slots"])
        if ok:
            passed += 1
        else:
            failures.append({"id": case["id"], "route": route.model_dump(mode="json")})
    return passed, len(cases), failures


def evaluate_composition_runtime() -> tuple[int, int, list[dict]]:
    cases = json.loads(COMPOSITION_DATASET.read_text(encoding="utf-8"))[:8]
    passed = 0
    failures = []
    original_tool = la.run_tool
    original_invoke = la.llm_fast.invoke
    previous_flag = os.environ.get("EDU_AGENT_ASSISTANT_PLANNER_ENABLED")

    class _Response:
        def __init__(self, content: str):
            self.content = content

    def fake_invoke(messages):
        system = "\n".join(str(item.get("content") or "") for item in messages if item.get("role") == "system")
        if "JSON 数组" in system:
            return _Response(json.dumps([
                {"id": "q1", "question": "史料说明了什么？", "answer": "A", "options": ["A. 核心史实", "B. 无关内容", "C. 错误年代", "D. 错误人物"]},
                {"id": "q2", "question": "该事件有何影响？", "answer": "推动历史变化", "options": None},
                {"id": "q3", "question": "如何理解该事件？", "answer": "结合原因和影响", "options": None},
                {"id": "q4", "question": "该事件发生在哪一背景？", "answer": "社会变革", "options": None},
                {"id": "q5", "question": "该事件的重要性是什么？", "answer": "影响后续发展", "options": None},
            ], ensure_ascii=False))
        return _Response("该事件应从背景、核心史实和影响三个层次理解。")

    def fake_tool(name, payload, context=None):
        assert name == "search_history_knowledge"
        return ToolResult(tool_name=name, ok=True, data={"sources": [{"topic": payload.get("topic") or "历史事件", "snippet": "可信史料说明了该事件的背景、经过与影响。", "source": "trajectory_eval"}]}, metadata={"source_count": 1, "query": payload.get("query")})

    os.environ["EDU_AGENT_ASSISTANT_PLANNER_ENABLED"] = "true"
    la.run_tool = fake_tool
    la.llm_fast.invoke = fake_invoke
    try:
        for case in cases:
            events = list(la.stream_learning_assistant_events({**case["request"], "student_id": "composition-eval", "actor_role": "student"}))
            route = next((data for event, data in events if event == "route"), {})
            plan = next((data for event, data in events if event == "plan"), {})
            final = next((data for event, data in events if event == "final"), {})
            tool_events = [data for event, data in events if event == "tool_result"]
            operations = [step.get("operation") for step in plan.get("steps") or []]
            ok = (
                [task.get("intent") for task in route.get("tasks") or []] == case["expected_intents"]
                and operations == case["expected_plan_operations"]
                and len(tool_events) == 1
                and final.get("completion_status") == "completed"
                and (final.get("plan_summary") or {}).get("completed_steps") == 3
                and any(item.get("tool_name") == "generate_quiz" for item in final.get("tool_results") or [])
            )
            if ok:
                passed += 1
            else:
                failures.append({"id": case["id"], "route": route, "operations": operations, "final": final})
    finally:
        la.run_tool = original_tool
        la.llm_fast.invoke = original_invoke
        if previous_flag is None:
            os.environ.pop("EDU_AGENT_ASSISTANT_PLANNER_ENABLED", None)
        else:
            os.environ["EDU_AGENT_ASSISTANT_PLANNER_ENABLED"] = previous_flag
    return passed, len(cases), failures


def evaluate_repair_and_rollback() -> tuple[int, int, list[dict]]:
    passed = 0
    failures: list[dict] = []
    original_tool = la.run_tool
    original_invoke = la.llm_fast.invoke
    previous_flag = os.environ.get("EDU_AGENT_ASSISTANT_PLANNER_ENABLED")

    class _Response:
        content = "洋务运动以自强、求富为口号，推动了近代工业发展。"

    try:
        calls = 0

        def repair_tool(name, payload, context=None):
            nonlocal calls
            calls += 1
            sources = [] if calls == 1 else [{"topic": "洋务运动", "snippet": "洋务派创办近代工业，主张自强求富。"}]
            return ToolResult(tool_name=name, ok=True, data={"sources": sources}, metadata={"source_count": len(sources), "query": payload.get("query")})

        os.environ["EDU_AGENT_ASSISTANT_PLANNER_ENABLED"] = "true"
        la.run_tool = repair_tool
        la.llm_fast.invoke = lambda messages: _Response()
        repair_events = list(la.stream_learning_assistant_events({"message": "解释洋务运动的影响", "student_id": "repair-eval", "actor_role": "student"}))
        repair_final = next((data for event, data in repair_events if event == "final"), {})
        repairs = [data for event, data in repair_events if event == "repair_attempt"]
        if calls == 2 and len(repairs) == 1 and repair_final.get("completion_status") == "completed":
            passed += 1
        else:
            failures.append({"id": "single_controlled_repair", "calls": calls, "repairs": repairs, "final": repair_final})

        os.environ["EDU_AGENT_ASSISTANT_PLANNER_ENABLED"] = "false"
        la.run_tool = lambda name, payload, context=None: ToolResult(
            tool_name=name,
            ok=True,
            data={"sources": [{"topic": "洋务运动", "snippet": "洋务运动推动近代化。"}]},
            metadata={"source_count": 1, "query": payload.get("query")},
        )
        rollback_events = list(la.stream_learning_assistant_events({"message": "先解释洋务运动，再出3道选择题", "student_id": "rollback-eval", "actor_role": "student"}))
        rollback_final = next((data for event, data in rollback_events if event == "final"), {})
        has_plan_event = any(event == "plan" for event, _ in rollback_events)
        generated_quiz = any(item.get("tool_name") == "generate_quiz" for item in rollback_final.get("tool_results") or [])
        if not has_plan_event and not generated_quiz and (rollback_final.get("plan_summary") or {}).get("total_steps") == 2:
            passed += 1
        else:
            failures.append({"id": "planner_flag_rollback", "has_plan_event": has_plan_event, "generated_quiz": generated_quiz, "final": rollback_final})
    finally:
        la.run_tool = original_tool
        la.llm_fast.invoke = original_invoke
        if previous_flag is None:
            os.environ.pop("EDU_AGENT_ASSISTANT_PLANNER_ENABLED", None)
        else:
            os.environ["EDU_AGENT_ASSISTANT_PLANNER_ENABLED"] = previous_flag
    return passed, 2, failures


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
    composition_passed, composition_total, composition_failures = evaluate_composition_plans()
    clarification_passed, clarification_total, clarification_failures = evaluate_clarifications()
    runtime_passed, runtime_total, runtime_failures = evaluate_composition_runtime()
    resilience_passed, resilience_total, resilience_failures = evaluate_repair_and_rollback()
    composition_rate = round(composition_passed / composition_total, 4) if composition_total else 0.0
    clarification_rate = round(clarification_passed / clarification_total, 4) if clarification_total else 0.0
    runtime_rate = round(runtime_passed / runtime_total, 4) if runtime_total else 0.0
    resilience_rate = round(resilience_passed / resilience_total, 4) if resilience_total else 0.0
    print(f"multi_intent_plan_exact_match={composition_rate}")
    print(f"clarification_trajectory_accuracy={clarification_rate}")
    print(f"composition_runtime_completion_rate={runtime_rate}")
    print(f"repair_and_rollback_accuracy={resilience_rate}")
    for detail in [*composition_failures[:3], *clarification_failures[:3], *runtime_failures[:3], *resilience_failures[:3]]:
        print_failed_case(str(detail.get("id") or "v2_trajectory"), "v2 trajectory mismatch", category="trajectory", detail=detail)
    if composition_rate < 0.85 or clarification_rate < 0.90 or runtime_rate < 0.85 or resilience_rate < 1.0:
        failed.append("v2_routing_or_composition")
    if failed:
        print(f"failed cases: {', '.join(failed)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
