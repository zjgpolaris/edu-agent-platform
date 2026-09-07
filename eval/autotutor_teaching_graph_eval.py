"""Real offline Graph teaching contracts; export only allowlisted synthetic facts."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

# Capture the explicit destination before the shared fixture clears the parent env.
OUTPUT = os.environ.get("AUTOTUTOR_REVIEW_CASE_OUTPUT")
from autotutor_demo_graph_flow_smoke import (  # shared isolated DB/ASGI/Graph fixture
    at, app, TestClient, metadata, engine, seed, get_connection, text, NETWORK_COUNTS,
)

POINT = "戊戌变法失败原因"


def check(condition, boundary, expected, actual):
    if not condition:
        raise AssertionError(json.dumps({"boundary": boundary, "expected": expected, "actual": actual}, ensure_ascii=False))


def assert_reteach(before, after, execution):
    explanation = after.teaching["explanation"]
    check(explanation != before.teaching["explanation"] and explanation.startswith("先纠正刚才的混淆："),
          "reteach", "targeted correction before reviewed explanation", explanation)
    correction = explanation.split("：", 1)[1].split(" 戊戌变法", 1)[0]
    # Independent reviewed expectations; never derive the oracle from model/output feedback.
    expected = {"wuxu-cause-practice-1": ("顽固派阻挠", "维新派自身力量不足"),
                "wuxu-cause-practice-2": ("变法为什么难以持续",),
                "wuxu-cause-practice-3": ("力量基础薄弱", "顽固派反击")}[before.question["assessment_id"]]
    check(all(fact in correction for fact in expected), "reteach", list(expected), correction)
    check(all(word in explanation for word in ("顽固派", "力量弱小", "影响", "原因")),
          "reteach", "cause facts and cause/impact distinction", explanation)
    check(after.objective.objective_id == before.objective.objective_id, "reteach", "same objective", after.objective.aspect)
    check(after.question["assessment_id"] != before.question["assessment_id"] and after.question["question"] != before.question["question"],
          "assessment_selection", "fresh question", after.question["assessment_id"])
    check(execution["selected_executor"] == "graph_active" and {"reflect", "re_plan", "reteach"} <= set(execution["visited_nodes"]),
          "reteach", "real Graph remediation", execution)


def assert_verification(state, teacher, passed):
    check(state["status"] == "completed" and state["exit_ticket_result"]["is_correct"] is passed,
          "exit_ticket", passed, state.get("status"))
    check((state["mastery"]["status"] == "verified") is passed,
          "exit_ticket", "verified" if passed else "not verified", state["mastery"]["status"])
    check(teacher["exit_ticket"]["passed"] is passed and teacher["exit_ticket"]["recorded"] and
          (teacher["mastery"]["status"] == "verified") is passed and teacher["execution"] == state["execution"],
          "evidence_consistency", "teacher matches persisted learning result", teacher["mastery"])


def main():
    metadata.create_all(engine)
    seed(verbose=False)
    client = TestClient(app)
    def login(name):
        response = client.post("/api/auth/login", json={"username": name, "password": "pilot123"})
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["token"]}
    headers, teacher_headers = login("pilot-student"), login("pilot-teacher")

    def start(key):
        response = client.post("/api/autotutor/start", headers=headers, json={"student_id": "pilot-student", "focus_tags": [POINT], "idempotency_key": key})
        check(response.status_code == 200, "test_harness", 200, response.status_code)
        return response.json()

    def internal(state):
        return at._load_persisted_session(state["session_id"])

    def answer(state, value):
        body = {"session_id": state["session_id"], "answer": value, "expected_revision": state["revision"], "idempotency_key": f'teaching-{state["revision"]}'}
        response = client.post("/api/autotutor/answer", headers=headers, json=body)
        check(response.status_code == 200, "test_harness", 200, response.status_code)
        result = response.json()
        check(result["revision"] == state["revision"] + 1, "evidence_consistency", state["revision"] + 1, result["revision"])
        # Compare all relevant side effects across same-key replay, including review memory.
        def effects():
            with get_connection() as conn:
                return [list(conn.execute(text(sql)).fetchall()) for sql in (
                    "SELECT * FROM learning_events ORDER BY id", "SELECT * FROM weakpoints ORDER BY student_id,knowledge_tag",
                    "SELECT * FROM weakpoint_evidence ORDER BY evidence_key", "SELECT * FROM memory_entries ORDER BY id",
                    "SELECT * FROM review_mastery_state ORDER BY student_id,knowledge_tag")]
        saved = effects()
        replay = client.post("/api/autotutor/answer", headers=headers, json=body)
        check(replay.status_code == 200 and replay.json()["revision"] == result["revision"] and effects() == saved,
              "evidence_consistency", "replay has zero new effects", replay.status_code)
        restored = client.get(f'/api/autotutor/session/{state["session_id"]}', headers=headers).json()
        check(restored["execution"] == result["execution"], "evidence_consistency", "same persisted revision", restored.get("revision"))
        return result

    def wrong(state, misconception=None):
        stored = internal(state)
        q = stored.exit_ticket.question if stored.phase == "exit_ticket" else stored.lesson_plan[stored.current_step_index].question
        assessment = at._assessment_from_question(q)
        return next(o.option_id for o in assessment.options if not o.is_correct and (misconception is None or o.misconception_code == misconception))

    examples = []
    results = []
    def run(name, action):
        try:
            action()
            results.append({"case_id": name, "status": "pass"})
            print("OK " + name)
        except Exception as exc:
            results.append({"case_id": name, "status": "fail"})
            print("FAIL " + name)
            try:
                detail = json.loads(str(exc))
            except (ValueError, TypeError):
                detail = {"boundary": "test_harness", "expected": "completed scenario", "actual": type(exc).__name__}
            print("FAILED_CASE_DETAIL=" + json.dumps({"name": name, **detail}, ensure_ascii=False))

    def remediation():
        state = start("teaching-remediation")
        before = internal(state).lesson_plan[0].model_copy(deep=True)
        state = answer(state, wrong(state, "cause_impact_confusion"))
        after = internal(state).lesson_plan[0]
        check(bool(state.get("reflection")) and state["replans"] == 1, "misconception_feedback", "reflection and replan", state["replans"])
        feedback = state["answer_feedback"]
        check(feedback["misconception_code"] == "cause_impact_confusion" and feedback["is_correct"] is False and "影响" in feedback["message"],
              "misconception_feedback", "cause/impact diagnosis for selected wrong option", feedback["misconception_code"])
        assert_reteach(before, after, state["execution"])
        restored = client.get(f'/api/autotutor/session/{state["session_id"]}', headers=headers).json()
        check(restored["current_question"]["teaching"]["explanation"] == after.teaching["explanation"], "evidence_consistency", "persisted corrected teaching", "current teaching")
        # Negative control: removing the correction must break the same oracle.
        damaged = after.model_copy(deep=True)
        damaged.teaching = before.teaching
        try:
            assert_reteach(before, damaged, state["execution"])
        except AssertionError:
            pass
        else:
            raise AssertionError("correction negative control accepted")
        examples.append({"scenario": "misconception_reteach", "objective": POINT,
                         "misconception": "cause_impact_confusion", "before": before.teaching["explanation"],
                         "after": after.teaching["explanation"], "execution": state["execution"]})
        return state

    def repeated():
        state = start("teaching-repeated")
        order = {"easy": 0, "medium": 1, "hard": 2}
        for _ in range(2):
            before = internal(state).lesson_plan[0].model_copy(deep=True)
            state = answer(state, wrong(state, "cause_impact_confusion"))
            after = internal(state).lesson_plan[0]
            assert_reteach(before, after, state["execution"])
            check(order[after.difficulty] <= order[before.difficulty] and after.attempts == before.attempts + 1,
                  "reteach", "bounded difficulty and attempts", after.difficulty)
        check(state["replans"] == 2, "reteach", 2, state["replans"])

    def finish(passed):
        state = remediation() if passed else start("teaching-exit-wrong")
        practice_ids, practice_stems = set(), set()
        for _ in range(30):
            stored = internal(state)
            if stored.phase == "exit_ticket":
                break
            step = stored.lesson_plan[stored.current_step_index]
            practice_ids.add(step.question["assessment_id"])
            practice_stems.add(step.question["question"])
            state = answer(state, step.question["answer"])
        stored = internal(state)
        check(stored.phase == "exit_ticket" and state["mastery"]["status"] != "verified", "exit_ticket", "independent verification pending", stored.phase)
        ticket = stored.exit_ticket.question
        check(ticket["assessment_id"] not in practice_ids and ticket["question"] not in practice_stems,
              "exit_ticket", "independent id and stem", ticket["assessment_id"])
        state = answer(state, ticket["answer"] if passed else wrong(state))
        response = client.get(f'/api/autotutor/session/{state["session_id"]}/evidence', headers=teacher_headers)
        check(response.status_code == 200, "evidence_consistency", 200, response.status_code)
        teacher = response.json()
        assert_verification(state, teacher, passed)
        with get_connection() as conn:
            rows = conn.execute(text("SELECT success FROM learning_events WHERE session_id=:sid AND event_type='auto_tutor_exit_ticket'"), {"sid": state["session_id"]}).fetchall()
        check(len(rows) == 1 and bool(rows[0][0]) is passed, "evidence_consistency", "one matching exit event", len(rows))
        if not passed:
            check(teacher["evidence"]["weakpoint_action"] == "weakpoint_recorded", "evidence_consistency", "weakpoint_recorded", teacher["evidence"]["weakpoint_action"])
            from services.weakpoint_service import get_weakpoints
            check(any(w["knowledge_tag"] == POINT for w in get_weakpoints("pilot-student")), "evidence_consistency", "weakpoint exists", False)
            from student_profile import list_memory_entries
            check(any(m.type == "review_goal" and isinstance(m.content, dict) and m.content.get("session_id") == state["session_id"] and (m.content.get("exit_ticket") or {}).get("is_correct") is False and POINT not in m.content.get("mastered", []) for m in list_memory_entries("pilot-student", limit=100)), "evidence_consistency", "session review goal records failed verification without mastery", False)
            damaged = copy.deepcopy(state)
            damaged["mastery"]["status"] = "verified"
            try:
                assert_verification(damaged, teacher, False)
            except AssertionError:
                pass
            else:
                raise AssertionError("mastery negative control accepted")
        examples.append({"scenario": "exit_correct" if passed else "exit_wrong", "objective": POINT,
                         "passed": teacher["exit_ticket"]["passed"], "mastery": teacher["mastery"]["status"],
                         "weakpoint_action": teacher["evidence"]["weakpoint_action"], "execution": teacher["execution"]})

    run("misconception_reteach_and_exit_correct", lambda: finish(True))
    run("repeated_wrong_targeted_reteach", repeated)
    run("exit_wrong_teacher_review_consistency", lambda: finish(False))
    # Negative control proves that passing {} in place of polluted data is caught.
    def polluted_negative():
        import autotutor_teaching_quality_eval as quality
        case = next(c for c in json.loads(quality.DATASET.read_text()) if c["scenario"] == "polluted_source")
        original = quality.prepare_content
        with patch.object(quality, "prepare_content", side_effect=lambda objective, data, **kw: original(objective, {}, **kw)):
            check(not quality.evaluate_case(case)[0], "test_harness", "bypassed pollution rejected", True)
    run("pollution_boundary_negative_control", polluted_negative)
    check(NETWORK_COUNTS["external_attempts"] == 0, "test_harness", 0, NETWORK_COUNTS["external_attempts"])
    if OUTPUT:
        Path(OUTPUT).write_text(json.dumps({"schema_version": 1, "production_evidence": False,
            "input_mode": "deterministic_fixture", "results": results, "examples": examples,
            "network": {"scope": "autotutor_teaching_graph_eval process", "external_attempts": NETWORK_COUNTS["external_attempts"]}}, ensure_ascii=False, indent=2) + "\n")
    if any(r["status"] != "pass" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
