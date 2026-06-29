"""Safe Langfuse tracing helpers."""
from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
from typing import Any, Iterator

from utils.cost_estimator import estimate_cost_usd

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_MAX_TEXT_CHARS = 8000
_MAX_ERROR_CHARS = 1000

_DATA_IMAGE_URL_RE = re.compile(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=\r\n]+")
_current_trace: ContextVar[Any | None] = ContextVar("current_langfuse_trace", default=None)
_current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
_langfuse_client: Any | None = None
_langfuse_checked = False
_langfuse_disabled_reason: str | None = None


class NoopObservation:
    def update(self, **_: Any) -> None:
        return None

    def end(self, **_: Any) -> None:
        return None


NOOP_OBSERVATION = NoopObservation()


def _env_true(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def is_tracing_enabled() -> bool:
    return _env_true("LANGFUSE_ENABLED", False) and get_langfuse_client() is not None


def capture_input_enabled() -> bool:
    return _env_true("LANGFUSE_CAPTURE_INPUT", True)


def capture_output_enabled() -> bool:
    return _env_true("LANGFUSE_CAPTURE_OUTPUT", True)


def get_langfuse_client() -> Any | None:
    global _langfuse_checked, _langfuse_client, _langfuse_disabled_reason

    if _langfuse_checked:
        return _langfuse_client

    _langfuse_checked = True
    if not _env_true("LANGFUSE_ENABLED", False):
        _langfuse_disabled_reason = "disabled"
        return None

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        _langfuse_disabled_reason = "missing_credentials"
        logger.warning("langfuse_disabled reason=%s", _langfuse_disabled_reason)
        return None

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=os.getenv("LANGFUSE_HOST") or None,
        )
        _langfuse_disabled_reason = None
        logger.info(
            "langfuse_enabled host=%s environment=%s release=%s",
            os.getenv("LANGFUSE_HOST", "default"),
            os.getenv("LANGFUSE_ENVIRONMENT", "local"),
            os.getenv("LANGFUSE_RELEASE", "edu-agent-local"),
        )
    except Exception as exc:
        _langfuse_client = None
        _langfuse_disabled_reason = "init_failed"
        logger.warning("langfuse_disabled reason=%s error=%s", _langfuse_disabled_reason, safe_error_message(exc))

    return _langfuse_client


def redact_data_urls(value: str) -> str:
    return _DATA_IMAGE_URL_RE.sub("[image:data-url omitted]", value)


def truncate_text(value: Any, max_chars: int = _MAX_TEXT_CHARS) -> str:
    text = redact_data_urls("" if value is None else str(value))
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated {len(text) - max_chars} chars]"


def safe_error_message(exc: BaseException | str, max_chars: int = _MAX_ERROR_CHARS) -> str:
    return truncate_text(str(exc), max_chars=max_chars)


def sanitize_content_block(content: Any, max_chars: int) -> Any:
    if isinstance(content, str):
        return truncate_text(content, max_chars=max_chars)
    if isinstance(content, list):
        sanitized_blocks = []
        for block in content:
            if not isinstance(block, dict):
                sanitized_blocks.append(truncate_text(block, max_chars=max_chars))
                continue
            sanitized_block = dict(block)
            if sanitized_block.get("type") == "text" and "text" in sanitized_block:
                sanitized_block["text"] = truncate_text(sanitized_block.get("text", ""), max_chars=max_chars)
            if sanitized_block.get("type") == "image_url" and isinstance(sanitized_block.get("image_url"), dict):
                image_url = dict(sanitized_block["image_url"])
                if "url" in image_url:
                    image_url["url"] = "[image:data-url omitted]"
                sanitized_block["image_url"] = image_url
            elif "url" in sanitized_block and isinstance(sanitized_block.get("url"), str):
                sanitized_block["url"] = redact_data_urls(sanitized_block["url"])
            sanitized_blocks.append(sanitized_block)
        return sanitized_blocks
    if isinstance(content, dict):
        return {key: sanitize_content_block(value, max_chars) for key, value in content.items()}
    return truncate_text(content, max_chars=max_chars)


def sanitize_messages(messages: Any, max_chars: int = _MAX_TEXT_CHARS) -> Any:
    if not capture_input_enabled():
        return None
    if isinstance(messages, str):
        return truncate_text(messages, max_chars=max_chars)
    if not isinstance(messages, list):
        return truncate_text(messages, max_chars=max_chars)

    sanitized = []
    for message in messages:
        if not isinstance(message, dict):
            sanitized.append(truncate_text(message, max_chars=max_chars))
            continue
        sanitized.append(
            {
                "role": message.get("role"),
                "content": sanitize_content_block(message.get("content", ""), max_chars),
            }
        )
    return sanitized


def sanitize_output(output: Any, max_chars: int = _MAX_TEXT_CHARS) -> Any:
    if not capture_output_enabled():
        return None
    return truncate_text(output, max_chars=max_chars)


def current_trace_id() -> str | None:
    return _current_trace_id.get()


def bind_trace_id(trace_id: str) -> None:
    """Bind an explicit trace_id into the current thread/task context (no-op if already set)."""
    if trace_id and not _current_trace_id.get():
        _current_trace_id.set(trace_id)


def set_trace_id(trace_id: str) -> None:
    """Force-set a trace_id in the current context, overriding any existing value."""
    if trace_id:
        _current_trace_id.set(trace_id)


def trace_metadata(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    trace_id = current_trace_id()
    if trace_id:
        metadata["trace_id"] = trace_id
    if extra:
        metadata.update({key: value for key, value in extra.items() if value is not None})
    return metadata


def base_metadata(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = {
        "service": "edu-agent-backend",
        "environment": os.getenv("LANGFUSE_ENVIRONMENT", "local"),
        "release": os.getenv("LANGFUSE_RELEASE", "edu-agent-local"),
    }
    metadata.update(trace_metadata(extra))
    return metadata


def start_trace(
    *,
    name: str,
    metadata: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    input_data: Any = None,
) -> Any:
    client = get_langfuse_client()
    if client is None or not hasattr(client, "trace"):
        return NOOP_OBSERVATION

    payload: dict[str, Any] = {"name": name, "metadata": base_metadata(metadata)}
    if user_id:
        payload["user_id"] = user_id
    if session_id:
        payload["session_id"] = session_id
    if input_data is not None and capture_input_enabled():
        payload["input"] = input_data

    try:
        return client.trace(**payload)
    except Exception as exc:
        logger.warning("langfuse_trace_start_failed error=%s", safe_error_message(exc))
        return NOOP_OBSERVATION


def end_trace(
    trace: Any,
    *,
    output: Any = None,
    metadata: dict[str, Any] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    end_observation(trace, output=output, metadata=metadata, level=level, status_message=status_message)


@contextmanager
def trace_context(
    *,
    name: str,
    metadata: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    input_data: Any = None,
) -> Iterator[Any]:
    trace_id = uuid4().hex
    trace_token = _current_trace_id.set(trace_id)
    trace = start_trace(name=name, metadata={**(metadata or {}), "trace_id": trace_id}, user_id=user_id, session_id=session_id, input_data=input_data)
    token = _current_trace.set(trace)
    try:
        yield trace
        end_trace(trace, metadata={"success": True, "trace_id": trace_id})
    except Exception as exc:
        end_trace(trace, metadata={"success": False, "trace_id": trace_id}, level="ERROR", status_message=safe_error_message(exc))
        raise
    finally:
        _current_trace.reset(token)
        _current_trace_id.reset(trace_token)


def start_span(
    *,
    name: str,
    input_data: Any = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    trace = _current_trace.get()
    if trace is NOOP_OBSERVATION or trace is None or not hasattr(trace, "span"):
        return NOOP_OBSERVATION

    payload: dict[str, Any] = {"name": name, "metadata": base_metadata(metadata)}
    if input_data is not None and capture_input_enabled():
        payload["input"] = input_data

    try:
        return trace.span(**payload)
    except Exception as exc:
        logger.warning("langfuse_span_start_failed error=%s", safe_error_message(exc))
        return NOOP_OBSERVATION


def end_span(
    span: Any,
    *,
    output: Any = None,
    metadata: dict[str, Any] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    end_observation(span, output=output, metadata=metadata, level=level, status_message=status_message)


def end_observation(
    observation: Any,
    *,
    output: Any = None,
    metadata: dict[str, Any] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    if observation is NOOP_OBSERVATION:
        return

    payload: dict[str, Any] = {}
    if metadata is not None:
        payload["metadata"] = metadata
    if output is not None and capture_output_enabled():
        payload["output"] = output
    if level:
        payload["level"] = level
    if status_message:
        payload["status_message"] = safe_error_message(status_message)

    try:
        if hasattr(observation, "end"):
            observation.end(**payload)
        elif hasattr(observation, "update"):
            observation.update(**payload)
    except Exception as exc:
        logger.warning("langfuse_observation_end_failed error=%s", safe_error_message(exc))


def start_generation(
    *,
    name: str,
    model: str,
    input_data: Any = None,
    metadata: dict[str, Any] | None = None,
    model_parameters: dict[str, Any] | None = None,
) -> Any:
    client = get_langfuse_client()
    if client is None:
        return NOOP_OBSERVATION

    payload = {
        "name": name,
        "model": model,
        "metadata": base_metadata(metadata),
    }
    if input_data is not None:
        payload["input"] = input_data
    if model_parameters:
        payload["model_parameters"] = model_parameters

    try:
        trace = _current_trace.get()
        if trace is not None and hasattr(trace, "generation"):
            return trace.generation(**payload)
        if hasattr(client, "generation"):
            return client.generation(**payload)
        if hasattr(client, "trace"):
            trace = client.trace(
                name="llm_standalone",
                metadata=base_metadata({"operation": metadata.get("operation") if metadata else None}),
            )
            if hasattr(trace, "generation"):
                return trace.generation(**payload)
    except Exception as exc:
        logger.warning("langfuse_generation_start_failed error=%s", safe_error_message(exc))
    return NOOP_OBSERVATION


def end_generation(
    generation: Any,
    *,
    output: Any = None,
    metadata: dict[str, Any] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    m = dict(metadata or {})
    # Auto-compute cost if model + token counts are present
    if "cost_usd" not in m and m.get("model") and m.get("input_tokens") is not None and m.get("output_tokens") is not None:
        m["cost_usd"] = estimate_cost_usd(str(m["model"]), int(m.get("input_tokens", 0)), int(m.get("output_tokens", 0)))
    end_observation(generation, output=output, metadata=m, level=level, status_message=status_message)


def safe_flush() -> None:
    client = get_langfuse_client()
    if client is None:
        return
    try:
        if hasattr(client, "flush"):
            client.flush()
    except Exception as exc:
        logger.warning("langfuse_flush_failed error=%s", safe_error_message(exc))


def safe_shutdown() -> None:
    client = get_langfuse_client()
    if client is None:
        return
    try:
        if hasattr(client, "shutdown"):
            client.shutdown()
        elif hasattr(client, "flush"):
            client.flush()
    except Exception as exc:
        logger.warning("langfuse_shutdown_failed error=%s", safe_error_message(exc))
