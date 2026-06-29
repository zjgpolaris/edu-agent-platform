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
DATASET_PATH = ROOT / "eval" / "datasets" / "learning_assistant_cases.json"

from agents.learning_assistant import stream_learning_assistant_events


def print_failed_case(name: str, reason: str, **detail) -> None:
    payload = {"name": name, "reason": reason, **{k: v for k, v in detail.items() if v is not None}}
    print("FAILED_CASE_DETAIL=" + json.dumps(payload, ensure_ascii=False, default=str))


BASE_CASES = [
    {
        "name": "character_recommendation",
        "request": {"message": "我想了解秦始皇，推荐一个历史人物", "grade": "七年级上册"},
        "expected_intents": {"character_recommendation"},
        "needs_tool": True,
    },
    {
        "name": "timeline_game",
        "request": {"message": "来一局中国近代史时间线游戏", "grade": "八年级上册", "student_id": "eval-student", "actor_role": "student"},
        "expected_intents": {"timeline_game"},
        "needs_tool": True,
    },
    {
        "name": "history_search",
        "request": {"message": "鸦片战争为什么重要？", "grade": "八年级上册"},
        "expected_intents": {"history_search"},
        "needs_tool": True,
    },
    {
        "name": "quiz_without_lesson_fallback",
        "request": {"message": "帮我出 3 道本课练习题", "grade": "八年级上册"},
        "expected_intents": {"quiz_generation"},
        "needs_tool": True,
    },
    {
        "name": "high_risk_confirmation_demo",
        "request": {"message": "演示高风险工具，删除演示记忆", "grade": "八年级上册", "student_id": "eval-student", "actor_role": "student"},
        "expected_intents": {"memory_delete_demo"},
        "needs_tool": True,
        "expects_confirmation": True,
    },
]


def load_dataset_cases() -> list[dict]:
    if not DATASET_PATH.exists():
        return []
    try:
        raw_cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    cases: list[dict] = []
    for index, item in enumerate(raw_cases if isinstance(raw_cases, list) else []):
        if not isinstance(item, dict):
            continue
        message = item.get("message") or item.get("query") or item.get("text")
        if not isinstance(message, str) or not message.strip():
            continue
        expected = item.get("expected_intents")
        if isinstance(expected, str):
            expected_intents = {expected}
        elif isinstance(expected, list):
            expected_intents = {value for value in expected if isinstance(value, str)}
        else:
            single = item.get("expected_intent")
            expected_intents = {single} if isinstance(single, str) else set()
        request = {
            "message": message,
            "grade": item.get("grade") or "八年级上册",
            "student_id": item.get("student_id") or "eval-student",
            "actor_role": item.get("actor_role") or "student",
        }
        if item.get("book_id"):
            request["book_id"] = item["book_id"]
        if item.get("lesson_id"):
            request["lesson_id"] = item["lesson_id"]
        cases.append({
            "name": item.get("name") or f"dataset_case_{index + 1}",
            "request": request,
            "expected_intents": expected_intents,
            "needs_tool": item.get("needs_tool", False),
            "expects_error": item.get("expects_error") or item.get("expected_error") == "guardrail_blocked" or item.get("action") == "guardrail.blocked",
        })
    return cases


CASES = BASE_CASES + load_dataset_cases()


def run_case(case: dict) -> tuple[bool, str]:
    try:
        events = list(stream_learning_assistant_events(case["request"]))
    except Exception as exc:
        if case.get("expects_error"):
            return True, "ok"
        return False, str(exc) or "unexpected exception"
    if case.get("expects_error"):
        return False, "expected error but stream completed"
    event_names = [event for event, _ in events]
    intent_payload = next((data for event, data in events if event == "intent"), {})
    final_payload = next((data for event, data in events if event == "final"), {})
    tool_payloads = [data for event, data in events if event == "tool_result"]
    runtime_steps = [data for event, data in events if event == "runtime_step"]

    expected_intents = case.get("expected_intents") or set()
    if expected_intents and intent_payload.get("intent") not in expected_intents:
        return False, f"unexpected intent={intent_payload.get('intent')}"
    if case.get("needs_tool") and not tool_payloads:
        return False, "missing tool_result"
    if not runtime_steps:
        return False, "missing runtime_step"
    if case.get("expects_confirmation"):
        first_tool = tool_payloads[0] if tool_payloads else {}
        error = first_tool.get("error") or {}
        metadata = first_tool.get("metadata") or {}
        token = metadata.get("confirmation_token")
        tool_name = first_tool.get("tool_name")
        if error.get("code") != "confirmation_required" or not token or not tool_name:
            return False, "missing confirmation_required"
        confirmed_request = {
            **case["request"],
            "confirmed_tool_name": tool_name,
            "confirmation_token": token,
            "confirmation_decision": "confirmed",
        }
        confirmed_events = list(stream_learning_assistant_events(confirmed_request))
        confirmed_final = next((data for event, data in confirmed_events if event == "final"), {})
        confirmed_tools = confirmed_final.get("tool_results") or []
        if not confirmed_tools or not confirmed_tools[0].get("ok"):
            return False, "confirmed execution failed"
        if not ((confirmed_tools[0].get("data") or {}).get("deleted")):
            return False, "confirmed execution did not delete demo memory"
    if not final_payload.get("response"):
        return False, "missing final response"
    if "error" in event_names:
        return False, "unexpected error event"
    return True, "ok"


def main() -> None:
    passed = 0
    failed: list[str] = []
    for case in CASES:
        ok, reason = run_case(case)
        if ok:
            passed += 1
            print(f"OK {case['name']}")
        else:
            failed.append(case["name"])
            print(f"FAIL {case['name']} {reason}")
            print_failed_case(
                case["name"],
                reason,
                query=(case.get("request") or {}).get("message"),
                expected=sorted(case.get("expected_intents") or []),
                category="tools" if case.get("needs_tool") else "agent",
            )

    print(f"learning_assistant_smoke={passed}/{len(CASES)}")
    if failed:
        print(f"failed cases: {', '.join(failed)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
