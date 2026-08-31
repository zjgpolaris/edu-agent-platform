"""LangChain provider factories and provider error normalization."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .contracts import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProfile,
)


DEFAULT_BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_ALLOWED_BAILIAN_HOST_SUFFIXES = ("dashscope.aliyuncs.com",)
_TRUE_VALUES = {"1", "true", "yes", "on"}


def bailian_api_key() -> str | None:
    return os.getenv("BAILIAN_API_KEY")


def bailian_base_url() -> str:
    return (os.getenv("BAILIAN_BASE_URL") or DEFAULT_BAILIAN_BASE_URL).rstrip("/")


def bailian_base_url_host() -> str:
    return (urlparse(bailian_base_url()).hostname or "invalid").lower()


def _allow_custom_endpoint() -> bool:
    return os.getenv("EDU_AGENT_LLM_ALLOW_CUSTOM_ENDPOINT", "").strip().lower() in _TRUE_VALUES


def provider_configuration_errors(provider: str = "bailian_openai") -> list[str]:
    errors: list[str] = []
    if provider != "bailian_openai":
        return [f"unsupported LLM provider: {provider}"]
    if not bailian_api_key():
        errors.append("BAILIAN_API_KEY is not configured")
    endpoint = bailian_base_url()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" and not _allow_custom_endpoint():
        errors.append("BAILIAN_BASE_URL must use HTTPS")
    hostname = (parsed.hostname or "").lower()
    if not _allow_custom_endpoint() and not any(
        hostname == suffix or hostname.endswith(f".{suffix}") for suffix in _ALLOWED_BAILIAN_HOST_SUFFIXES
    ):
        errors.append("BAILIAN_BASE_URL host is not allowed")
    return errors


def create_chat_model(profile: LLMProfile) -> Any:
    errors = provider_configuration_errors(profile.provider)
    if errors:
        raise LLMConfigurationError("; ".join(errors))
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:  # pragma: no cover - exercised by environment verification
        raise LLMConfigurationError("langchain-openai is not installed") from exc

    return ChatOpenAI(
        model=profile.model,
        api_key=bailian_api_key(),
        base_url=bailian_base_url(),
        max_tokens=profile.max_tokens,
        timeout=profile.timeout_seconds,
        max_retries=0,
        include_response_headers=True,
    )


def normalize_provider_error(exc: BaseException) -> Exception:
    if isinstance(exc, (LLMConfigurationError, LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderError)):
        return exc

    name = exc.__class__.__name__.lower()
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)

    if status in {401, 403} or "authentication" in name or "permission" in name:
        return LLMAuthenticationError("LLM provider authentication failed")
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return LLMRateLimitError("LLM provider rate limit exceeded")
    if "timeout" in name or isinstance(exc, TimeoutError):
        return LLMTimeoutError("LLM provider request timed out")
    if isinstance(status, int):
        return LLMProviderError(f"LLM provider request failed with status {status}")
    return LLMProviderError(f"LLM provider request failed ({exc.__class__.__name__})")


def provider_request_metadata(message: Any) -> dict[str, Any]:
    response_metadata = getattr(message, "response_metadata", None)
    usage_metadata = getattr(message, "usage_metadata", None)
    result: dict[str, Any] = {}
    if isinstance(response_metadata, dict):
        finish_reason = response_metadata.get("finish_reason")
        headers = response_metadata.get("headers")
        request_id = response_metadata.get("request_id") or response_metadata.get("id")
        if isinstance(headers, dict):
            request_id = request_id or headers.get("x-request-id") or headers.get("request-id")
        if finish_reason is not None:
            result["finish_reason"] = str(finish_reason)
        if request_id is not None:
            result["provider_request_id"] = str(request_id)[:200]
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, dict):
            result["input_tokens"] = token_usage.get("prompt_tokens")
            result["output_tokens"] = token_usage.get("completion_tokens")
            result["total_tokens"] = token_usage.get("total_tokens")
    if isinstance(usage_metadata, dict):
        result["input_tokens"] = usage_metadata.get("input_tokens", result.get("input_tokens"))
        result["output_tokens"] = usage_metadata.get("output_tokens", result.get("output_tokens"))
        result["total_tokens"] = usage_metadata.get("total_tokens", result.get("total_tokens"))
    return {key: value for key, value in result.items() if value is not None}
