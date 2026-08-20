from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-essay-runtime-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)

import agents.essay_grader as essay  # noqa: E402


class Response:
    def __init__(self, content: str):
        self.content = content


class CriticModel:
    def __init__(self, answers: list[str]):
        self.answers = list(answers)

    def invoke(self, _prompt):
        return Response(self.answers.pop(0))


def payload(score: int) -> essay.EssayGradePayload:
    return essay.EssayGradePayload(liyi=score, jiegou=15, yuyan=20, shuxie=10, cailiao=10, pingjia="具体评语")


async def run_graph(critic_answers: list[str]):
    original_llm = essay.llm
    original_structured = essay.invoke_structured
    generated = [payload(10), payload(12)]
    essay.llm = CriticModel(critic_answers)
    essay.invoke_structured = lambda *_args, **_kwargs: generated.pop(0) if generated else payload(12)
    try:
        graph = essay.build_grader_graph()
        return await graph.ainvoke({
            "essay": "测试作文",
            "student_id": "student-a",
            "run_id": "run-essay-test",
            "draft_score": {},
            "draft_comments": "",
            "final_score": {},
            "final_comments": "",
            "revision_count": 0,
            "critique_approved": False,
            "needs_human_review": False,
            "review_reason": None,
        })
    finally:
        essay.llm = original_llm
        essay.invoke_structured = original_structured


def main() -> None:
    revised = asyncio.run(run_graph(["语言评分需修正", "APPROVED"]))
    assert revised["revision_count"] == 1, revised
    assert revised["completion_status"] == "completed"
    assert revised["final_score"]["total_score"] == sum(revised["final_score"][key] for key in ("liyi", "jiegou", "yuyan", "shuxie", "cailiao"))
    waiting = asyncio.run(run_graph(["仍不公正", "仍需教师判断"]))
    assert waiting["revision_count"] == 1
    assert waiting["needs_human_review"] is True
    assert waiting["completion_status"] == "waiting_input"
    assert waiting["final_score"] == {}
    print("essay_grader_runtime_smoke=PASS")


if __name__ == "__main__":
    main()
