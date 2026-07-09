from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")
if not os.environ.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
    os.environ["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)
os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-mcp-smoke.sqlite3")

EXPECTED_TOOLS = {
    "search_history_knowledge",
    "get_textbook_lesson",
    "suggest_review_plan",
    "generate_quiz",
}


def start_server() -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    return subprocess.Popen(
        [sys.executable, "-m", "backend.mcp_server"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def request(proc: subprocess.Popen[str], message: dict[str, Any]) -> dict[str, Any]:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, "MCP server returned no response"
    payload = json.loads(line)
    assert payload.get("jsonrpc") == "2.0"
    assert payload.get("id") == message.get("id")
    return payload


def assert_ok_response(payload: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in payload, payload.get("error")
    result = payload.get("result")
    assert isinstance(result, dict), "missing result"
    return result


def main() -> None:
    proc = start_server()
    try:
        initialized = assert_ok_response(
            request(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "edu-agent-mcp-smoke", "version": "0.1.0"},
                    },
                },
            )
        )
        assert initialized["protocolVersion"] == "2025-06-18"
        assert "tools" in initialized["capabilities"]
        assert proc.stdin is not None
        proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        proc.stdin.flush()

        listed = assert_ok_response(request(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
        tools = listed.get("tools")
        assert isinstance(tools, list) and tools
        names = {tool.get("name") for tool in tools}
        assert names == EXPECTED_TOOLS, f"unexpected MCP tools: {sorted(names)}"
        for tool in tools:
            assert isinstance(tool.get("inputSchema"), dict)
            assert isinstance(tool.get("annotations"), dict)

        lesson = assert_ok_response(
            request(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "get_textbook_lesson", "arguments": {"book_id": "history-grade-8a", "lesson_id": "lesson-1"}},
                },
            )
        )
        assert lesson.get("isError") is False
        assert lesson["structuredContent"]["ok"] is True
        assert lesson["structuredContent"]["data"]["lesson"]["lesson_id"] == "lesson-1"
        assert lesson["structuredContent"]["data"]["lesson"]["items"]

        history = assert_ok_response(
            request(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "search_history_knowledge", "arguments": {"query": "鸦片战争", "k": 1}},
                },
            )
        )
        assert history.get("isError") is False
        assert history["structuredContent"]["ok"] is True

        denied = request(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "delete_demo_memory", "arguments": {"student_id": "demo-student", "memory_id": "demo_1"}},
            },
        )
        assert denied["error"]["code"] == -32602

        print("mcp_server_smoke=PASS")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


if __name__ == "__main__":
    main()
