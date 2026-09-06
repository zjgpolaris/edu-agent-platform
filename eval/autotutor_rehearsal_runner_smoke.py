"""Bounded manual orchestration and no accidental production attestation."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_autotutor_rehearsals import run
from scripts.run_autotutor_canary_verification_traffic import stable_executor_bucket, _reviewed_answer_texts


def main():
    commit, config, salt = "a" * 40, "runner-rehearsal", "runner-salt"
    actor = next(f"private-{i}" for i in range(10000) if stable_executor_bucket(f"private-{i}", salt=salt) < 100)
    env = {"AUTOTUTOR_VERIFICATION_ENVIRONMENT": "production-verification",
        "AUTOTUTOR_PRODUCTION_ALLOWED_HOSTS": "edu.example", "AUTOTUTOR_GRAPH_BUCKET_SALT": salt,
        "AUTOTUTOR_PRODUCTION_API_TOKEN": "private-machine", "AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256": "a" * 64,
        "AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET": "t" * 48,
        "AUTOTUTOR_VERIFICATION_STUDENT_CREDENTIALS_JSON": json.dumps([{"actor_id": actor, "username": "private-user", "password": "private-password"}])}
    question = {"assessment_id": "wuxu-cause-practice-3",
                "options": ["A. " + _reviewed_answer_texts()["wuxu-cause-practice-3"], "B. other"]}
    for never_restart in (False, True):
        ticks, checkpoints, starts, answers = [0], [0], [0], []
        def request(url, **kwargs):
            assert kwargs["timeout"] <= 30
            if url.endswith("/capabilities"):
                return {"enabled": True, "commit": commit, "environment": "production"}
            if "/verification?" in url:
                return {"deployment": {"environment": "production", "deployed_commit": commit},
                        "configuration": {"mode": "active_canary", "active_bps": 100, "config_version": config},
                        "admission": {"status": "admitted"}}
            if url.endswith("/login"):
                return {"actor_id": actor, "role": "student", "token": "private-token"}
            if url.endswith("/start"):
                starts[0] += 1
                return {"session_id": "private-session-" + str(starts[0]), "status": "awaiting_answer", "revision": 0, "current_question": question}
            if url.endswith("/answer"):
                answers.append(kwargs["payload"])
                return {"idempotent_replay": len(answers) == 2}
            operation = kwargs["payload"]["operation"]
            checks = {"state_survived_process_change": True, "resumed_once_after_process_change": True,
                      "uncached_admission_denied_on_writer_unavailable": True, "kill_switch_downgraded_transition": True}
            if operation == "checkpoint":
                checkpoints[0] += 1
            payload = {"process_instance": "first" if checkpoints[0] == 1 or never_restart else "second",
                       "selected_executor": "graph_active", "active_bps": 100, "kill_switch": checkpoints[0] == 4,
                       "checks": checks, "production_attestation": False}
            return {"payload": payload, "signature": "safe-signature"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            try:
                result = run(api_base="https://edu.example", commit=commit, config=config, output=output,
                    timeout=61, env=env, request=request, monotonic=lambda: ticks[0], sleep=lambda n: ticks.__setitem__(0, ticks[0] + n))
                assert not never_restart and result["status"] == "observed"
                assert starts[0] == 2 and len(answers) == 3 and answers[0] == answers[1]
            except TimeoutError:
                assert never_restart and ticks[0] == 61 and not answers
            receipt = json.loads(output.read_text())
            assert receipt["production_ready"] is False and receipt["production_attestation"] is False
            assert "private" not in json.dumps(receipt)
            assert receipt["finished_at"]
    with tempfile.TemporaryDirectory() as directory:
        calls = []
        def disabled(url, **kwargs):
            calls.append(url)
            assert url.endswith("/capabilities")
            return {"enabled": False, "commit": commit, "environment": "production"}
        try:
            run(api_base="https://edu.example", commit=commit, config=config, output=Path(directory) / "receipt.json",
                env=env, request=disabled)
            raise AssertionError("disabled capability allowed traffic")
        except ValueError:
            assert len(calls) == 1
    source = (ROOT / ".github/workflows/autotutor-production-rehearsals.yml").read_text()
    assert "environment: production-verification" in source and "cancel-in-progress: false" in source
    assert "contents: write" not in source and "deployments: write" not in source
    assert "--timeout-seconds 3000" in source and "if: always()" in source
    production = (ROOT / ".github/workflows/autotutor-production-verification.yml").read_text()
    assert "inputs.build_candidate_evidence && steps.remote.outcome" in production
    print("autotutor_rehearsal_runner_smoke=PASS")


if __name__ == "__main__":
    main()
