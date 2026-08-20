from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from security.audit_log import record_audit_event
from tracing import current_trace_id, end_span, safe_error_message, start_span, truncate_text
from tools.base import ToolError, ToolExecutionContext, ToolResult, ToolSpec
from tools.character_tools import RecommendCharacterInput, recommend_character
from tools.game_tools import StartTimelineGameInput, start_timeline_game
from tools.history_search import SearchHistoryKnowledgeInput, search_history_knowledge
from tools.profile_tools import (
    DeleteDemoMemoryInput,
    GetStudentProfileInput,
    RecordLearningEventInput,
    SuggestReviewPlanInput,
    delete_demo_memory,
    get_student_profile,
    record_learning_event,
    suggest_review_plan,
)
from tools.quiz_tools import GenerateQuizInput, generate_quiz
from tools.textbook_tools import GetTextbookLessonInput, get_textbook_lesson

CONFIRMATION_TTL_SECONDS = 300
ROLE_RANK = {"anonymous": 0, "student": 1, "teacher": 2, "admin": 3}

TOOLS: dict[str, ToolSpec] = {
    "search_history_knowledge": ToolSpec(
        name="search_history_knowledge",
        description="检索历史知识库并返回带分数的史料来源。",
        input_model=SearchHistoryKnowledgeInput,
        handler=search_history_knowledge,
        risk_level="low",
        side_effect="read",
        required_role="anonymous",
        timeout_seconds=15,
    ),
    "get_textbook_lesson": ToolSpec(
        name="get_textbook_lesson",
        description="读取指定教材课文的结构化知识点。",
        input_model=GetTextbookLessonInput,
        handler=get_textbook_lesson,
        risk_level="low",
        side_effect="read",
        required_role="anonymous",
    ),
    "generate_quiz": ToolSpec(
        name="generate_quiz",
        description="基于指定教材课文生成自测题。",
        input_model=GenerateQuizInput,
        handler=generate_quiz,
        risk_level="low",
        side_effect="external_call",
        required_role="anonymous",
        timeout_seconds=20,
    ),
    "recommend_character": ToolSpec(
        name="recommend_character",
        description="根据学习问题推荐适合对话的历史人物。",
        input_model=RecommendCharacterInput,
        handler=recommend_character,
        risk_level="low",
        side_effect="external_call",
        required_role="anonymous",
        timeout_seconds=20,
    ),
    "start_timeline_game": ToolSpec(
        name="start_timeline_game",
        description="启动一局历史时间线排序游戏。",
        input_model=StartTimelineGameInput,
        handler=start_timeline_game,
        risk_level="medium",
        side_effect="session_create",
        required_role="student",
        timeout_seconds=20,
    ),
    "get_student_profile": ToolSpec(
        name="get_student_profile",
        description="读取学生长期学习画像。",
        input_model=GetStudentProfileInput,
        handler=get_student_profile,
        risk_level="medium",
        side_effect="read",
        required_role="student",
        audit_enabled=True,
    ),
    "record_learning_event": ToolSpec(
        name="record_learning_event",
        description="记录一条学生学习事件并更新画像。",
        input_model=RecordLearningEventInput,
        handler=record_learning_event,
        risk_level="medium",
        side_effect="write",
        required_role="student",
        audit_enabled=True,
    ),
    "suggest_review_plan": ToolSpec(
        name="suggest_review_plan",
        description="根据学生画像生成复习建议。",
        input_model=SuggestReviewPlanInput,
        handler=suggest_review_plan,
        risk_level="medium",
        side_effect="read",
        required_role="student",
        audit_enabled=True,
    ),
    "delete_demo_memory": ToolSpec(
        name="delete_demo_memory",
        description="删除一条演示学习记忆，用于展示高风险工具确认流程。",
        input_model=DeleteDemoMemoryInput,
        handler=delete_demo_memory,
        risk_level="high",
        side_effect="write",
        required_role="student",
        requires_confirmation=True,
        audit_enabled=True,
    ),
}


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_model.model_json_schema(),
            "output_schema": spec.output_model.model_json_schema() if spec.output_model else None,
            "risk_level": spec.risk_level,
            "side_effect": spec.side_effect,
            "required_role": spec.required_role,
            "requires_confirmation": spec.requires_confirmation,
            "timeout_seconds": spec.timeout_seconds,
            "audit_enabled": spec.audit_enabled,
        }
        for spec in TOOLS.values()
    ]


def _tool_policy_metadata(spec: ToolSpec) -> dict[str, Any]:
    return {
        "risk_level": spec.risk_level,
        "side_effect": spec.side_effect,
        "required_role": spec.required_role,
        "requires_confirmation": spec.requires_confirmation,
        "audit_enabled": spec.audit_enabled,
    }


def _context_metadata(context: ToolExecutionContext) -> dict[str, Any]:
    return {
        "actor_role": context.role,
        "actor_id": context.actor_id,
        "student_id": context.student_id,
        "request_source": context.request_source,
        "confirmed": context.confirmed,
        "run_id": context.run_id,
        "step_id": context.step_id,
        "run_revision": context.run_revision,
        "idempotency_key": context.idempotency_key,
        "capability_operation": context.capability_operation,
        "data_scope": context.data_scope,
    }


def _result_metadata(spec: ToolSpec | None, context: ToolExecutionContext | None, duration_ms: float | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if spec:
        metadata.update(_tool_policy_metadata(spec))
    if context:
        metadata.update(_context_metadata(context))
    trace_id = current_trace_id()
    if trace_id:
        metadata["trace_id"] = trace_id
    if duration_ms is not None:
        metadata["duration_ms"] = round(duration_ms, 2)
    metadata.update(extra or {})
    return metadata


def _tool_error(
    tool_name: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    duration_ms: float | None = None,
    spec: ToolSpec | None = None,
    context: ToolExecutionContext | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        ok=False,
        error=ToolError(code=code, message=message, retryable=retryable),
        metadata=_result_metadata(spec, context, duration_ms, extra_metadata),
    )


def _confirmation_secret() -> bytes:
    return (os.getenv("JWT_SECRET") or os.getenv("EDU_AGENT_CONFIRMATION_SECRET") or "edu-agent-dev-secret").encode("utf-8")


def _confirmation_body(
    tool_name: str,
    payload: dict[str, Any],
    actor_id: str | None,
    issued_at: int,
    *,
    run_id: str | None = None,
    step_id: str | None = None,
    run_revision: int | None = None,
) -> dict[str, Any]:
    body = {"tool_name": tool_name, "payload": payload, "actor_id": actor_id, "issued_at": issued_at}
    if run_id is not None or step_id is not None or run_revision is not None:
        if not run_id or not step_id or run_revision is None:
            raise ValueError("v2 confirmation requires run_id, step_id and run_revision")
        body.update({"token_version": 2, "run_id": run_id, "step_id": step_id, "run_revision": run_revision})
    return body


def _sign_confirmation_body(body: dict[str, Any]) -> str:
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(_confirmation_secret(), raw, hashlib.sha256).hexdigest()


def _encode_token(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "confirm_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_token(token: str) -> dict[str, Any] | None:
    if not token.startswith("confirm_"):
        return None
    raw = token.removeprefix("confirm_")
    raw += "=" * (-len(raw) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception:
        return None


def _make_confirmation_token(tool_name: str, payload: dict[str, Any], context: ToolExecutionContext) -> str:
    issued_at = int(time.time())
    body = _confirmation_body(
        tool_name,
        payload,
        context.actor_id,
        issued_at,
        run_id=context.run_id,
        step_id=context.step_id,
        run_revision=context.run_revision,
    )
    return _encode_token({"body": body, "signature": _sign_confirmation_body(body)})


def issue_runtime_confirmation_token(
    tool_name: str,
    payload: dict[str, Any],
    context: ToolExecutionContext,
) -> str:
    """Issue a v2 token only for a registered high-risk capability input."""
    spec = TOOLS.get(tool_name)
    if spec is None:
        raise LookupError("tool not found")
    if not (spec.requires_confirmation or spec.risk_level == "high"):
        raise ValueError("tool does not require confirmation")
    validated_payload = spec.input_model.model_validate(payload).model_dump()
    if not context.run_id or not context.step_id or context.run_revision is None:
        raise ValueError("runtime confirmation requires run, step and revision")
    return _make_confirmation_token(tool_name, validated_payload, context)


def _verify_confirmation_token(token: str | None, tool_name: str, payload: dict[str, Any], context: ToolExecutionContext) -> bool:
    if not token:
        return False
    decoded = _decode_token(token)
    if not decoded:
        return False
    body = decoded.get("body")
    signature = decoded.get("signature")
    if not isinstance(body, dict) or not isinstance(signature, str):
        return False
    issued_at = body.get("issued_at")
    if not isinstance(issued_at, int) or time.time() - issued_at > CONFIRMATION_TTL_SECONDS:
        return False
    try:
        expected_body = _confirmation_body(
            tool_name,
            payload,
            context.actor_id,
            issued_at,
            run_id=context.run_id,
            step_id=context.step_id,
            run_revision=context.run_revision,
        )
    except ValueError:
        return False
    if body != expected_body:
        return False
    return hmac.compare_digest(signature, _sign_confirmation_body(body))


def _should_audit(spec: ToolSpec) -> bool:
    return spec.audit_enabled or spec.risk_level in {"medium", "high"}


def _audit_tool(action: str, tool_name: str, spec: ToolSpec, context: ToolExecutionContext, *, success: bool = True, metadata: dict[str, Any] | None = None) -> None:
    if not _should_audit(spec) and action == "tool.allowed":
        return
    record_audit_event(
        actor_id=context.actor_id,
        action=action,
        resource_type="tool",
        resource_id=tool_name,
        success=success,
        data_scope=context.data_scope,
        metadata={"tool_name": tool_name, **_tool_policy_metadata(spec), **_context_metadata(context), **(metadata or {})},
    )


def _has_required_role(context: ToolExecutionContext, spec: ToolSpec) -> bool:
    return ROLE_RANK.get(context.role, 0) >= ROLE_RANK.get(spec.required_role, 0)


def _mark_claim_unknown(context: ToolExecutionContext, claim: Any, *, error_type: str) -> None:
    if not claim or not claim.acquired or not context.run_id or not context.idempotency_key:
        return
    try:
        from agent_runtime.side_effect_store import get_side_effect, mark_side_effect_unknown

        current = get_side_effect(context.run_id, context.idempotency_key)
        if current and current.get("status") == "started":
            mark_side_effect_unknown(
                context.run_id,
                context.idempotency_key,
                {"code": "handler_or_commit_exception", "type": error_type},
            )
    except Exception:
        # Never replace the governed tool error with a secondary ledger error.
        pass


def run_tool(tool_name: str, payload: dict[str, Any], context: ToolExecutionContext | None = None) -> ToolResult:
    started_at = perf_counter()
    context = context or ToolExecutionContext()
    spec = TOOLS.get(tool_name)
    if spec is None:
        return _tool_error(tool_name, "tool_not_found", "未找到可用工具。", context=context)

    span = start_span(
        name="tool.execute",
        input_data={"tool_name": tool_name, "payload": payload},
        metadata={
            "tool_name": tool_name,
            "input_schema": spec.input_model.__name__,
            **_tool_policy_metadata(spec),
            **_context_metadata(context),
        },
    )
    validated_payload: dict[str, Any] = {}
    side_effect_claim = None
    try:
        validated = spec.input_model.model_validate(payload)
        validated_payload = validated.model_dump()
        if not _has_required_role(context, spec):
            duration_ms = (perf_counter() - started_at) * 1000
            result = _tool_error(
                tool_name,
                "role_denied",
                "当前身份无权执行该工具。",
                duration_ms=duration_ms,
                spec=spec,
                context=context,
            )
            _audit_tool("tool.role_denied", tool_name, spec, context, success=False, metadata={"duration_ms": round(duration_ms, 2), "input_summary": validated_payload})
            end_span(span, output={"ok": False, "error": "role_denied"}, metadata={"tool_name": tool_name, "success": False, "duration_ms": round(duration_ms, 2), **_tool_policy_metadata(spec), **_context_metadata(context)}, level="WARNING", status_message="role_denied")
            return result

        needs_confirmation = spec.requires_confirmation or spec.risk_level == "high"
        if needs_confirmation and not context.confirmed:
            duration_ms = (perf_counter() - started_at) * 1000
            try:
                token = _make_confirmation_token(tool_name, validated_payload, context)
            except ValueError:
                duration_ms = (perf_counter() - started_at) * 1000
                return _tool_error(
                    tool_name,
                    "invalid_runtime_confirmation_context",
                    "高风险 Run 确认缺少 step/revision 绑定。",
                    duration_ms=duration_ms,
                    spec=spec,
                    context=context,
                )
            result = _tool_error(
                tool_name,
                "confirmation_required",
                "该工具会执行高风险操作，需要用户确认。",
                duration_ms=duration_ms,
                spec=spec,
                context=context,
                extra_metadata={"confirmation_token": token, "confirmation_expires_in_seconds": CONFIRMATION_TTL_SECONDS},
            )
            _audit_tool("tool.confirmation_required", tool_name, spec, context, success=False, metadata={"duration_ms": round(duration_ms, 2), "input_summary": validated_payload, "payload": validated_payload})
            end_span(span, output={"ok": False, "error": "confirmation_required"}, metadata={"tool_name": tool_name, "success": False, "duration_ms": round(duration_ms, 2), **_tool_policy_metadata(spec), **_context_metadata(context)}, level="WARNING", status_message="confirmation_required")
            return result

        if needs_confirmation and context.confirmed:
            if not _verify_confirmation_token(context.confirmation_token, tool_name, validated_payload, context):
                duration_ms = (perf_counter() - started_at) * 1000
                result = _tool_error(
                    tool_name,
                    "invalid_confirmation",
                    "确认凭证无效或已过期。",
                    duration_ms=duration_ms,
                    spec=spec,
                    context=context,
                )
                _audit_tool("tool.denied", tool_name, spec, context, success=False, metadata={"reason": "invalid_confirmation", "duration_ms": round(duration_ms, 2), "input_summary": validated_payload})
                end_span(span, output={"ok": False, "error": "invalid_confirmation"}, metadata={"tool_name": tool_name, "success": False, "duration_ms": round(duration_ms, 2), **_tool_policy_metadata(spec), **_context_metadata(context)}, level="WARNING", status_message="invalid_confirmation")
                return result
            _audit_tool("tool.confirmation_confirmed", tool_name, spec, context, metadata={"confirmed_tool_name": tool_name, "input_summary": validated_payload})

        if context.run_id and spec.side_effect in {"write", "session_create"}:
            from agent_runtime.side_effect_store import claim_side_effect

            if not context.step_id or not context.idempotency_key:
                duration_ms = (perf_counter() - started_at) * 1000
                result = _tool_error(
                    tool_name,
                    "missing_side_effect_idempotency",
                    "Runtime 副作用步骤缺少 step 或幂等键。",
                    duration_ms=duration_ms,
                    spec=spec,
                    context=context,
                )
                _audit_tool("tool.denied", tool_name, spec, context, success=False, metadata={"reason": "missing_side_effect_idempotency"})
                end_span(span, output={"ok": False, "error": "missing_side_effect_idempotency"}, metadata={"tool_name": tool_name, "success": False, **_tool_policy_metadata(spec), **_context_metadata(context)}, level="WARNING", status_message="missing_side_effect_idempotency")
                return result
            side_effect_claim = claim_side_effect(
                run_id=context.run_id,
                step_id=context.step_id,
                operation=context.capability_operation or tool_name,
                idempotency_key=context.idempotency_key,
                input_payload=validated_payload,
            )
            if side_effect_claim.replayable:
                stored = side_effect_claim.record.get("result")
                if not isinstance(stored, dict):
                    return _tool_error(
                        tool_name,
                        "side_effect_replay_missing_result",
                        "已执行的副作用缺少可重放结果。",
                        spec=spec,
                        context=context,
                    )
                result = ToolResult.model_validate(stored)
                result.metadata = {**result.metadata, **_result_metadata(spec, context), "idempotent_replay": True}
                _audit_tool("tool.idempotent_replay", tool_name, spec, context, success=result.ok)
                end_span(span, output={"ok": result.ok, "idempotent_replay": True}, metadata={"tool_name": tool_name, "success": result.ok, "idempotent_replay": True, **_tool_policy_metadata(spec), **_context_metadata(context)})
                return result
            if not side_effect_claim.acquired:
                status = str(side_effect_claim.record.get("status") or "unknown")
                error_code = "side_effect_in_progress" if status == "started" else "side_effect_outcome_unknown"
                result = _tool_error(
                    tool_name,
                    error_code,
                    "副作用仍在执行中。" if status == "started" else "副作用结果不确定，禁止自动重试。",
                    retryable=False,
                    spec=spec,
                    context=context,
                )
                _audit_tool("tool.denied", tool_name, spec, context, success=False, metadata={"reason": error_code})
                end_span(span, output={"ok": False, "error": error_code}, metadata={"tool_name": tool_name, "success": False, **_tool_policy_metadata(spec), **_context_metadata(context)}, level="WARNING", status_message=error_code)
                return result

        try:
            result = spec.handler(validated)
        except Exception as exc:
            _mark_claim_unknown(context, side_effect_claim, error_type=type(exc).__name__)
            raise
        duration_ms = (perf_counter() - started_at) * 1000
        result.metadata = {**_result_metadata(spec, context, duration_ms), **result.metadata}
        if side_effect_claim and side_effect_claim.acquired and context.run_id and context.idempotency_key:
            from agent_runtime.side_effect_store import commit_side_effect, fail_side_effect

            if result.ok:
                commit_side_effect(context.run_id, context.idempotency_key, result.model_dump())
            else:
                fail_side_effect(context.run_id, context.idempotency_key, result.model_dump())
        if result.ok:
            _audit_tool("tool.allowed", tool_name, spec, context, metadata={"duration_ms": round(duration_ms, 2), "input_summary": validated_payload})
        else:
            _audit_tool("tool.failed", tool_name, spec, context, success=False, metadata={"duration_ms": round(duration_ms, 2), "error_code": result.error.code if result.error else None, "input_summary": validated_payload})
        end_span(
            span,
            output={"ok": result.ok, "metadata": result.metadata},
            metadata={"tool_name": tool_name, "success": result.ok, "duration_ms": round(duration_ms, 2), **_tool_policy_metadata(spec), **_context_metadata(context)},
        )
        return result
    except ValidationError as exc:
        duration_ms = (perf_counter() - started_at) * 1000
        message = truncate_text(str(exc), max_chars=360)
        result = _tool_error(tool_name, "invalid_input", message, duration_ms=duration_ms, spec=spec, context=context)
        _audit_tool("tool.failed", tool_name, spec, context, success=False, metadata={"error_code": "invalid_input", "duration_ms": round(duration_ms, 2)})
        end_span(
            span,
            metadata={"tool_name": tool_name, "success": False, **_tool_policy_metadata(spec), **_context_metadata(context), "error_type": "ValidationError", "duration_ms": round(duration_ms, 2)},
            level="WARNING",
            status_message=message,
        )
        return result
    except LookupError as exc:
        _mark_claim_unknown(context, side_effect_claim, error_type=type(exc).__name__)
        duration_ms = (perf_counter() - started_at) * 1000
        message = safe_error_message(exc)
        result = _tool_error(tool_name, "not_found", message, duration_ms=duration_ms, spec=spec, context=context)
        _audit_tool("tool.failed", tool_name, spec, context, success=False, metadata={"error_code": "not_found", "duration_ms": round(duration_ms, 2), "input_summary": validated_payload})
        end_span(
            span,
            metadata={"tool_name": tool_name, "success": False, **_tool_policy_metadata(spec), **_context_metadata(context), "error_type": type(exc).__name__, "duration_ms": round(duration_ms, 2)},
            level="WARNING",
            status_message=message,
        )
        return result
    except ValueError as exc:
        _mark_claim_unknown(context, side_effect_claim, error_type=type(exc).__name__)
        duration_ms = (perf_counter() - started_at) * 1000
        message = safe_error_message(exc)
        result = _tool_error(tool_name, "invalid_request", message, duration_ms=duration_ms, spec=spec, context=context)
        _audit_tool("tool.failed", tool_name, spec, context, success=False, metadata={"error_code": "invalid_request", "duration_ms": round(duration_ms, 2), "input_summary": validated_payload})
        end_span(
            span,
            metadata={"tool_name": tool_name, "success": False, **_tool_policy_metadata(spec), **_context_metadata(context), "error_type": type(exc).__name__, "duration_ms": round(duration_ms, 2)},
            level="WARNING",
            status_message=message,
        )
        return result
    except Exception as exc:
        _mark_claim_unknown(context, side_effect_claim, error_type=type(exc).__name__)
        duration_ms = (perf_counter() - started_at) * 1000
        message = safe_error_message(exc)
        result = _tool_error(tool_name, "tool_failed", message or "工具执行失败。", retryable=True, duration_ms=duration_ms, spec=spec, context=context)
        _audit_tool("tool.failed", tool_name, spec, context, success=False, metadata={"error_code": "tool_failed", "duration_ms": round(duration_ms, 2), "input_summary": validated_payload})
        end_span(
            span,
            metadata={"tool_name": tool_name, "success": False, **_tool_policy_metadata(spec), **_context_metadata(context), "error_type": type(exc).__name__, "duration_ms": round(duration_ms, 2)},
            level="ERROR",
            status_message=message,
        )
        return result
