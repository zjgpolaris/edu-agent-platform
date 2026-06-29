"""作文批改 Agent — Reflection (Critic-Reviser) 模式"""
from __future__ import annotations

import json

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field
from typing import TypedDict

from llm_config import llm_quality as llm
from security.audit_log import record_audit_event
from structured_output import invoke_structured


class EssayGradePayload(BaseModel):
    liyi: int = Field(default=0, ge=0, le=20, description="立意得分")
    jiegou: int = Field(default=0, ge=0, le=20, description="结构得分")
    yuyan: int = Field(default=0, ge=0, le=30, description="语言得分")
    shuxie: int = Field(default=0, ge=0, le=15, description="书写风格得分")
    cailiao: int = Field(default=0, ge=0, le=15, description="材料运用得分")
    pingjia: str = Field(default="", description="总体评语")

    def to_comments_json(self) -> str:
        return json.dumps({
            "立意(20)": self.liyi,
            "结构(20)": self.jiegou,
            "语言(30)": self.yuyan,
            "书写风格(15)": self.shuxie,
            "材料运用(15)": self.cailiao,
            "总体评语": self.pingjia,
        }, ensure_ascii=False)


class EssayState(TypedDict):
    essay: str
    student_id: str | None
    draft_score: dict
    draft_comments: str
    final_score: dict
    final_comments: str
    revision_count: int
    critique_approved: bool
    needs_human_review: bool
    review_reason: str | None


_GRADER_MESSAGES = lambda essay: [
    {"role": "system", "content": "你是高中语文教师。只输出严格 JSON。"},
    {"role": "user", "content": (
        "请批改以下作文，输出 JSON 对象，字段：\n"
        "liyi(0-20), jiegou(0-20), yuyan(0-30), shuxie(0-15), cailiao(0-15), pingjia(总体评语)\n\n"
        f"作文：{essay}"
    )},
]

CRITIC_PROMPT = (
    "请审核以下作文批改结果是否公正、是否遗漏重要问题：\n{comments}\n"
    "如无问题，回复 APPROVED。否则说明具体问题（勿重新输出完整JSON）。"
)


def grade(state: EssayState) -> EssayState:
    result = invoke_structured(
        llm,
        _GRADER_MESSAGES(state["essay"]),
        model=EssayGradePayload,
        fallback=EssayGradePayload(),
    )
    record_audit_event(
        actor_id=state.get("student_id"),
        action="essay_grader.grade",
        resource_type="essay",
        success=True,
        metadata={"essay_length": len(state["essay"])},
    )
    return {"draft_comments": result.to_comments_json(), "revision_count": 0, "critique_approved": False}


def critique(state: EssayState) -> EssayState:
    resp = llm.invoke(CRITIC_PROMPT.format(comments=state["draft_comments"]))
    approved = "APPROVED" in resp.content
    needs_review = not approved or state["revision_count"] >= 1
    record_audit_event(
        actor_id=state.get("student_id"),
        action="essay_grader.critique",
        resource_type="essay",
        success=True,
        metadata={"approved": approved, "revision_count": state["revision_count"] + 1},
    )
    return {
        "final_comments": state["draft_comments"],   # always valid JSON
        "revision_count": state["revision_count"] + 1,
        "critique_approved": approved,
        "needs_human_review": needs_review,
        "review_reason": (resp.content[:300] if not approved else None),
    }


def should_finalize(state: EssayState) -> str:
    if state.get("final_comments") or state["revision_count"] >= 2:
        return "done"
    return "critique"


def build_grader_graph() -> StateGraph:
    g = StateGraph(EssayState)
    g.add_node("grade", grade)
    g.add_node("critique", critique)
    g.set_entry_point("grade")
    g.add_edge("grade", "critique")
    g.add_conditional_edges("critique", should_finalize, {"done": END, "critique": "critique"})
    return g.compile()
