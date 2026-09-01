from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from tracing import end_span, start_span, truncate_text

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")
_FALLBACK_UNSET = object()


class StructuredOutputError(ValueError):
    pass


class StructuredInvocationProvenance(BaseModel):
    decision_source: Literal[
        "langchain_primary",
        "langchain_fallback_profile",
        "deterministic_fallback",
    ]
    provider: str | None = None
    transport: str | None = None
    configured_profile: str | None = None
    executed_profile: str | None = None
    configured_model: str | None = None
    executed_model: str | None = None
    model_attempt: int | None = None
    structured_repair_used: bool = False
    fallback_used: bool = False


@dataclass(frozen=True)
class StructuredInvocationResult(Generic[R]):
    value: R
    provenance: StructuredInvocationProvenance


def _strip_code_fence(raw: str) -> str:
    content = raw.strip()
    if not content.startswith("```"):
        return content

    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _error_type(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ValidationError):
        return "schema_validation_failed"
    message = str(exc)
    if "empty" in message:
        return "empty_output"
    if "does not contain JSON" in message:
        return "no_json"
    if "root is not" in message:
        return "wrong_root_type"
    if "does not match schema" in message:
        return "schema_validation_failed"
    return exc.__class__.__name__


def _parse_span(operation: str, raw: str, **metadata):
    return start_span(
        name="structured_output.parse",
        input_data=truncate_text(raw, max_chars=1200),
        metadata={"operation": operation, "raw_chars": len(str(raw or "")), **metadata},
    )


def extract_json_text(raw: str) -> str:
    raw_text = str(raw or "")
    span = _parse_span("extract_json_text", raw_text)
    try:
        content = _strip_code_fence(raw_text)
        if not content:
            raise StructuredOutputError("empty model output")

        try:
            json.loads(content)
            end_span(span, metadata={"operation": "extract_json_text", "success": True, "raw_chars": len(raw_text)})
            return content
        except json.JSONDecodeError:
            pass

        object_start = content.find("{")
        object_end = content.rfind("}")
        if object_start >= 0 and object_end > object_start:
            extracted = content[object_start : object_end + 1]
            end_span(span, metadata={"operation": "extract_json_text", "success": True, "raw_chars": len(raw_text)})
            return extracted

        list_start = content.find("[")
        list_end = content.rfind("]")
        if list_start >= 0 and list_end > list_start:
            extracted = content[list_start : list_end + 1]
            end_span(span, metadata={"operation": "extract_json_text", "success": True, "raw_chars": len(raw_text)})
            return extracted

        raise StructuredOutputError("model output does not contain JSON")
    except Exception as exc:
        end_span(
            span,
            metadata={"operation": "extract_json_text", "success": False, "raw_chars": len(raw_text), "error_type": _error_type(exc)},
            level="ERROR",
            status_message=str(exc),
        )
        raise


def parse_json_object(raw: str) -> dict[str, Any]:
    raw_text = str(raw or "")
    span = _parse_span("parse_json_object", raw_text, expect="object")
    try:
        try:
            payload = json.loads(extract_json_text(raw_text))
        except json.JSONDecodeError as exc:
            raise StructuredOutputError("model output is invalid JSON object") from exc
        if not isinstance(payload, dict):
            raise StructuredOutputError("model JSON root is not an object")
        end_span(span, metadata={"operation": "parse_json_object", "expect": "object", "success": True, "raw_chars": len(raw_text)})
        return payload
    except Exception as exc:
        end_span(
            span,
            metadata={"operation": "parse_json_object", "expect": "object", "success": False, "raw_chars": len(raw_text), "error_type": _error_type(exc)},
            level="ERROR",
            status_message=str(exc),
        )
        raise


def parse_json_list(raw: str) -> list[Any]:
    raw_text = str(raw or "")
    span = _parse_span("parse_json_list", raw_text, expect="list")
    try:
        try:
            payload = json.loads(extract_json_text(raw_text))
        except json.JSONDecodeError as exc:
            raise StructuredOutputError("model output is invalid JSON list") from exc
        if not isinstance(payload, list):
            raise StructuredOutputError("model JSON root is not a list")
        end_span(span, metadata={"operation": "parse_json_list", "expect": "list", "success": True, "raw_chars": len(raw_text)})
        return payload
    except Exception as exc:
        end_span(
            span,
            metadata={"operation": "parse_json_list", "expect": "list", "success": False, "raw_chars": len(raw_text), "error_type": _error_type(exc)},
            level="ERROR",
            status_message=str(exc),
        )
        raise


def validate_with_pydantic(payload: Any, model: type[T]) -> T:
    span = start_span(
        name="structured_output.validate",
        metadata={"operation": "validate_with_pydantic", "schema": model.__name__},
    )
    try:
        parsed = model.model_validate(payload)
        end_span(span, metadata={"operation": "validate_with_pydantic", "schema": model.__name__, "success": True})
        return parsed
    except ValidationError as exc:
        end_span(
            span,
            metadata={
                "operation": "validate_with_pydantic",
                "schema": model.__name__,
                "success": False,
                "error_type": _error_type(exc),
            },
            level="ERROR",
            status_message=str(exc),
        )
        raise StructuredOutputError(f"model JSON does not match schema: {model.__name__}") from exc


def parse_model(raw: str, model: type[T]) -> T:
    raw_text = str(raw or "")
    span = _parse_span("parse_model", raw_text, expect="object", schema=model.__name__)
    try:
        parsed = validate_with_pydantic(parse_json_object(raw_text), model)
        end_span(
            span,
            metadata={"operation": "parse_model", "expect": "object", "schema": model.__name__, "success": True, "raw_chars": len(raw_text)},
        )
        return parsed
    except Exception as exc:
        end_span(
            span,
            metadata={
                "operation": "parse_model",
                "expect": "object",
                "schema": model.__name__,
                "success": False,
                "raw_chars": len(raw_text),
                "error_type": _error_type(exc),
            },
            level="ERROR",
            status_message=str(exc),
        )
        raise


def _repair_json_with_llm_response(
    llm,
    raw: str,
    *,
    expect: Literal["object", "list"] = "object",
    schema_name: str | None = None,
    error: str | None = None,
) -> tuple[str, Any]:
    raw_text = str(raw or "")
    span = start_span(
        name="structured_output.repair_json",
        input_data=truncate_text(raw_text, max_chars=1200),
        metadata={"expect": expect, "schema": schema_name, "raw_chars": len(raw_text), "error": truncate_text(error, max_chars=500)},
    )
    messages = [
        {
            "role": "system",
            "content": "你只负责修复模型输出的 JSON 格式。只输出严格 JSON，不要解释。不得新增、删除或改写事实内容；不得改写年份、事件ID、人物名等事实字段。只修复引号、逗号、括号、根类型和字段类型等格式问题。",
        },
        {
            "role": "user",
            "content": f"""
期望 JSON 根类型：{expect}
Pydantic schema：{schema_name or "未指定"}
解析错误：{error or "未知"}

原始输出：
{truncate_text(raw_text, max_chars=6000)}
""".strip(),
        },
    ]
    try:
        response = llm.invoke(messages)
        repaired = str(getattr(response, "content", response))
        end_span(
            span,
            output=truncate_text(repaired, max_chars=1200),
            metadata={"expect": expect, "schema": schema_name, "success": True, "raw_chars": len(raw_text), "repaired_chars": len(repaired)},
        )
        return repaired, response
    except Exception as exc:
        end_span(
            span,
            metadata={"expect": expect, "schema": schema_name, "success": False, "raw_chars": len(raw_text), "error_type": _error_type(exc)},
            level="ERROR",
            status_message=str(exc),
        )
        raise StructuredOutputError(f"JSON repair failed: {exc}") from exc


def repair_json_with_llm(
    llm,
    raw: str,
    *,
    expect: Literal["object", "list"] = "object",
    schema_name: str | None = None,
    error: str | None = None,
) -> str:
    repaired, _response = _repair_json_with_llm_response(
        llm,
        raw,
        expect=expect,
        schema_name=schema_name,
        error=error,
    )
    return repaired


def _parse_expected(raw_text: str, expect: Literal["object", "list"], model: type[T] | None = None) -> Any:
    if model is not None:
        return parse_model(raw_text, model)
    if expect == "object":
        return parse_json_object(raw_text)
    if expect == "list":
        return parse_json_list(raw_text)
    raise StructuredOutputError(f"unsupported JSON root expectation: {expect}")


def _model_identity(llm: Any) -> tuple[str | None, str | None]:
    profile = getattr(llm, "profile", None)
    profile_name = getattr(profile, "name", None) or getattr(llm, "name", None)
    model_name = getattr(profile, "model", None) or getattr(llm, "model", None)
    return (str(profile_name) if profile_name else None, str(model_name) if model_name else None)


def _successful_provenance(
    llm: Any,
    response: Any,
    *,
    structured_repair_used: bool,
) -> StructuredInvocationProvenance:
    response_metadata = getattr(response, "response_metadata", None)
    raw = response_metadata.get("edu_agent_provenance") if isinstance(response_metadata, dict) else None
    metadata = raw if isinstance(raw, dict) else {}
    default_profile, default_model = _model_identity(llm)
    configured_profile = str(metadata.get("configured_profile") or default_profile or "") or None
    executed_profile = str(metadata.get("executed_profile") or configured_profile or "") or None
    configured_model = str(metadata.get("configured_model") or default_model or "") or None
    executed_model = str(metadata.get("executed_model") or configured_model or "") or None
    raw_attempt = metadata.get("model_attempt")
    model_attempt = int(raw_attempt) if isinstance(raw_attempt, int) and raw_attempt > 0 else 1
    used_fallback_profile = model_attempt > 1 or (
        bool(configured_profile and executed_profile) and configured_profile != executed_profile
    )
    return StructuredInvocationProvenance(
        decision_source="langchain_fallback_profile" if used_fallback_profile else "langchain_primary",
        provider=str(metadata.get("provider") or "") or None,
        transport=str(metadata.get("transport") or "") or None,
        configured_profile=configured_profile,
        executed_profile=executed_profile,
        configured_model=configured_model,
        executed_model=executed_model,
        model_attempt=model_attempt,
        structured_repair_used=structured_repair_used,
        fallback_used=used_fallback_profile,
    )


def _deterministic_provenance(llm: Any, *, structured_repair_used: bool) -> StructuredInvocationProvenance:
    configured_profile, configured_model = _model_identity(llm)
    return StructuredInvocationProvenance(
        decision_source="deterministic_fallback",
        configured_profile=configured_profile,
        configured_model=configured_model,
        structured_repair_used=structured_repair_used,
        fallback_used=True,
    )


def invoke_structured_with_provenance(
    llm,
    messages: list[dict[str, str]],
    *,
    expect: Literal["object", "list"] = "object",
    model: type[T] | None = None,
    fallback: Any = _FALLBACK_UNSET,
    repair: bool = True,
) -> StructuredInvocationResult[Any]:
    schema_name = model.__name__ if model is not None else None
    span = start_span(name="structured_output.invoke_structured", metadata={"expect": expect, "schema": schema_name, "repair": repair})
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        if fallback is not _FALLBACK_UNSET:
            end_span(
                span,
                metadata={
                    "expect": expect,
                    "schema": schema_name,
                    "success": False,
                    "fallback_used": True,
                    "repair_attempted": False,
                    "repair_success": False,
                    "raw_chars": 0,
                    "error_type": _error_type(exc),
                },
                level="WARNING",
                status_message=str(exc),
            )
            return StructuredInvocationResult(
                value=fallback,
                provenance=_deterministic_provenance(llm, structured_repair_used=False),
            )
        end_span(
            span,
            metadata={
                "expect": expect,
                "schema": schema_name,
                "success": False,
                "fallback_used": False,
                "repair_attempted": False,
                "repair_success": False,
                "raw_chars": 0,
                "error_type": _error_type(exc),
            },
            level="ERROR",
            status_message=str(exc),
        )
        raise
    raw = getattr(response, "content", response)
    raw_text = str(raw)
    repair_attempted = False
    try:
        try:
            result = _parse_expected(raw_text, expect, model)
            end_span(
                span,
                metadata={
                    "expect": expect,
                    "schema": schema_name,
                    "success": True,
                    "fallback_used": False,
                    "repair_attempted": False,
                    "repair_success": False,
                    "raw_chars": len(raw_text),
                },
            )
            return StructuredInvocationResult(
                value=result,
                provenance=_successful_provenance(llm, response, structured_repair_used=False),
            )
        except StructuredOutputError as first_exc:
            if not repair:
                raise
            repair_attempted = True
            repaired_text, repair_response = _repair_json_with_llm_response(
                llm,
                raw_text,
                expect=expect,
                schema_name=schema_name,
                error=str(first_exc),
            )
            result = _parse_expected(repaired_text, expect, model)
            end_span(
                span,
                metadata={
                    "expect": expect,
                    "schema": schema_name,
                    "success": True,
                    "fallback_used": False,
                    "repair_attempted": True,
                    "repair_success": True,
                    "raw_chars": len(raw_text),
                    "repaired_chars": len(repaired_text),
                },
            )
            return StructuredInvocationResult(
                value=result,
                provenance=_successful_provenance(llm, repair_response, structured_repair_used=True),
            )
    except StructuredOutputError as exc:
        if fallback is not _FALLBACK_UNSET:
            end_span(
                span,
                metadata={
                    "expect": expect,
                    "schema": schema_name,
                    "success": False,
                    "fallback_used": True,
                    "repair_attempted": repair_attempted,
                    "repair_success": False,
                    "raw_chars": len(raw_text),
                    "error_type": _error_type(exc),
                },
                level="WARNING",
                status_message=str(exc),
            )
            return StructuredInvocationResult(
                value=fallback,
                provenance=_deterministic_provenance(llm, structured_repair_used=repair_attempted),
            )
        end_span(
            span,
            metadata={
                "expect": expect,
                "schema": schema_name,
                "success": False,
                "fallback_used": False,
                "repair_attempted": repair_attempted,
                "repair_success": False,
                "raw_chars": len(raw_text),
                "error_type": _error_type(exc),
            },
            level="ERROR",
            status_message=str(exc),
        )
        raise


def invoke_structured(
    llm,
    messages: list[dict[str, str]],
    *,
    expect: Literal["object", "list"] = "object",
    model: type[T] | None = None,
    fallback: Any = _FALLBACK_UNSET,
    repair: bool = True,
) -> Any:
    return invoke_structured_with_provenance(
        llm,
        messages,
        expect=expect,
        model=model,
        fallback=fallback,
        repair=repair,
    ).value


def invoke_json(
    llm,
    messages: list[dict[str, str]],
    *,
    expect: Literal["object", "list"] = "object",
    model: type[T] | None = None,
    fallback: Any = _FALLBACK_UNSET,
) -> Any:
    return invoke_structured(llm, messages, expect=expect, model=model, fallback=fallback, repair=True)
