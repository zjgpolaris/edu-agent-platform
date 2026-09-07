"""Capabilities and real API planning, isolated from all external services."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

OUTPUT = os.environ.get("AUTOTUTOR_PLANNING_CASE_OUTPUT")
from autotutor_demo_graph_flow_smoke import at, app, TestClient, metadata, engine, seed, NETWORK_COUNTS
from agents import autotutor_catalog as catalog
from agents import autotutor_content as content
from services.weakpoint_service import clear_weakpoints, record_weakpoint, get_weakpoints


def expect_selection(result, explicit=False):
    assert result[0] == ("甲午战争影响" if explicit else "洋务运动目的"), "selected wrong target"
    assert result[2]["launchable"] is (not explicit)


def main():
    examples = []
    weak = [{"knowledge_tag": "甲午战争影响", "wrong_count": 5}, {"knowledge_tag": "洋务运动目的", "wrong_count": 2}]
    auto = catalog.choose(weak, [], [], grade="八年级上册")
    explicit = catalog.choose(weak, [], [], focus="甲午战争影响")
    expect_selection(auto)
    expect_selection(explicit, True)
    for bad, mode in ((explicit, False), (auto, True)):
        try:
            expect_selection(bad, mode)
        except AssertionError:
            pass
        else:
            raise AssertionError("selection negative control accepted")
    assert auto[2]["skipped_count"] == 1
    assert not catalog.choose(weak, [], [], grade="七年级上册")[2]["launchable"]
    assert not catalog.choose([], [], [], grade="七年级上册")[2]["launchable"]
    assert catalog.choose([], [], [], grade="八年级")[2]["launchable"]
    assert catalog.targets("unknown")["items"] == [] and catalog.targets("")["items"] == []
    assert len(catalog.targets("七年级上册")["items"]) == 1
    assert not catalog.choose([weak[0]] * 50 + [weak[1]], [], [])[2]["launchable"]
    print("OK catalog_priority_explicit_grade_boundaries_and_negative_controls")

    entries = content.load_curated_content()
    western = next(e.model_copy(deep=True) for e in entries if e.entity == "洋务运动")
    original = western.model_copy(deep=True)
    western.exit_ticket_items = []
    missing = catalog.Catalog((western,), "test")
    assert not missing.capability("洋务运动目的")["pairs"]
    # An apparently different ID cannot make a copied practice an independent ticket.
    western.exit_ticket_items = [original.practice_items[0].model_copy(update={"assessment_id": "fake-independent", "kind": "exit_ticket", "difficulty": "medium"})]
    assert original.practice_items[0].assessment_id not in catalog.Catalog((western,), "test").capability("洋务运动目的")["pairs"]
    # All selectable IDs are validated combinations, not just the first pair in an array.
    real = catalog.Catalog((original,), "test").capability("洋务运动目的")
    assert len(real["pairs"]) == 3
    lower = original.model_copy(deep=True)
    lower.practice_items = [q for q in lower.practice_items if q.difficulty == "easy"]
    chosen = catalog.choose([], [], [], focus="洋务运动目的", catalog=catalog.Catalog((lower,), "test"))
    assert chosen[1] == "easy" and chosen[2]["requested_difficulty"] == "medium"
    with patch.object(content, "load_curated_content", return_value=()):
        assert catalog.targets()["items"] == []
    print("OK catalog_real_pair_validation_empty_and_lower_difficulty")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "content.json"
        payload = {"items": [original.model_dump(mode="json")]}
        path.write_text(json.dumps(payload))
        with patch.object(content, "CONTENT_PATH", path):
            first = catalog.snapshot()
            stat = path.stat()
            payload["items"][0]["review_status"] = "withdrawn"
            path.write_text(json.dumps(payload))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            second = catalog.snapshot()
            assert first.version != second.version and not second.capability("洋务运动目的")["pairs"]
            for malformed in ("not json", '{"items":null}', '{"items":42}'):
                path.write_text(malformed)
                assert not catalog.snapshot().entries
            path.unlink()
            assert not catalog.snapshot().entries
    print("OK catalog_content_replacement_with_same_mtime_and_removal")

    metadata.create_all(engine)
    seed(verbose=False)
    clear_weakpoints("pilot-student")
    for item in weak:
        for _ in range(item["wrong_count"]):
            record_weakpoint("pilot-student", item["knowledge_tag"], source="catalog_eval")
    before = get_weakpoints("pilot-student")
    client = TestClient(app)
    def login(user):
        return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": user, "password": "pilot123"}).json()["token"]}
    headers, teacher = login("pilot-student"), login("pilot-teacher")
    assert client.get("/api/autotutor/targets").status_code == 401
    public = client.get("/api/autotutor/targets", headers=headers)
    assert public.status_code == 200 and len(public.json()["items"]) == 5
    serialized = json.dumps(public.json())
    assert not any(word in serialized for word in ("answer", "reviewed_by", "source_refs", "student_id", "question", "options"))
    assert client.get("/api/autotutor/targets", headers=teacher).json() == public.json()
    safe = catalog.project_planning({**auto[2], "secret": "private", "selection_source": [], "skipped_count": "private"}, 3)
    assert "private" not in json.dumps(safe) and safe["revision"] == 3
    print("OK catalog_api_auth_and_projection")

    def start(key, focus=None):
        body = {"student_id": "pilot-student", "idempotency_key": key, "grade": "八年级上册"}
        if focus:
            body["focus_tags"] = [focus]
        result = client.post("/api/autotutor/start", json=body, headers=headers)
        assert result.status_code == 200
        return result.json(), body
    for mode in ("graph_active", "legacy"):
        with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "true" if mode == "legacy" else "false"}):
            with patch.object(at.DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER, "prepare", wraps=at.DEFAULT_AUTOTUTOR_OBSERVATION_PROVIDER.prepare) as provider:
                result, body = start("catalog-auto-" + mode)
                replay = client.post("/api/autotutor/start", json=body, headers=headers).json()
                assert provider.call_count == 1 and replay["session_id"] == result["session_id"]
            assert result["lesson_plan"][0]["knowledge_point"] == "洋务运动目的" and result["current_question"]
            assert at._load_persisted_session(result["session_id"]).executor_mode == mode
            if mode == "graph_active":
                assert result["execution"]["selected_executor"] == mode
            assert result["planning_decision"]["skipped_count"] == 1
            blocked, _ = start("catalog-explicit-" + mode, "甲午战争影响")
            assert blocked["status"] == "needs_content" and blocked["lesson_plan"][0]["knowledge_point"] == "甲午战争影响"
            assert not blocked["current_question"] and blocked["mastery"]["status"] != "verified"
            sid = result["session_id"]
            restored = client.get(f"/api/autotutor/session/{sid}", headers=headers).json()
            evidence = client.get(f"/api/autotutor/session/{sid}/evidence", headers=teacher).json()
            trace = client.get(f"/api/autotutor/session/{sid}/demo-trace", headers=headers).json()
            assert restored["planning_decision"] == evidence["planning_decision"] == trace["planning_decision"] == result["planning_decision"]
            examples.append({"mode": mode, "automatic_target": result["lesson_plan"][0]["knowledge_point"],
                "explicit_target": blocked["lesson_plan"][0]["knowledge_point"], "explicit_status": blocked["status"],
                "planning_decision": result["planning_decision"]})
    assert get_weakpoints("pilot-student") == before
    print("OK catalog_real_graph_legacy_planning_explicit_replay_evidence")

    # Revoke content after a valid start; no answer grading or mastery writes occur.
    current, _ = start("catalog-revocation")
    stored = at._load_persisted_session(current["session_id"])
    answer = stored.lesson_plan[0].question["answer"]
    with patch.object(content, "load_curated_content", return_value=()):
        result = client.post("/api/autotutor/answer", headers=headers, json={"session_id": current["session_id"], "answer": answer,
            "expected_revision": current["revision"], "idempotency_key": "catalog-revoked-answer"}).json()
    assert result["status"] == "needs_content" and result["revision"] == current["revision"] + 1
    assert "last_answer_correct" not in result and get_weakpoints("pilot-student") == before
    assert result["planning_decision"]["launchable"] is False
    # Independent exit tickets are revalidated too, before judging the answer.
    exit_start, _ = start("catalog-exit-revocation")
    practice = at._load_persisted_session(exit_start["session_id"]).lesson_plan[0].question
    ticket = client.post("/api/autotutor/answer", headers=headers, json={"session_id": exit_start["session_id"],
        "answer": practice["answer"], "expected_revision": exit_start["revision"], "idempotency_key": "catalog-exit-practice"}).json()
    assert ticket["phase"] == "exit_ticket"
    exit_answer = at._load_persisted_session(ticket["session_id"]).exit_ticket.question["answer"]
    before_exit = get_weakpoints("pilot-student")
    with patch.object(content, "load_curated_content", return_value=()):
        revoked_exit = client.post("/api/autotutor/answer", headers=headers, json={"session_id": ticket["session_id"],
            "answer": exit_answer, "expected_revision": ticket["revision"], "idempotency_key": "catalog-exit-revoked"}).json()
    assert revoked_exit["status"] == "needs_content" and revoked_exit["mastery"]["status"] != "verified"
    assert "last_answer_correct" not in revoked_exit and get_weakpoints("pilot-student") == before_exit
    real_snapshot = catalog.snapshot
    calls = 0
    def changed():
        nonlocal calls
        calls += 1
        return real_snapshot() if calls == 1 else catalog.Catalog((), "changed")
    with patch.object(catalog, "snapshot", side_effect=changed):
        changed_start, _ = start("catalog-midflight-change")
    assert changed_start["status"] == "needs_content" and changed_start["planning_decision"]["reason_code"] == "catalog_changed"
    assert NETWORK_COUNTS["external_attempts"] == 0
    print("OK catalog_midflight_change_and_answer_revocation")
    if OUTPUT:
        Path(OUTPUT).write_text(json.dumps({"schema_version": 1, "production_evidence": False, "examples": examples}, ensure_ascii=False))


if __name__ == "__main__":
    main()
