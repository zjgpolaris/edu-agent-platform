"""作文批量批改服务"""
import asyncio
from typing import Any

from agents.essay_grader import build_grader_graph, EssayState

MAX_CONCURRENT_GRADING = 3


async def grade_single(essay: str, student_name: str) -> dict[str, Any]:
    graph = build_grader_graph()
    state: EssayState = {
        "essay": essay,
        "draft_score": {},
        "draft_comments": "",
        "final_score": {},
        "final_comments": "",
        "revision_count": 0,
        "critique_approved": False,
        "needs_human_review": False,
        "review_reason": None,
    }
    result = await graph.ainvoke(state)
    return {
        "student_name": student_name,
        "final_comments": result.get("final_comments", ""),
        "needs_human_review": result.get("needs_human_review", False),
        "review_reason": result.get("review_reason"),
        "failed": False,
    }


async def grade_single_safe(essay: str, student_name: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    async with semaphore:
        try:
            if not student_name.strip() or not essay.strip():
                raise ValueError("学生姓名和作文内容不能为空")
            return await grade_single(essay, student_name)
        except Exception as exc:
            return {
                "student_name": student_name or "未命名学生",
                "final_comments": "",
                "needs_human_review": True,
                "review_reason": "批改失败，需教师人工处理",
                "failed": True,
                "error": str(exc) or "批改失败",
            }


async def batch_grade(essays: list[dict[str, str]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_GRADING)
    tasks = [
        grade_single_safe(str(e.get("essay", "")), str(e.get("student_name", "")), semaphore)
        for e in essays
    ]
    return await asyncio.gather(*tasks)


_SCORE_DIMS = ["立意", "结构", "语言", "书写风格", "材料运用"]


def _parse_total_score(comments: str) -> float | None:
    import json, re
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", comments.strip(), flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
    except Exception:
        return None
    scores = [float(obj[k]) for dim in _SCORE_DIMS for k in obj if k.startswith(dim) and _safe_float(obj[k]) is not None]
    return sum(scores) if scores else None


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"avg_score": 0, "score_distribution": {}, "needs_review_count": 0, "failed_count": 0}
    failed = sum(1 for r in results if r.get("failed"))
    needs_review = sum(1 for r in results if r.get("needs_human_review"))
    automatic = len(results) - needs_review
    scores = [s for r in results if not r.get("failed") and (s := _parse_total_score(r.get("final_comments", ""))) is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    return {
        "avg_score": avg_score,
        "score_distribution": {"需复核": needs_review, "自动通过": automatic, "批改失败": failed},
        "needs_review_count": needs_review,
        "failed_count": failed,
    }
