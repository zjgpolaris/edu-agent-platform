"""统一 LLM 配置。"""
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tracing import end_generation, safe_error_message, sanitize_messages, sanitize_output, start_generation


logger = logging.getLogger(__name__)


def _mask_secret(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 10:
        return f"set(len={len(value)})"
    return f"{value[:6]}...{value[-4:]}(len={len(value)})"


@dataclass
class LLMResponse:
    content: str


class ZodeChatModel:
    def __init__(
        self,
        model: str,
        max_tokens: int = 1024,
        fallback_models: list[str] | None = None,
        name: str | None = None,
        allow_cross_provider_fallback: bool = True,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.fallback_models = fallback_models or []
        self.name = name or model
        self.allow_cross_provider_fallback = allow_cross_provider_fallback
        self.helper_path = Path(__file__).parent / "zode_client.js"

    @staticmethod
    def _execution_disabled() -> bool:
        return os.getenv("EDU_AGENT_LLM_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}

    def _provider_model_chain(self) -> list[tuple[str, str]]:
        chain = [(LLM_PROVIDER, model) for model in [self.model, *self.fallback_models]]
        if self.allow_cross_provider_fallback and LLM_PROVIDER in {"bailian", "dashscope"} and ANTHROPIC_AUTH_TOKEN:
            chain.extend(("anthropic", model) for model in [ANTHROPIC_MODEL_QUALITY, ANTHROPIC_MODEL_FAST, ANTHROPIC_MODEL_FALLBACK])
        return list(dict.fromkeys(chain))

    def _provider_available(self, provider: str) -> bool:
        if self._execution_disabled():
            return False
        if provider == "anthropic":
            return bool(os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY"))
        if provider in {"bailian", "dashscope"}:
            return bool(os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
        return True

    def _trace_metadata(self, provider: str, model: str, attempt_index: int, operation: str, stream: bool) -> dict[str, Any]:
        return {
            "provider": provider,
            "llm_name": self.name,
            "configured_model": self.model,
            "attempt_model": model,
            "attempt_index": attempt_index,
            "fallback_models": self.fallback_models,
            "max_tokens": self.max_tokens,
            "stream": stream,
            "transport": "zode_client.js",
            "operation": operation,
        }

    def invoke(self, messages: Any, max_retries: int = 2) -> LLMResponse:
        import time
        if self._execution_disabled():
            raise RuntimeError("LLM execution is disabled for this deterministic run")
        last_error = None
        for attempt_index, (provider, model) in enumerate(self._provider_model_chain(), start=1):
            if not self._provider_available(provider):
                last_error = RuntimeError(f"{provider} credentials are not configured")
                logger.info("llm_invoke_provider_unavailable provider=%s model=%s reason=%s", provider, model, last_error)
                continue
            metadata = self._trace_metadata(provider, model, attempt_index, "invoke", False)
            for retry in range(max_retries):
                generation = start_generation(
                    name="llm.invoke",
                    model=model,
                    input_data=sanitize_messages(messages),
                    metadata={**metadata, "retry": retry},
                    model_parameters={"max_tokens": self.max_tokens, "stream": False},
                )
                try:
                    logger.info(
                        "llm_invoke_attempt provider=%s model=%s max_tokens=%s retry=%s",
                        provider, model, self.max_tokens, retry,
                    )
                    content = self._invoke_model(provider, model, messages)
                    stripped = content.strip()
                    if stripped:
                        logger.info("llm_invoke_success provider=%s model=%s chars=%s", provider, model, len(content))
                        end_generation(generation, output=sanitize_output(stripped), metadata={**metadata, "output_chars": len(stripped)})
                        return LLMResponse(content=stripped)
                    last_error = RuntimeError(f"{provider}/{model} returned empty content")
                    logger.warning("llm_invoke_empty provider=%s model=%s", provider, model)
                    end_generation(generation, metadata={**metadata, "output_chars": 0}, level="WARNING", status_message=str(last_error))
                    break  # empty response — skip retries, try next model
                except Exception as exc:
                    last_error = exc
                    logger.warning("llm_invoke_failed provider=%s model=%s retry=%s reason=%s", provider, model, retry, exc)
                    end_generation(generation, metadata=metadata, level="ERROR", status_message=safe_error_message(exc))
                    if retry < max_retries - 1:
                        time.sleep(0.5 * (retry + 1))
        raise RuntimeError(str(last_error) if last_error else "LLM request failed")

    def stream(self, messages: Any) -> Iterator[str]:
        if self._execution_disabled():
            raise RuntimeError("LLM execution is disabled for this deterministic run")
        last_error = None
        for attempt_index, (provider, model) in enumerate(self._provider_model_chain(), start=1):
            if not self._provider_available(provider):
                last_error = RuntimeError(f"{provider} credentials are not configured")
                logger.info("llm_stream_provider_unavailable provider=%s model=%s reason=%s", provider, model, last_error)
                continue
            emitted = False
            completed = False
            generation_ended = False
            chunks: list[str] = []
            metadata = self._trace_metadata(provider, model, attempt_index, "stream", True)
            generation = start_generation(
                name="llm.stream",
                model=model,
                input_data=sanitize_messages(messages),
                metadata=metadata,
                model_parameters={"max_tokens": self.max_tokens, "stream": True},
            )
            try:
                logger.info(
                    "llm_stream_attempt provider=%s model=%s max_tokens=%s",
                    provider,
                    model,
                    self.max_tokens,
                )
                for chunk in self._stream_model(provider, model, messages):
                    emitted = True
                    chunks.append(chunk)
                    yield chunk
                output = "".join(chunks).strip()
                end_generation(
                    generation,
                    output=sanitize_output(output),
                    metadata={
                        **metadata,
                        "output_chars": len(output),
                        "chunk_count": len(chunks),
                        "emitted": emitted,
                    },
                )
                generation_ended = True
                completed = True
                logger.info("llm_stream_success provider=%s model=%s emitted=%s", provider, model, emitted)
                return
            except Exception as exc:
                error_metadata = {
                    **metadata,
                    "chunk_count": len(chunks),
                    "emitted": emitted,
                    "partial_output": emitted,
                }
                end_generation(
                    generation,
                    output=sanitize_output("".join(chunks).strip()) if emitted else None,
                    metadata=error_metadata,
                    level="ERROR",
                    status_message=safe_error_message(exc),
                )
                generation_ended = True
                if emitted:
                    logger.warning("llm_stream_failed_after_emit provider=%s model=%s reason=%s", provider, model, exc)
                    raise
                last_error = exc
                logger.warning("llm_stream_failed provider=%s model=%s reason=%s", provider, model, exc)
            finally:
                if not completed and not generation_ended and emitted:
                    output = "".join(chunks).strip()
                    end_generation(
                        generation,
                        output=sanitize_output(output),
                        metadata={
                            **metadata,
                            "output_chars": len(output),
                            "chunk_count": len(chunks),
                            "emitted": emitted,
                            "partial_output": True,
                        },
                        level="WARNING",
                        status_message="stream closed before completion",
                    )
        raise RuntimeError(str(last_error) if last_error else "LLM stream request failed")

    def _build_payload(self, model: str, messages: Any, stream: bool = False) -> dict[str, Any]:
        system = None
        anthropic_messages = []

        if isinstance(messages, str):
            anthropic_messages = [{"role": "user", "content": messages}]
        else:
            for message in messages:
                role = message.get("role")
                content = message.get("content", "")
                if role == "system":
                    system = content
                elif role in {"user", "assistant"}:
                    anthropic_messages.append({"role": role, "content": content})

        return {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": anthropic_messages,
            "stream": stream,
        }

    def _invoke_model(self, provider: str, model: str, messages: Any) -> str:
        payload = self._build_payload(model, messages)
        env = os.environ.copy()
        env["LLM_PROVIDER"] = provider
        result = subprocess.run(
            ["node", str(self.helper_path), json.dumps(payload, ensure_ascii=False)],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"{model} request failed")
        return result.stdout

    def _stream_model(self, provider: str, model: str, messages: Any) -> Iterator[str]:
        payload = self._build_payload(model, messages, stream=True)
        env = os.environ.copy()
        env["LLM_PROVIDER"] = provider
        process = subprocess.Popen(
            ["node", str(self.helper_path), json.dumps(payload, ensure_ascii=False)],
            cwd=Path(__file__).parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        try:
            for line in process.stdout:
                record = json.loads(line)
                if record.get("type") == "delta" and record.get("text"):
                    yield record["text"]
                elif record.get("type") == "done":
                    break
        finally:
            returncode = process.wait(timeout=10)

        if returncode != 0:
            error = process.stderr.read().strip()
            raise RuntimeError(error or f"{model} stream request failed")


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
ANTHROPIC_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL_FAST = os.getenv("ANTHROPIC_MODEL_FAST", "kimi-k2.5")
ANTHROPIC_MODEL_QUALITY = os.getenv("ANTHROPIC_MODEL_QUALITY", "kimi-k2.6")
ANTHROPIC_MODEL_FALLBACK = os.getenv("ANTHROPIC_MODEL_FALLBACK", "GLM-5.1")
ANTHROPIC_MODEL_REASONING = os.getenv("ANTHROPIC_MODEL_REASONING", "gpt-5.4")

if LLM_PROVIDER in {"bailian", "dashscope"}:
    # Keep the default chain on models covered by the Bailian free-quota plan.
    # Explicit snapshots make eval runs reproducible instead of silently
    # changing behavior when an alias is advanced by the provider.
    DEFAULT_MODEL_FAST = "qwen3.6-35b-a3b"
    DEFAULT_MODEL_QUALITY = "qwen3.7-plus"
    DEFAULT_MODEL_FALLBACK = "qwen3.7-max-2026-06-08"
    DEFAULT_MODEL_REASONING = "qwen3.7-max-2026-06-08"
else:
    DEFAULT_MODEL_FAST = ANTHROPIC_MODEL_FAST
    DEFAULT_MODEL_QUALITY = ANTHROPIC_MODEL_QUALITY
    DEFAULT_MODEL_FALLBACK = ANTHROPIC_MODEL_FALLBACK
    DEFAULT_MODEL_REASONING = ANTHROPIC_MODEL_REASONING

def _model_env(name: str, default: str) -> str:
    """空字符串/未设都回退到默认，避免平台残留空变量覆盖默认模型名。"""
    value = (os.getenv(name) or "").strip()
    return value or default


MODEL_FAST = _model_env("LLM_MODEL_FAST", DEFAULT_MODEL_FAST)
MODEL_QUALITY = _model_env("LLM_MODEL_QUALITY", DEFAULT_MODEL_QUALITY)
MODEL_FALLBACK = _model_env("LLM_MODEL_FALLBACK", DEFAULT_MODEL_FALLBACK)
MODEL_REASONING = _model_env("LLM_MODEL_REASONING", DEFAULT_MODEL_REASONING)
MODEL_MULTIMODAL = _model_env("LLM_MODEL_MULTIMODAL", "qwen3.5-omni-flash")
MODEL_MULTIMODAL_QUALITY = _model_env("LLM_MODEL_MULTIMODAL_QUALITY", "qwen3.5-omni-plus")

logger.info(
    "llm_config_loaded provider=%s fast=%s quality=%s fallback=%s reasoning=%s multimodal=%s multimodal_quality=%s bailian_base_url=%s bailian_key=%s anthropic_base_url=%s anthropic_key=%s",
    LLM_PROVIDER,
    MODEL_FAST,
    MODEL_QUALITY,
    MODEL_FALLBACK,
    MODEL_REASONING,
    MODEL_MULTIMODAL,
    MODEL_MULTIMODAL_QUALITY,
    _mask_secret(os.getenv("BAILIAN_BASE_URL", "set")),
    _mask_secret(os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")),
    _mask_secret(os.getenv("ANTHROPIC_BASE_URL", "set")),
    _mask_secret(os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")),
)

llm_fast = ZodeChatModel(MODEL_FAST, max_tokens=1024, fallback_models=[MODEL_FALLBACK], name="llm_fast")
llm_quality = ZodeChatModel(MODEL_QUALITY, max_tokens=2048, fallback_models=[MODEL_FAST, MODEL_FALLBACK], name="llm_quality")
llm_reasoning = ZodeChatModel(MODEL_REASONING, max_tokens=2048, fallback_models=[MODEL_QUALITY, MODEL_FAST], name="llm_reasoning")
llm_multimodal = ZodeChatModel(MODEL_MULTIMODAL, max_tokens=4096, fallback_models=[], name="llm_multimodal", allow_cross_provider_fallback=False)
llm_multimodal_quality = ZodeChatModel(MODEL_MULTIMODAL_QUALITY, max_tokens=4096, fallback_models=[], name="llm_multimodal_quality", allow_cross_provider_fallback=False)
