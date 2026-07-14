from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mcp_client import MCPClientError, MCPStdioClient  # noqa: E402
from trace_store import get_trace_store, trace_context  # noqa: E402


async def run() -> None:
    env = {
        "PYTHONPATH": str(BACKEND),
        "EDU_AGENT_DB_PATH": str(Path(tempfile.gettempdir()) / "edu-agent-mcp-client-smoke.sqlite3"),
    }
    allowed = {"get_textbook_lesson", "search_history_knowledge"}
    trace_id = "eval-mcp-client"
    with trace_context(trace_id):
        async with MCPStdioClient(
            [sys.executable, "-m", "backend.mcp_server"],
            cwd=ROOT,
            env={**os.environ, **env},
            allowed_tools=allowed,
        ) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == allowed
            lesson = await client.call_tool(
                "get_textbook_lesson",
                {"book_id": "history-grade-8a", "lesson_id": "lesson-1"},
            )
            assert lesson["source"] == "external_mcp"
            assert lesson["untrusted"] is True
            result = lesson["result"]
            assert result["isError"] is False
            assert result["structuredContent"]["data"]["lesson"]["lesson_id"] == "lesson-1"

            try:
                await client.call_tool("generate_quiz", {"topic": "辛亥革命"})
            except MCPClientError as exc:
                assert "not allowed" in str(exc)
            else:
                raise AssertionError("allowlist did not block undiscovered MCP tool")

    events = get_trace_store().get_trace(trace_id)
    event_types = [event["event_type"] for event in events]
    assert "tool_list" in event_types
    assert "tool_start" in event_types
    assert "tool_result" in event_types
    print("mcp_client_smoke=PASS")


if __name__ == "__main__":
    asyncio.run(run())
