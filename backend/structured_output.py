from __future__ import annotations

import json
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from tracing import end_span, start_span, truncate_text

T = TypeVar("T", bound=BaseModel)
_FALLBACK_UNSET = object()


class StructuredOutputError(ValueError):
    pass


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


def repair_json_with_llm(
    llm,
    raw: str,
    *,
    expect: Literal["object", "list"] = "object",
    schema_name: str | None = None,
    error: str | None = None,
) -> str:
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
        return repaired
    except Exception as exc:
        end_span(
            span,
            metadata={"expect": expect, "schema": schema_name, "success": False, "raw_chars": len(raw_text), "error_type": _error_type(exc)},
            level="ERROR",
            status_message=str(exc),
        )
        raise StructuredOutputError(f"JSON repair failed: {exc}") from exc


def _parse_expected(raw_text: str, expect: Literal["object", "list"], model: type[T] | None = None) -> Any:
    if model is not None:
        return parse_model(raw_text, model)
    if expect == "object":
        return parse_json_object(raw_text)
    if expect == "list":
        return parse_json_list(raw_text)
    raise StructuredOutputError(f"unsupported JSON root expectation: {expect}")


def invoke_structured(
    llm,
    messages: list[dict[str, str]],
    *,
    expect: Literal["object", "list"] = "object",
    model: type[T] | None = None,
    fallback: Any = _FALLBACK_UNSET,
    repair: bool = True,
) -> Any:
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
            return fallback
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
            return result
        except StructuredOutputError as first_exc:
            if not repair:
                raise
            repair_attempted = True
            repaired_text = repair_json_with_llm(llm, raw_text, expect=expect, schema_name=schema_name, error=str(first_exc))
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
            return result
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
            return fallback
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


def invoke_json(
    llm,
    messages: list[dict[str, str]],
    *,
    expect: Literal["object", "list"] = "object",
    model: type[T] | None = None,
    fallback: Any = _FALLBACK_UNSET,
) -> Any:
    return invoke_structured(llm, messages, expect=expect, model=model, fallback=fallback, repair=True)
