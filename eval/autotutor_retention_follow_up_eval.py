"""Real Graph/Legacy -> retention publication, follow-up and failure boundaries."""
import json
import os
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

OUTPUT = os.environ.get("AUTOTUTOR_FOLLOW_UP_CASE_OUTPUT")
from autotutor_demo_graph_flow_smoke import at, app, TestClient, metadata, engine, seed, NETWORK_COUNTS
from db.engine import get_connection
from sqlalchemy import text
from agents import autotutor_content as content
from services import review_service as review
from services import review_retention as retention
from services.autotutor_follow_up import get_follow_up
from services.review_mastery_service import parse_time
from services.weakpoint_service import clear_weakpoints, record_weakpoint, get_weakpoints
from review_retention_checks import check_retention_transactions


def main():
    metadata.create_all(engine); seed(verbose=False)
    client = TestClient(app)
    def login(user):
        return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": user, "password": "pilot123"}).json()["token"]}
    from security.accounts import create_account
    create_account("unrelated-teacher", "unrelated-teacher", "pilot123", "teacher")
    unrelated = login("unrelated-teacher")
    headers, teacher, other = login("pilot-student"), login("pilot-teacher"), login("pilot-student-b")
    def complete(key, wrong_first=False):
        result = client.post("/api/autotutor/start", headers=headers, json={"student_id":"pilot-student", "focus_tags":["洋务运动目的"], "idempotency_key":key}).json()
        for index in range(5):
            if result["status"] == "completed":
                return result
            state = at._load_persisted_session(result["session_id"])
            question = state.exit_ticket.question if state.phase == "exit_ticket" else state.lesson_plan[0].question
            answer = next(a for a in "ABCD" if a != question["answer"]) if wrong_first and index == 0 else question["answer"]
            response = client.post("/api/autotutor/answer", headers=headers, json={"session_id":result["session_id"], "answer":answer, "expected_revision":result["revision"], "idempotency_key":f"{key}-answer-{index}"})
            assert response.status_code == 200, response.text
            result = response.json()
        raise AssertionError("lesson did not complete")
    def row():
        with get_connection() as conn:
            return dict(conn.execute(text("SELECT * FROM review_mastery_state WHERE student_id='pilot-student' AND knowledge_tag='洋务运动目的'")).mappings().one())
    examples = []
    for mode in ("graph_active", "legacy"):
        for level in ("easy", "medium"):
            clear_weakpoints("pilot-student")
            if level == "easy":
                for _ in range(2): record_weakpoint("pilot-student", "洋务运动目的", source="test")
            with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "true" if mode == "legacy" else "false"}):
                completed = complete(f"retention-{mode}-{level}", wrong_first=level == "easy")
            assert at._load_persisted_session(completed["session_id"]).executor_mode == mode
            assert completed["mastery"]["status"] == "verified" and completed["evidence"]["review_action"] == "retention_scheduled"
            state = row(); day = state["updated_at"][:10]; due = state["retention_due_at"]
            before = (parse_time(due)-timedelta(seconds=1)).isoformat()
            follow = get_follow_up(completed, at=before)
            assert follow["follow_up"]["status"] == "scheduled" and get_follow_up(completed, at=due)["follow_up"]["status"] == "due"
            url = f"/api/autotutor/session/{completed['session_id']}/follow-up"
            assert client.get(url).status_code == 401 and client.get(url, headers=other).status_code == 403
            assert client.get(url, headers=unrelated).status_code == 403
            public = client.get(url, headers=headers).json()
            assert client.get(url, headers=teacher).json()["follow_up"] == public["follow_up"]
            assert not any(key in json.dumps(public) for key in ("answer", "evidence_key", "question", "options"))
            assert row() == state  # read-only endpoint
            weak = get_weakpoints("pilot-student")
            session = review.create_today_session("pilot-student", day, at=due)
            safe = review.public_review_session(session)
            assert not any(t.get("task_role") == "retention" and t["tag"] == "洋务运动目的" for t in safe["tasks"])
            assert any(t["knowledge_tag"] == "洋务运动目的" for t in safe["blocked_reviews"])
            assert row()["status"] == "content_blocked" and get_weakpoints("pilot-student") == weak
            repeat = review.get_today_session("pilot-student", day, at=due)
            assert repeat["revision"] == session["revision"]
            assert get_follow_up(completed, at=due)["follow_up"]["status"] == "content_blocked"
            examples.append({"mode":mode, "difficulty":level, "immediate":"verified", "follow_up":"content_blocked"})
    print("OK real_graph_legacy_schedule_missing_content_and_readonly_authorization")
    # Negative control: the pre-fix generic fallback would release an excluded practice.
    from services.history_review_question import build_grounded_review_question
    blocked = review._generate_question("洋务运动目的", task_role="retention", excluded_assessment_ids={"westernization-purpose-exit-1"})
    assert review.is_unusable_question(blocked)
    assert not review.is_unusable_question(build_grounded_review_question("洋务运动目的", target_difficulty="medium"))
    assert client.post("/api/students/pilot-student/review/submit", headers=headers,
        json={"task_index":0,"selected_answer":"A","occurred_at":"2099-01-01T00:00:00Z"}).status_code == 422
    from services.history_review_question import build_curated_review_question
    entry_model = next(e.model_copy(deep=True) for e in content.load_curated_content() if e.entity == "洋务运动")
    original_ticket = entry_model.exit_ticket_items[0]
    entry_model.exit_ticket_items = [original_ticket.model_copy(update={"assessment_id":"renamed-identical-ticket"})]
    with content.use_content_snapshot((entry_model,)):
        assert build_curated_review_question("洋务运动目的", task_role="retention", excluded_fingerprints={content.assessment_fingerprint(original_ticket)}) is None
    print("OK role_fallback_negative_control")
    # Save the bad pre-v153 task in the real review row; publication withdraws it.
    state = row(); day=session["date"]; due=state["retention_due_at"]
    invalid = build_grounded_review_question("洋务运动目的", target_difficulty="medium")
    review._decorate_task(invalid, student_id="pilot-student",session_id=session["id"],task_role="retention",retrieval_evidence_key=state["retrieval_evidence_key"],due_at=due)
    with get_connection() as conn:
        conn.execute(text("UPDATE review_sessions SET tasks_json=:tasks, revision=revision+1 WHERE id=:id"), {"tasks":json.dumps([invalid]),"id":session["id"]})
    withdrawn = review.get_today_session("pilot-student", day, at=due)
    assert review.public_review_session(withdrawn)["total"] == 0
    print("OK historical_invalid_task_withdrawal")
    # This extra item exists ONLY in a temporary synthetic test pack.
    payload = json.loads(content.CONTENT_PATH.read_text())
    entry = next(e for e in payload["items"] if e["entity"] == "洋务运动")
    extra = json.loads(json.dumps(entry["exit_ticket_items"][0]))
    extra.update(assessment_id="synthetic-westernization-retention", stem="洋务派创办近代企业，却坚持清朝原有政治统治。这说明这些举措的根本目的是什么？", review_prompt="洋务派创办近代企业，却坚持清朝原有政治统治。这说明这些举措的根本目的是什么？")
    texts = ["借助近代技术维护清朝统治", "建立资产阶级民主共和国", "立即结束外国在华全部特权", "彻底否定封建君主统治"]
    for option, value in zip(extra["options"], texts):
        option["text"] = value
        option["is_correct"] = option["option_id"] == "A"
        option["feedback"] = "正确。洋务派利用近代技术维护清朝统治。" if option["is_correct"] else "这不符合洋务派维护清朝统治的目的。"
    entry["exit_ticket_items"].append(extra)
    with TemporaryDirectory() as folder:
        path=Path(folder)/"synthetic.json";path.write_text(json.dumps(payload))
        with patch.object(content,"CONTENT_PATH",path), patch.object(review,"CONTENT_PATH",path):
            recovered=review.get_today_session("pilot-student",day,at=due)
            index=next(i for i,t in enumerate(recovered["tasks"]) if t.get("question_id")==extra["assessment_id"])
            task=recovered["tasks"][index]
            # Content revoked after publication must not grade.
            with patch.object(retention,"role_question",return_value=None):
                try: review.submit_answer("pilot-student",day,index,task["answer"],recovered["revision"],"retention-revoked",occurred_at=due)
                except review.ReviewConflictError: pass
                else: raise AssertionError("revoked task graded")
            submitted=review.submit_answer("pilot-student",day,index,task["answer"],recovered["revision"],"retention-success",occurred_at=due)
            assert submitted["phase"]=="retention_verified"
            assert get_follow_up(completed,at=due)["follow_up"]["status"]=="retention_verified"
    print("OK synthetic_content_restore_success_and_revocation")
    newer=complete("retention-newer-chain")
    assert get_follow_up(completed)["follow_up"]["status"]=="superseded"
    assert get_follow_up(newer)["follow_up"]["status"]=="scheduled"
    print("OK follow_up_source_chain_superseded")
    check_retention_transactions()
    assert NETWORK_COUNTS["external_attempts"]==0
    if OUTPUT:
        Path(OUTPUT).write_text(json.dumps({"production_evidence":False,"examples":examples},ensure_ascii=False))

if __name__ == "__main__":
    main()
