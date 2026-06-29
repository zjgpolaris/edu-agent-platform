from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
DATASET_PATH = ROOT / "eval" / "datasets" / "tool_registry_cases.json"

DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")
if not os.environ.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
    os.environ["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)
os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-tool-registry-smoke.sqlite3")
try:
    Path(os.environ["EDU_AGENT_DB_PATH"]).unlink()
except FileNotFoundError:
    pass

from tools.base import ToolExecutionContext
from tools.registry import list_tools, run_tool


def print_failed_case(name: str, reason: str, **detail) -> None:
    payload = {"name": name, "reason": reason, **{k: v for k, v in detail.items() if v is not None}}
    print("FAILED_CASE_DETAIL=" + json.dumps(payload, ensure_ascii=False, default=str))

REQUIRED_TOOL_FIELDS = {
    "name",
    "description",
    "input_schema",
    "output_schema",
    "risk_level",
    "side_effect",
    "required_role",
    "requires_confirmation",
    "timeout_seconds",
    "audit_enabled",
}
EXPECTED_TOOLS = {
    "search_history_knowledge",
    "get_textbook_lesson",
    "generate_quiz",
    "recommend_character",
    "start_timeline_game",
    "get_student_profile",
    "record_learning_event",
    "suggest_review_plan",
    "delete_demo_memory",
}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_SIDE_EFFECTS = {"none", "read", "write", "session_create", "external_call"}
VALID_ROLES = {"anonymous", "student", "teacher", "admin"}


def run_case(name: str, fn: Callable[[], None]) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        print(f"FAIL {name}: {reason}")
        print_failed_case(name, reason, category="tools", expected="tool registry/governance contract passes")
        return False


def list_tools_contract() -> None:
    tools = list_tools()
    assert tools, "list_tools returned no tools"
    names = {tool.get("name") for tool in tools}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {sorted(missing)}"

    for tool in tools:
        missing_fields = REQUIRED_TOOL_FIELDS - set(tool)
        assert not missing_fields, f"{tool.get('name')} missing fields: {sorted(missing_fields)}"
        assert isinstance(tool["name"], str) and tool["name"], "invalid tool name"
        assert isinstance(tool["description"], str) and tool["description"], f"{tool['name']} missing description"
        assert tool["risk_level"] in VALID_RISK_LEVELS, f"{tool['name']} invalid risk_level"
        assert tool["side_effect"] in VALID_SIDE_EFFECTS, f"{tool['name']} invalid side_effect"
        assert tool["required_role"] in VALID_ROLES, f"{tool['name']} invalid required_role"
        assert isinstance(tool["requires_confirmation"], bool), f"{tool['name']} invalid requires_confirmation"
        assert isinstance(tool["timeout_seconds"], int), f"{tool['name']} invalid timeout_seconds"
        assert isinstance(tool["audit_enabled"], bool), f"{tool['name']} invalid audit_enabled"


def input_schemas_are_json_schema_objects() -> None:
    for tool in list_tools():
        schema = tool["input_schema"]
        assert isinstance(schema, dict), f"{tool['name']} input_schema is not an object"
        assert schema.get("type") == "object", f"{tool['name']} input_schema type is not object"
        assert isinstance(schema.get("properties"), dict), f"{tool['name']} input_schema has no properties"
        output_schema = tool["output_schema"]
        assert output_schema is None or isinstance(output_schema, dict), f"{tool['name']} output_schema is invalid"


def normalized_tool_not_found() -> None:
    result = run_tool("missing_tool", {})
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "tool_not_found"


def normalized_invalid_input() -> None:
    result = run_tool("search_history_knowledge", {})
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "invalid_input"
    assert "duration_ms" in result.metadata


def deterministic_success_path() -> None:
    result = run_tool("suggest_review_plan", {"student_id": "tool-registry-smoke", "limit": 2}, context=ToolExecutionContext(role="student", student_id="tool-registry-smoke", request_source="eval"))
    assert result.ok, result.error.message if result.error else "tool failed"
    assert result.data["review_plan"]
    assert "duration_ms" in result.metadata


def low_risk_tool_allowed() -> None:
    result = run_tool("search_history_knowledge", {"query": "鸦片战争", "k": 1}, context=ToolExecutionContext(role="anonymous", request_source="eval"))
    assert result.ok or (result.error and result.error.code in {"not_found", "tool_failed"})
    assert result.metadata["risk_level"] == "low"


def role_denied_for_student_tool() -> None:
    result = run_tool("get_student_profile", {"student_id": "tool-governance-smoke"}, context=ToolExecutionContext(role="anonymous", request_source="eval"))
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "role_denied"


def high_risk_requires_confirmation() -> None:
    result = run_tool(
        "delete_demo_memory",
        {"student_id": "tool-governance-smoke", "memory_id": "demo_wrong_memory_001", "reason": "eval"},
        context=ToolExecutionContext(role="student", student_id="tool-governance-smoke", request_source="eval"),
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "confirmation_required"
    assert result.metadata.get("confirmation_token")


def high_risk_confirmed_executes() -> None:
    payload = {"student_id": "tool-governance-smoke", "memory_id": "demo_wrong_memory_001", "reason": "eval"}
    first = run_tool("delete_demo_memory", payload, context=ToolExecutionContext(role="student", student_id="tool-governance-smoke", request_source="eval"))
    token = first.metadata.get("confirmation_token")
    assert isinstance(token, str) and token
    second = run_tool(
        "delete_demo_memory",
        payload,
        context=ToolExecutionContext(role="student", student_id="tool-governance-smoke", confirmed=True, confirmation_token=token, request_source="eval"),
    )
    assert second.ok, second.error.message if second.error else "confirmed tool failed"
    assert second.data["scope"] == "demo_only"


def load_dataset_case_functions() -> list[tuple[str, Callable[[], None]]]:
    if not DATASET_PATH.exists():
        return []
    try:
        raw_cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    cases: list[tuple[str, Callable[[], None]]] = []
    for index, item in enumerate(raw_cases if isinstance(raw_cases, list) else []):
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool_name")
        payload = item.get("payload")
        if not isinstance(tool_name, str) or not isinstance(payload, dict):
            continue
        expected_error = item.get("expected_error") or item.get("error_code")
        expected_ok = item.get("expected_ok")
        role = item.get("actor_role") or item.get("role") or "student"
        student_id = item.get("student_id") or payload.get("student_id")
        confirmed = bool(item.get("confirmed"))
        confirmation_token = item.get("confirmation_token") if isinstance(item.get("confirmation_token"), str) else None
        name = str(item.get("name") or f"dataset_case_{index + 1}")

        def fn(tool_name=tool_name, payload=payload, expected_error=expected_error, expected_ok=expected_ok, role=role, student_id=student_id, confirmed=confirmed, confirmation_token=confirmation_token) -> None:
            result = run_tool(tool_name, payload, context=ToolExecutionContext(role=role, student_id=student_id, confirmed=confirmed, confirmation_token=confirmation_token, request_source="eval_dataset"))
            if expected_error:
                assert not result.ok
                assert result.error is not None
                assert result.error.code == expected_error
            elif expected_ok is not None:
                assert result.ok is bool(expected_ok)
            else:
                assert result.ok or result.error is not None

        cases.append((f"dataset_{name}", fn))
    return cases


def main() -> None:
    cases = [
        ("list_tools_contract", list_tools_contract),
        ("input_schemas_are_json_schema_objects", input_schemas_are_json_schema_objects),
        ("normalized_tool_not_found", normalized_tool_not_found),
        ("normalized_invalid_input", normalized_invalid_input),
        ("deterministic_success_path", deterministic_success_path),
        ("low_risk_tool_allowed", low_risk_tool_allowed),
        ("role_denied_for_student_tool", role_denied_for_student_tool),
        ("high_risk_requires_confirmation", high_risk_requires_confirmation),
        ("high_risk_confirmed_executes", high_risk_confirmed_executes),
    ]
    governance_names = {name for name, _ in cases[-4:]}
    cases.extend(load_dataset_case_functions())
    results = [(name, run_case(name, fn)) for name, fn in cases]
    passed = sum(1 for _, ok in results if ok)
    governance_passed = sum(1 for name, ok in results if name in governance_names and ok)
    print(f"tool_registry_smoke={passed}/{len(cases)}")
    print(f"tool_governance={governance_passed}/4")
    if passed != len(cases) or governance_passed != 4:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
