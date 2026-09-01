"""Student-safe projection of AutoTutor runtime steps for the public demo.

This module never exposes raw trace events.  It accepts the already-sanitized
AutoTutor public state and produces a small, deterministic teaching journey.
"""
from __future__ import annotations

from typing import Any

from agents.autotutor_provenance import public_decision_provenance

_STATUS = {
    "success": "completed",
    "failed": "failed",
    "degraded": "degraded",
    "blocked": "blocked",
    "waiting_answer": "waiting",
}

_PHASES = {
    "plan": ("plan", "制定教学计划"),
    "tool_result": ("observe", "检索并核验教学依据"),
    "content_gate": ("observe", "检查教学内容是否可信"),
    "teach": ("teach", "生成针对性讲解"),
    "reteach": ("reteach", "调整讲解方式"),
    "act": ("teach", "生成有效练习"),
    "observe": ("observe", "等待学生作答"),
    "judge": ("judge", "判断作答并识别错因"),
    "reflect": ("reflect", "反思当前教学策略"),
    "re_plan": ("re_plan", "调整后续教学计划"),
    "exit_ticket": ("exit_ticket", "执行独立退出票检验"),
    "memory": ("evidence", "写入学习证据"),
}

_ADJUSTMENTS = {
    "reteach": "补讲核心概念",
    "lower_difficulty": "降低题目难度",
    "change_example": "更换讲解例子",
    "advance": "继续下一学习步骤",
}

_DECISION_SOURCES = {
    "tool_result": "tool",
    "memory": "evidence_store",
}


def _text(value: Any, *, limit: int = 80) -> str:
    return str(value or "").strip()[:limit]


def _summary(event_type: str, metadata: dict[str, Any], status: str) -> str:
    point = _text(metadata.get("knowledge_point"), limit=60)
    if event_type == "plan":
        targets = metadata.get("targeted_points")
        labels = [_text(item, limit=40) for item in targets[:2]] if isinstance(targets, list) else []
        return f"围绕{'、'.join(filter(None, labels)) or '当前薄弱点'}安排了本节目标"
    if event_type == "tool_result":
        count = max(0, int(metadata.get("source_count") or 0))
        return f"找到并检查了 {count} 条教学依据"
    if event_type == "content_gate":
        return "内容依据不足，已安全停止" if status == "blocked" else "教学内容通过可信度检查"
    if event_type in {"teach", "reteach"}:
        return f"{'换一种方式讲解' if event_type == 'reteach' else '讲解'}「{point or '当前知识点'}」"
    if event_type == "act":
        return f"围绕「{point or '当前知识点'}」生成并验证练习题"
    if event_type == "observe":
        return "题目已准备好，等待学生作答"
    if event_type == "judge":
        return "回答正确，继续完成独立检验" if metadata.get("is_correct") is True else "发现回答有误，进入反思与调整"
    if event_type == "reflect":
        return "发现当前回答存在概念混淆，需要调整讲解"
    if event_type == "re_plan":
        adjustment = _ADJUSTMENTS.get(_text(metadata.get("adjustment")), "调整教学顺序和讲解方式")
        return f"计划已调整：{adjustment}"
    if event_type == "exit_ticket":
        if metadata.get("verified_mastery") is True:
            return "退出票通过，掌握证据已验证"
        if status == "failed":
            return "退出票未通过，保留薄弱点继续复习"
        return "使用不同题目进行最后的掌握检验"
    if event_type == "memory":
        evidence = metadata.get("evidence") if isinstance(metadata.get("evidence"), dict) else {}
        return "学习证据已写入复习与教师端" if evidence.get("exit_ticket_recorded") else "已保存本节学习过程"
    return ""


def project_demo_trace(state: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, deterministic projection of one AutoTutor session."""
    projected: list[dict[str, Any]] = []
    steps = state.get("runtime_steps") if isinstance(state.get("runtime_steps"), list) else []
    for item in sorted((step for step in steps if isinstance(step, dict)), key=lambda value: int(value.get("sequence") or 0)):
        event_type = _text(item.get("event_type"), limit=40)
        mapping = _PHASES.get(event_type)
        if mapping is None:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        raw_status = _text(item.get("status"), limit=30)
        status = _STATUS.get(raw_status, "completed")
        summary = _summary(event_type, metadata, raw_status)
        if event_type == "reflect":
            provenance = public_decision_provenance(metadata.get("decision_provenance"))
        else:
            source = _DECISION_SOURCES.get(event_type, "policy")
            provenance = {
                "decision_source": source,
                "fallback_used": False,
                "structured_repair_used": False,
                "model": None,
            }
        projected.append({
            "sequence": len(projected) + 1,
            "phase": mapping[0],
            "label": mapping[1],
            "status": status,
            "summary": summary,
            "duration_ms": max(0, round(float(item["latency_ms"]), 2)) if isinstance(item.get("latency_ms"), (int, float)) else None,
            "decision_source": (provenance or {}).get("decision_source"),
            "model": (provenance or {}).get("model"),
        })
    return {
        "enabled": True,
        "session_id": _text(state.get("session_id"), limit=128),
        "status": _text(state.get("status"), limit=40),
        "events": projected[:40],
    }
