"""Managed LangChain chat model with EduAgent retry, fallback and trace semantics."""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from tracing import end_generation, safe_error_message, sanitize_messages, sanitize_output, start_generation

from .contracts import (
    LLMAuthenticationError,
    LLMCapabilityError,
    LLMConfigurationError,
    LLMEmptyResponseError,
    LLMProfile,
    LLMStreamInterruptedError,
    LLMUnavailableError,
)
from .providers import create_chat_model, normalize_provider_error, provider_request_metadata


logger = logging.getLogger(__name__)
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") in {"text", "output_text"}:
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content or "")


def _ai_message(message: Any, content: str, *, provenance: Mapping[str, Any] | None = None) -> AIMessage:
    response_metadata = dict(getattr(message, "response_metadata", {}) or {})
    if provenance:
        response_metadata["edu_agent_provenance"] = dict(provenance)
    return AIMessage(
        content=content,
        additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
        response_metadata=response_metadata,
        id=getattr(message, "id", None),
        usage_metadata=getattr(message, "usage_metadata", None),
    )


class ManagedChatModel:
    """Compatibility facade over native LangChain models.

    Existing EduAgent code uses invoke().content and stream() -> str. New graph
    code should use as_langchain() and the standard BaseChatModel contract.
    """

    def __init__(
        self,
        profile: LLMProfile,
        profiles: Mapping[str, LLMProfile],
        *,
        client_factory: Callable[[LLMProfile], Any] = create_chat_model,
        sleep: Callable[[float], None] = time.sleep,
        capability_enabled: Callable[[str], bool] | None = None,
    ) -> None:
        self.profile = profile
        self._profiles = dict(profiles)
        self._client_factory = client_factory
        self._sleep = sleep
        self._capability_enabled = capability_enabled
        self._clients: dict[str, Any] = {}

        self.name = profile.name
        self.model = profile.model
        self.max_tokens = profile.max_tokens
        self.fallback_profiles = list(profile.fallback_profiles)
        self.fallback_models = [self._profiles[name].model for name in profile.fallback_profiles]

    @staticmethod
    def _execution_disabled() -> bool:
        return os.getenv("EDU_AGENT_LLM_DISABLED", "").strip().lower() in _TRUE_VALUES

    def _profile_chain(self, *, allow_fallback: bool = True) -> list[LLMProfile]:
        profiles = [self.profile]
        if allow_fallback:
            profiles.extend(self._profiles[name] for name in self.profile.fallback_profiles)
        return list({profile.name: profile for profile in profiles}.values())

    def _capability_allowed(self, capability: str) -> bool:
        normalized = "tool_calling" if capability == "tools" else capability
        if capability in self.profile.capabilities or normalized in self.profile.capabilities:
            return True
        return bool(self._capability_enabled and self._capability_enabled(normalized))

    def _client(self, profile: LLMProfile) -> Any:
        if profile.name not in self._clients:
            self._clients[profile.name] = self._client_factory(profile)
        return self._clients[profile.name]

    def _validate_messages(self, messages: Any, profile: LLMProfile) -> None:
        if isinstance(messages, str):
            if not messages.strip():
                raise LLMConfigurationError("LLM messages must not be empty")
            return
        if not isinstance(messages, Sequence) or isinstance(messages, (bytes, bytearray)) or not messages:
            raise LLMConfigurationError("LLM messages must be a non-empty string or sequence")
        for message in messages:
            if isinstance(message, BaseMessage):
                role = getattr(message, "type", "")
                content = message.content
            elif isinstance(message, Mapping):
                role = str(message.get("role") or "")
                content = message.get("content", "")
            else:
                raise LLMConfigurationError("LLM message must be a mapping or BaseMessage")
            if role not in {"system", "user", "human", "assistant", "ai", "tool"}:
                raise LLMConfigurationError(f"unsupported LLM message role: {role or 'missing'}")
            if role == "tool" and not self._capability_allowed("tool_calling"):
                raise LLMCapabilityError(f"LLM profile {profile.name} has not passed tool capability validation")
            if isinstance(content, str):
                continue
            if not isinstance(content, Sequence) or isinstance(content, (bytes, bytearray)):
                raise LLMConfigurationError("LLM message content must be text or content blocks")
            for block in content:
                if not isinstance(block, Mapping):
                    raise LLMConfigurationError("LLM content block must be a mapping")
                if block.get("type") == "image_url" and "vision" not in profile.capabilities:
                    raise LLMCapabilityError(f"LLM profile {profile.name} does not support image input")

    def as_langchain(self) -> Any:
        if self._execution_disabled():
            raise LLMConfigurationError("LLM execution is disabled for this deterministic run")
        return self._client(self.profile)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        if not self._capability_allowed("tool_calling"):
            raise LLMCapabilityError(f"LLM profile {self.profile.name} has not passed tool capability validation")
        return self.as_langchain().bind_tools(tools, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        if not self._capability_allowed("native_structured_output"):
            raise LLMCapabilityError(
                f"LLM profile {self.profile.name} has not passed native structured output validation"
            )
        return self.as_langchain().with_structured_output(schema, **kwargs)

    def _trace_metadata(
        self,
        profile: LLMProfile,
        model_attempt: int,
        model_retry: int,
        operation: str,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "provider": "bailian",
            "transport": profile.provider,
            "llm_name": self.name,
            "profile": profile.name,
            "configured_model": self.model,
            "attempt_model": profile.model,
            "model_attempt": model_attempt,
            "model_retry": model_retry,
            "fallback_profiles": self.fallback_profiles,
            "fallback_models": self.fallback_models,
            "max_tokens": profile.max_tokens,
            "stream": stream,
            "operation": operation,
        }

    def invoke(
        self,
        messages: Any,
        max_retries: int | None = None,
        *,
        allow_fallback: bool = True,
        **kwargs: Any,
    ) -> AIMessage:
        if self._execution_disabled():
            raise LLMConfigurationError("LLM execution is disabled for this deterministic run")
        last_error: Exception | None = None
        retry_override = max(1, int(max_retries)) if max_retries is not None else None

        for model_attempt, profile in enumerate(self._profile_chain(allow_fallback=allow_fallback), start=1):
            self._validate_messages(messages, profile)
            attempts = retry_override if retry_override is not None else profile.max_attempts
            for model_retry in range(attempts):
                metadata = self._trace_metadata(profile, model_attempt, model_retry, "invoke", False)
                generation = start_generation(
                    name="llm.invoke",
                    model=profile.model,
                    input_data=sanitize_messages(messages),
                    metadata=metadata,
                    model_parameters={"max_tokens": profile.max_tokens, "stream": False},
                )
                try:
                    started = time.perf_counter()
                    response = self._client(profile).invoke(messages, **kwargs)
                    content = _content_text(getattr(response, "content", response)).strip()
                    if not content:
                        last_error = LLMEmptyResponseError(f"{profile.name}/{profile.model} returned empty content")
                        end_generation(
                            generation,
                            metadata={**metadata, "latency_ms": int((time.perf_counter() - started) * 1000), "output_chars": 0},
                            level="WARNING",
                            status_message=str(last_error),
                        )
                        break
                    response_meta = provider_request_metadata(response)
                    end_generation(
                        generation,
                        output=sanitize_output(content),
                        metadata={
                            **metadata,
                            **response_meta,
                            "model": profile.model,
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                            "output_chars": len(content),
                        },
                    )
                    logger.info(
                        "llm_invoke_success profile=%s model=%s model_attempt=%s model_retry=%s chars=%s",
                        profile.name,
                        profile.model,
                        model_attempt,
                        model_retry,
                        len(content),
                    )
                    return _ai_message(
                        response,
                        content,
                        provenance={
                            "provider": "bailian",
                            "transport": profile.provider,
                            "configured_profile": self.profile.name,
                            "executed_profile": profile.name,
                            "configured_model": self.profile.model,
                            "executed_model": profile.model,
                            "model_attempt": model_attempt,
                        },
                    )
                except LLMEmptyResponseError:
                    raise
                except Exception as exc:
                    normalized = normalize_provider_error(exc)
                    last_error = normalized
                    end_generation(
                        generation,
                        metadata=metadata,
                        level="ERROR",
                        status_message=safe_error_message(normalized),
                    )
                    logger.warning(
                        "llm_invoke_failed profile=%s model=%s model_attempt=%s model_retry=%s error_type=%s",
                        profile.name,
                        profile.model,
                        model_attempt,
                        model_retry,
                        normalized.__class__.__name__,
                    )
                    if isinstance(normalized, (LLMConfigurationError, LLMAuthenticationError)):
                        raise normalized from exc
                    if model_retry < attempts - 1:
                        self._sleep(0.5 * (model_retry + 1))

        detail = str(last_error) if last_error is not None else "LLM request failed"
        raise LLMUnavailableError(detail) from last_error

    def stream_text(self, messages: Any, *, allow_fallback: bool = True, **kwargs: Any) -> Iterator[str]:
        if self._execution_disabled():
            raise LLMConfigurationError("LLM execution is disabled for this deterministic run")
        last_error: Exception | None = None

        for model_attempt, profile in enumerate(self._profile_chain(allow_fallback=allow_fallback), start=1):
            self._validate_messages(messages, profile)
            metadata = self._trace_metadata(profile, model_attempt, 0, "stream", True)
            generation = start_generation(
                name="llm.stream",
                model=profile.model,
                input_data=sanitize_messages(messages),
                metadata=metadata,
                model_parameters={"max_tokens": profile.max_tokens, "stream": True},
            )
            emitted = False
            completed = False
            generation_ended = False
            chunks: list[str] = []
            response_meta: dict[str, Any] = {}
            started = time.perf_counter()
            try:
                for chunk in self._client(profile).stream(messages, **kwargs):
                    response_meta.update(provider_request_metadata(chunk))
                    text = _content_text(getattr(chunk, "content", chunk))
                    if not text:
                        continue
                    emitted = True
                    chunks.append(text)
                    yield text
                output = "".join(chunks).strip()
                if not output:
                    raise LLMEmptyResponseError(f"{profile.name}/{profile.model} returned empty stream")
                end_generation(
                    generation,
                    output=sanitize_output(output),
                    metadata={
                        **metadata,
                        **response_meta,
                        "model": profile.model,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "output_chars": len(output),
                        "chunk_count": len(chunks),
                        "emitted": emitted,
                    },
                )
                generation_ended = True
                completed = True
                return
            except GeneratorExit:
                raise
            except Exception as exc:
                normalized = exc if isinstance(exc, LLMEmptyResponseError) else normalize_provider_error(exc)
                last_error = normalized
                error_metadata = {
                    **metadata,
                    **response_meta,
                    "model": profile.model,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "chunk_count": len(chunks),
                    "emitted": emitted,
                    "partial_output": emitted,
                }
                end_generation(
                    generation,
                    output=sanitize_output("".join(chunks).strip()) if emitted else None,
                    metadata=error_metadata,
                    level="ERROR",
                    status_message=safe_error_message(normalized),
                )
                generation_ended = True
                if emitted:
                    raise LLMStreamInterruptedError("LLM stream interrupted after output was emitted") from normalized
                if isinstance(normalized, (LLMConfigurationError, LLMAuthenticationError)):
                    raise normalized from exc
            finally:
                if not completed and not generation_ended and emitted:
                    output = "".join(chunks).strip()
                    end_generation(
                        generation,
                        output=sanitize_output(output),
                        metadata={
                            **metadata,
                            **response_meta,
                            "model": profile.model,
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                            "output_chars": len(output),
                            "chunk_count": len(chunks),
                            "emitted": emitted,
                            "partial_output": True,
                        },
                        level="WARNING",
                        status_message="stream closed before completion",
                    )

        detail = str(last_error) if last_error is not None else "LLM stream request failed"
        raise LLMUnavailableError(detail) from last_error

    def stream(self, messages: Any, **kwargs: Any) -> Iterator[str]:
        """Temporary compatibility alias. New code should call stream_text()."""
        return self.stream_text(messages, **kwargs)
