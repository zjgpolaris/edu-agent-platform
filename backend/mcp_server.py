from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import BaseModel

from tools.base import ToolExecutionContext
from tools.registry import TOOLS, run_tool

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "edu-agent-mcp", "title": "EduAgent MCP Server", "version": "0.1.0"}
EXPOSED_TOOLS = {
    "search_history_knowledge",
    "get_textbook_lesson",
    "suggest_review_plan",
    "generate_quiz",
}


def _json_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _json_error(message_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _schema_for_model(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _tool_annotations(tool_name: str) -> dict[str, Any]:
    spec = TOOLS[tool_name]
    return {
        "readOnlyHint": spec.side_effect == "read",
        "destructiveHint": spec.side_effect == "write",
        "idempotentHint": spec.side_effect in {"read", "none"},
        "openWorldHint": spec.side_effect == "external_call",
        "riskLevel": spec.risk_level,
        "requiredRole": spec.required_role,
        "requiresConfirmation": spec.requires_confirmation,
    }


def mcp_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name in sorted(EXPOSED_TOOLS):
        spec = TOOLS[name]
        tools.append(
            {
                "name": spec.name,
                "title": spec.name.replace("_", " ").title(),
                "description": spec.description,
                "inputSchema": _schema_for_model(spec.input_model),
                "annotations": _tool_annotations(name),
            }
        )
    return tools


def _context_for_call(tool_name: str, arguments: dict[str, Any]) -> ToolExecutionContext:
    student_id = arguments.get("student_id")
    if tool_name == "suggest_review_plan":
        return ToolExecutionContext(
            actor_id=student_id if isinstance(student_id, str) else None,
            role="student",
            student_id=student_id if isinstance(student_id, str) else None,
            request_source="mcp",
        )
    return ToolExecutionContext(role="anonymous", request_source="mcp")


def _tool_call_result(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = run_tool(tool_name, arguments, context=_context_for_call(tool_name, arguments))
    structured_content: dict[str, Any] = {
        "ok": result.ok,
        "tool_name": result.tool_name,
        "data": result.data,
        "metadata": result.metadata,
    }
    if result.error:
        structured_content["error"] = result.error.model_dump()
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured_content, ensure_ascii=False, default=str),
            }
        ],
        "structuredContent": structured_content,
        "isError": not result.ok,
    }


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _json_response(message_id, {})
    if method == "initialize":
        requested_version = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        protocol_version = requested_version if requested_version == PROTOCOL_VERSION else PROTOCOL_VERSION
        return _json_response(
            message_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": "EduAgent exposes selected education tools through MCP while preserving registry validation, role policy, confirmation metadata, audit, and tracing.",
            },
        )
    if method == "tools/list":
        return _json_response(message_id, {"tools": mcp_tools()})
    if method == "tools/call":
        if not isinstance(params, dict):
            return _json_error(message_id, -32602, "Invalid params")
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(tool_name, str) or tool_name not in EXPOSED_TOOLS:
            return _json_error(message_id, -32602, f"Unknown tool: {tool_name}")
        if not isinstance(arguments, dict):
            return _json_error(message_id, -32602, "Tool arguments must be an object")
        return _json_response(message_id, _tool_call_result(tool_name, arguments))
    return _json_error(message_id, -32601, f"Method not found: {method}")


def serve_stdio() -> None:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            _write(_json_error(None, -32700, "Parse error", {"detail": str(exc)}))
            continue
        if not isinstance(message, dict):
            _write(_json_error(None, -32600, "Invalid request"))
            continue
        try:
            response = handle_request(message)
        except Exception as exc:
            response = _json_error(message.get("id"), -32603, "Internal error", {"detail": str(exc)})
        if response is not None and "id" in message:
            _write(response)


if __name__ == "__main__":
    serve_stdio()
