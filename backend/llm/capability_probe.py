"""Explicit, synthetic live probes for configured LLM profiles."""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel
from tracing import current_trace_id, trace_context

from .registry import LLMRegistry, get_default_registry


_ONE_PIXEL_RED_PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


class _ProbeSchema(BaseModel):
    ok: bool
    message: str


def _run_check(callback: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        callback()
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error_type": exc.__class__.__name__,
        }


def _probe_profile(registry: LLMRegistry, profile_key: str) -> dict[str, Any]:
    managed = registry.get_model(profile_key)
    native = managed.as_langchain()
    checks: dict[str, dict[str, Any]] = {}

    checks["invoke"] = _run_check(
        lambda: managed.invoke(
            [
                {"role": "system", "content": "只按要求返回简短内容。"},
                {"role": "user", "content": "只回复 pong"},
            ],
            max_retries=1,
        )
    )
    checks["stream"] = _run_check(
        lambda: "".join(managed.stream_text([{"role": "user", "content": "只回复 stream-ok"}]))
    )

    def json_prompt() -> None:
        response = managed.invoke(
            [{"role": "user", "content": '只返回严格 JSON：{"ok":true,"message":"json-ok"}'}],
            max_retries=1,
        )
        payload = json.loads(response.content)
        _ProbeSchema.model_validate(payload)

    checks["json_prompt"] = _run_check(json_prompt)

    def native_structured() -> None:
        result = native.with_structured_output(_ProbeSchema).invoke(
            "返回 ok=true，message=structured-ok。"
        )
        _ProbeSchema.model_validate(result)

    checks["native_structured_output"] = _run_check(native_structured)

    def tool_calling() -> None:
        tool = {
            "type": "function",
            "function": {
                "name": "probe_weather",
                "description": "Return synthetic weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
        response = native.bind_tools([tool], tool_choice="probe_weather").invoke("查询北京天气")
        if not getattr(response, "tool_calls", None):
            raise RuntimeError("tool_call_not_returned")

    checks["tool_calling"] = _run_check(tool_calling)

    if "vision" in managed.profile.capabilities:
        checks["vision_base64"] = _run_check(
            lambda: managed.invoke(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "简短描述图片主色。"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{_ONE_PIXEL_RED_PNG}"},
                            },
                        ],
                    }
                ],
                max_retries=1,
            )
        )

    required = ["invoke", "json_prompt"]
    if "stream" in managed.profile.capabilities:
        required.append("stream")
    if "vision" in managed.profile.capabilities:
        required.append("vision_base64")
    return {
        "profile": profile_key,
        "name": managed.name,
        "model": managed.model,
        "provider": registry.provider,
        "transport": "langchain_openai",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "required_checks": required,
        "checks": checks,
        "result": "pass" if all(checks[name]["ok"] for name in required) else "fail",
    }


def probe_profile(registry: LLMRegistry, profile_key: str) -> dict[str, Any]:
    with trace_context(name="llm.capability_probe", metadata={"profile": profile_key, "provider": registry.provider}):
        result = _probe_profile(registry, profile_key)
        result["trace_id"] = current_trace_id()
        return result


def run_live_probe(profile_keys: list[str] | None = None) -> dict[str, Any]:
    registry = get_default_registry()
    selected = profile_keys or ["fast", "quality", "reasoning", "multimodal", "multimodal_quality"]
    profiles = [probe_profile(registry, key) for key in selected]
    return {
        "provider": registry.provider,
        "transport": "langchain_openai",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "profiles": profiles,
        "result": "pass" if all(item["result"] == "pass" for item in profiles) else "fail",
    }
