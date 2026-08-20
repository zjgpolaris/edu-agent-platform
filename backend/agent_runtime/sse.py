from __future__ import annotations

import json
from typing import Any

from agent_runtime.models import RuntimeEvent

_SENSITIVE_KEYS = {
    "prompt",
    "system_prompt",
    "essay",
    "student_profile",
    "memory_content",
    "secret",
    "token",
    "confirmation_token",
    "stack",
    "traceback",
}


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else sanitize_public_payload(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_public_payload(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:4000]
    return value


def runtime_sse_frame(event: RuntimeEvent) -> str:
    safe = event.model_copy(update={"data": sanitize_public_payload(event.data)})
    payload = json.dumps(safe.model_dump(), ensure_ascii=False, separators=(",", ":"))
    return f"id: {safe.sequence}\nevent: {safe.event}\ndata: {payload}\n\n"
