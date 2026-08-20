"""作文批改固定子图：grade → critic → revise once → human review/finalize。"""
from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, model_validator

from llm_config import llm_quality as llm
from security.audit_log import record_audit_event
from structured_output import invoke_structured


class EssayGradePayload(BaseModel):
    liyi: int = Field(default=0, ge=0, le=20, description="立意得分")
    jiegou: int = Field(default=0, ge=0, le=20, description="结构得分")
    yuyan: int = Field(default=0, ge=0, le=30, description="语言得分")
    shuxie: int = Field(default=0, ge=0, le=15, description="书写风格得分")
    cailiao: int = Field(default=0, ge=0, le=15, description="材料运用得分")
    total_score: int = Field(default=0, ge=0, le=100, description="分项得分之和")
    pingjia: str = Field(default="", max_length=2000, description="总体评语")

    @model_validator(mode="after")
    def compute_total(self) -> "EssayGradePayload":
        self.total_score = self.liyi + self.jiegou + self.yuyan + self.shuxie + self.cailiao
        return self

    def to_score_dict(self) -> dict[str, int]:
        return {
            "liyi": self.liyi,
            "jiegou": self.jiegou,
            "yuyan": self.yuyan,
            "shuxie": self.shuxie,
            "cailiao": self.cailiao,
            "total_score": self.total_score,
        }

    def to_comments_json(self) -> str:
        return json.dumps({
            "立意(20)": self.liyi,
            "结构(20)": self.jiegou,
            "语言(30)": self.yuyan,
            "书写风格(15)": self.shuxie,
            "材料运用(15)": self.cailiao,
            "总分(100)": self.total_score,
            "总体评语": self.pingjia,
        }, ensure_ascii=False)


class EssayState(TypedDict, total=False):
    essay: str
    student_id: str | None
    run_id: str | None
    draft_score: dict
    draft_comments: str
    final_score: dict
    final_comments: str
    revision_count: int
    critique_approved: bool
    needs_human_review: bool
    review_reason: str | None
    completion_status: str


def _grader_messages(essay: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是高中语文教师。只输出严格 JSON，不复述作文原文。"},
        {"role": "user", "content": (
            "请批改以下作文，输出 JSON 对象，字段：\n"
            "liyi(0-20), jiegou(0-20), yuyan(0-30), shuxie(0-15), "
            "cailiao(0-15), total_score(分项之和), pingjia(总体评语)\n\n"
            f"作文：{essay}"
        )},
    ]


CRITIC_PROMPT = (
    "请审核以下作文批改结果是否满足分项范围、总分一致、公平且评语具体：\n{comments}\n"
    "如无问题，只回复 APPROVED；否则说明一个最需要修正的问题，不要复述作文。"
)


def grade(state: EssayState) -> EssayState:
    result = invoke_structured(
        llm,
        _grader_messages(state["essay"]),
        model=EssayGradePayload,
        fallback=EssayGradePayload(pingjia="模型暂不可用，建议进入教师复核。"),
    )
    record_audit_event(
        actor_id=state.get("student_id"),
        action="essay_grader.grade",
        resource_type="essay",
        resource_id=state.get("run_id"),
        success=True,
        metadata={"essay_length": len(state["essay"]), "total_score": result.total_score},
    )
    return {
        "draft_score": result.to_score_dict(),
        "draft_comments": result.to_comments_json(),
        "revision_count": 0,
        "critique_approved": False,
        "needs_human_review": False,
        "review_reason": None,
    }


def critique(state: EssayState) -> EssayState:
    try:
        response = llm.invoke(CRITIC_PROMPT.format(comments=state["draft_comments"]))
        critic_text = str(response.content or "").strip()
        approved = critic_text == "APPROVED" or critic_text.startswith("APPROVED")
        reason = None if approved else (critic_text[:300] or "critic_empty_response")
    except Exception as exc:
        approved = False
        reason = f"critic_exception:{exc.__class__.__name__}"
    record_audit_event(
        actor_id=state.get("student_id"),
        action="essay_grader.critique",
        resource_type="essay",
        resource_id=state.get("run_id"),
        success=approved,
        metadata={"approved": approved, "revision_count": state.get("revision_count", 0)},
    )
    return {"critique_approved": approved, "review_reason": reason}


def revise(state: EssayState) -> EssayState:
    current_comments = json.loads(state.get("draft_comments") or "{}")
    current = EssayGradePayload.model_validate({
        **state.get("draft_score", {}),
        "pingjia": current_comments.get("总体评语", ""),
    })
    prompt = [
        {"role": "system", "content": "你是作文评分修订者。只输出严格 JSON，不复述作文原文。"},
        {"role": "user", "content": (
            f"审核问题：{state.get('review_reason') or '评分需复核'}\n"
            f"当前评分：{state.get('draft_comments', '')}\n"
            "结合原作文进行一次最小修订。字段和范围与原评分相同，总分必须等于分项之和。\n"
            f"作文：{state['essay']}"
        )},
    ]
    revised = invoke_structured(llm, prompt, model=EssayGradePayload, fallback=current)
    revision_count = int(state.get("revision_count", 0)) + 1
    record_audit_event(
        actor_id=state.get("student_id"),
        action="essay_grader.revise",
        resource_type="essay",
        resource_id=state.get("run_id"),
        metadata={"revision_count": revision_count, "total_score": revised.total_score},
    )
    return {
        "draft_score": revised.to_score_dict(),
        "draft_comments": revised.to_comments_json(),
        "revision_count": revision_count,
        "critique_approved": False,
    }


def mark_human_review(state: EssayState) -> EssayState:
    return {
        "needs_human_review": True,
        "completion_status": "waiting_input",
        "final_score": {},
        "final_comments": "",
    }


def finalize(state: EssayState) -> EssayState:
    return {
        "final_score": dict(state["draft_score"]),
        "final_comments": state["draft_comments"],
        "needs_human_review": False,
        "review_reason": None,
        "completion_status": "completed",
    }


def route_after_critic(state: EssayState) -> str:
    if state.get("critique_approved"):
        return "finalize"
    if int(state.get("revision_count", 0)) < 1:
        return "revise"
    return "human_review"


def build_grader_graph():
    graph = StateGraph(EssayState)
    graph.add_node("grade", grade)
    graph.add_node("critic", critique)
    graph.add_node("revise", revise)
    graph.add_node("human_review", mark_human_review)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("grade")
    graph.add_edge("grade", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {"finalize": "finalize", "revise": "revise", "human_review": "human_review"},
    )
    graph.add_edge("revise", "critic")
    graph.add_edge("human_review", END)
    graph.add_edge("finalize", END)
    return graph.compile()
