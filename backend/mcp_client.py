from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from trace_store import current_trace_id, emit_trace_event

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ROLE_LEVEL = {"anonymous": 0, "student": 1, "teacher": 2, "admin": 3}


def _emit_mcp_trace(step_name: str, event_type: str, *, status: str = "success", metadata: dict[str, Any] | None = None) -> None:
    if current_trace_id():
        emit_trace_event("mcp_client", step_name, event_type, status=status, metadata=metadata)


class MCPClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]

    @property
    def required_role(self) -> str:
        value = self.annotations.get("requiredRole")
        return value if isinstance(value, str) else "anonymous"

    @property
    def requires_confirmation(self) -> bool:
        return self.annotations.get("requiresConfirmation") is True


def _sanitize_value(value: Any, *, max_string_chars: int) -> Any:
    if isinstance(value, str):
        cleaned = _CONTROL_CHARS.sub("", value)
        if len(cleaned) > max_string_chars:
            return cleaned[:max_string_chars] + "…[truncated]"
        return cleaned
    if isinstance(value, list):
        return [_sanitize_value(item, max_string_chars=max_string_chars) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item, max_string_chars=max_string_chars)
            for key, item in value.items()
        }
    return value


class MCPStdioClient:
    """Minimal MCP stdio client with local policy enforcement and safe output wrapping."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        allowed_tools: set[str] | None = None,
        timeout_seconds: float = 30.0,
        max_output_chars: int = 12_000,
    ) -> None:
        if not command:
            raise ValueError("MCP command is required")
        self.command = list(command)
        self.cwd = str(cwd) if cwd is not None else None
        self.env = {**os.environ, **(env or {})}
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._tools: dict[str, MCPTool] = {}

    async def __aenter__(self) -> "MCPStdioClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._process is not None:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=self.cwd,
            env=self.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await self._request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "edu-agent-mcp-client", "version": "0.1.0"},
                },
            )
            await self._notify("notifications/initialized")
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        process, self._process = self._process, None
        self._tools = {}
        if process is None or process.returncode is not None:
            return
        process.terminate()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=3)
        if process.returncode is None:
            process.kill()
            await process.wait()

    async def list_tools(self, *, refresh: bool = False) -> list[MCPTool]:
        if self._tools and not refresh:
            return list(self._tools.values())
        result = await self._request("tools/list", {})
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise MCPClientError("MCP tools/list returned an invalid tool list")
        discovered: dict[str, MCPTool] = {}
        for raw in raw_tools:
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                continue
            name = raw["name"]
            if self.allowed_tools is not None and name not in self.allowed_tools:
                continue
            discovered[name] = MCPTool(
                name=name,
                description=str(raw.get("description") or ""),
                input_schema=raw.get("inputSchema") if isinstance(raw.get("inputSchema"), dict) else {},
                annotations=raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {},
            )
        self._tools = discovered
        _emit_mcp_trace(
            "tools_discovered",
            "tool_list",
            metadata={"tool_count": len(discovered), "tools": sorted(discovered)},
        )
        return list(discovered.values())

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        role: str = "anonymous",
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not self._tools:
            await self.list_tools()
        tool = self._tools.get(name)
        if tool is None:
            raise MCPClientError(f"MCP tool is not allowed or was not discovered: {name}")
        if _ROLE_LEVEL.get(role, -1) < _ROLE_LEVEL.get(tool.required_role, 99):
            raise MCPClientError(f"Role {role} cannot call MCP tool {name}; requires {tool.required_role}")
        if tool.requires_confirmation and not confirmed:
            raise MCPClientError(f"MCP tool requires confirmation: {name}")
        if not isinstance(arguments, dict):
            raise MCPClientError("MCP tool arguments must be an object")

        _emit_mcp_trace(
            name,
            "tool_start",
            status="pending",
            metadata={"tool_name": name, "role": role, "arguments": arguments},
        )
        try:
            result = await self._request("tools/call", {"name": name, "arguments": arguments})
        except Exception as exc:
            _emit_mcp_trace(
                name,
                "tool_error",
                status="error",
                metadata={"tool_name": name, "error": str(exc)},
            )
            raise

        sanitized = _sanitize_value(result, max_string_chars=self.max_output_chars)
        wrapped = {
            "source": "external_mcp",
            "untrusted": True,
            "tool_name": name,
            "result": sanitized,
        }
        _emit_mcp_trace(
            name,
            "tool_result",
            metadata={"tool_name": name, "is_error": bool(result.get("isError"))},
        )
        return wrapped

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        process = self._require_process()
        assert process.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await process.stdin.drain()

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            process = self._require_process()
            assert process.stdin is not None and process.stdout is not None
            self._request_id += 1
            request_id = self._request_id
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            await process.stdin.drain()
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=self.timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise MCPClientError(f"MCP request timed out: {method}") from exc
            if not line:
                detail = ""
                if process.stderr is not None:
                    with suppress(asyncio.TimeoutError):
                        detail = (await asyncio.wait_for(process.stderr.read(), timeout=0.2)).decode(errors="replace")
                raise MCPClientError(f"MCP server closed stdout during {method}: {detail[:500]}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MCPClientError(f"MCP server returned invalid JSON during {method}") from exc
            if response.get("id") != request_id:
                raise MCPClientError(f"MCP response id mismatch during {method}")
            if isinstance(response.get("error"), dict):
                error = response["error"]
                raise MCPClientError(f"MCP {method} failed: {error.get('message', 'unknown error')}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise MCPClientError(f"MCP {method} returned no result object")
            return result

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None or self._process.returncode is not None:
            raise MCPClientError("MCP client is not started")
        return self._process
