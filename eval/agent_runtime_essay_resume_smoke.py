from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_temp_dir = tempfile.TemporaryDirectory(prefix="edu-agent-runtime-essay-resume-")
os.environ["EDU_AGENT_DB_PATH"] = str(Path(_temp_dir.name) / "runtime.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EDU_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_PERCENT_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ESSAY_GRADER_BPS"] = "10000"
os.environ["EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_CHECKPOINT_ENABLED"] = "true"
os.environ["EDU_AGENT_RUNTIME_V2_RESUMABLE_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
import agents.essay_grader as essay  # noqa: E402
from agent_runtime.artifact_store import list_run_artifacts  # noqa: E402
from agent_runtime.checkpoint_store import latest_checkpoint  # noqa: E402
from agent_runtime.event_store import get_run, list_run_events  # noqa: E402
from api.main import app  # noqa: E402


class FakeGraph:
    async def ainvoke(self, _state):
        return {
            "draft_score": {"liyi": 15, "jiegou": 15, "yuyan": 20, "shuxie": 10, "cailiao": 10, "total_score": 70},
            "draft_comments": "需教师判断立意边界",
            "final_score": {},
            "final_comments": "",
            "revision_count": 1,
            "needs_human_review": True,
            "review_reason": "critic_disagreement",
        }


def main() -> None:
    original = essay.build_grader_graph
    essay.build_grader_graph = lambda: FakeGraph()
    body = "这是一篇只应出现在受控 artifact 中的测试作文。"
    try:
        with TestClient(app) as client:
            graded = client.post("/api/chinese/essay/grade", json={"essay": body, "student_id": "student-essay-runtime"})
            assert graded.status_code == 200, graded.text
            payload = graded.json()
            assert payload["completion_status"] == "waiting_input"
            assert payload["review_resume_enabled"] is True
            run = get_run(payload["run_id"])
            assert run["status"] == "waiting_input"
            checkpoint = latest_checkpoint(run["run_id"])
            assert checkpoint and checkpoint["revision"] == run["revision"]
            assert body not in " ".join(str(event.data) for event in list_run_events(run["run_id"]))
            artifacts = list_run_artifacts(run["run_id"], actor_id="dev-teacher", actor_role="teacher")
            assert any((item.get("content") or {}).get("essay") == body for item in artifacts)

            reviewed = client.post("/api/chinese/essay/review-result", json={
                "session_id": run["run_id"],
                "approved": True,
                "decision": "approved",
                "teacher_comments": "教师确认通过",
                "expected_revision": run["revision"],
            })
            assert reviewed.status_code == 200, reviewed.text
            assert get_run(run["run_id"])["status"] == "completed"
    finally:
        essay.build_grader_graph = original

    print("agent_runtime_essay_resume_smoke=PASS")


if __name__ == "__main__":
    main()
