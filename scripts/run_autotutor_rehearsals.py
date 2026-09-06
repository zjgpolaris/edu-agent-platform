#!/usr/bin/env python3
"""Bounded, operator-assisted rehearsal observations; never issues production GO.

Session IDs, credentials and answers remain in memory. Only signed, PII-free
server observations and coverage limits are written to the artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_autotutor_canary_verification_traffic import (
    _credentials, _select_account, _issue_traffic_token, _request_json,
    _validate_preflight, _answer_for_public_question, _reviewed_answer_texts,
    _assert_receipt_safe, _write_receipt, _failure_code,
)


def run(*, api_base, commit, config, output, timeout=3000, env=None,
        request=_request_json, sleep=time.sleep, monotonic=time.monotonic):
    source = dict(os.environ if env is None else env)
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", config):
        raise ValueError("verification_deployment_identity_invalid")
    if source.get("AUTOTUTOR_VERIFICATION_ENVIRONMENT") != "production-verification":
        raise ValueError("verification_environment_not_protected")
    parsed = urllib.parse.urlparse(api_base)
    allowed = source.get("AUTOTUTOR_PRODUCTION_ALLOWED_HOSTS", "").split(",")
    if parsed.scheme != "https" or parsed.hostname not in {h.strip() for h in allowed} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("api_host_not_allowlisted")
    if not 1 <= timeout <= 3300:
        raise ValueError("rehearsal_timeout_invalid")
    deadline = monotonic() + timeout
    receipt = {"schema_version": 1, "receipt_type": "autotutor_rehearsal_runner",
               "commit": commit, "config_version": config, "environment": "production",
               "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
               "production_attestation": False, "production_ready": False, "observations": {},
               "coverage_limits": ["process_change_requires_operator_restart_confirmation",
                                   "writer_probe_does_not_cover_cache_or_postcommit_failure"]}
    def checkpoint(stage):
        receipt["stage"] = stage
        _assert_receipt_safe(receipt)
        _write_receipt(Path(output), receipt)
        print(json.dumps({"stage": stage, "production_ready": False}), flush=True)
    def call(path, **kwargs):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("verification_traffic_timeout")
        # No automatic POST retries: ambiguous results stop and retain evidence.
        return request(api_base.rstrip("/") + path, timeout=min(30, remaining), **kwargs)
    machine = {"Authorization": "Bearer " + source.get("AUTOTUTOR_PRODUCTION_API_TOKEN", ""),
               "X-AutoTutor-Bootstrap-SHA256": source.get("AUTOTUTOR_PRODUCTION_BOOTSTRAP_SHA256", "")}
    try:
        checkpoint("preflight")
        capabilities = call("/api/admin/agent-runtime/autotutor-canary/rehearsals/capabilities", headers=machine)
        if capabilities.get("enabled") is not True or capabilities.get("commit") != commit or capabilities.get("environment") != "production":
            raise ValueError("rehearsal_capability_unavailable")
        preflight = call("/api/admin/agent-runtime/autotutor-canary/verification?" + urllib.parse.urlencode({
            "expected_commit": commit, "expected_config_version": config}), headers=machine)
        settings = _validate_preflight(preflight, expected_commit=commit, expected_config_version=config, phase="canary")
        if (preflight.get("admission") or {}).get("status") != "admitted":
            raise ValueError("rehearsal_admission_not_ready")
        account = _select_account(_credentials(source.get("AUTOTUTOR_VERIFICATION_STUDENT_CREDENTIALS_JSON", "")),
                                  phase="canary", salt=source.get("AUTOTUTOR_GRAPH_BUCKET_SALT", ""), active_bps=settings["active_bps"])
        login = call("/api/auth/login", method="POST", payload={"username": account["username"], "password": account["password"]})
        if login.get("actor_id") != account["actor_id"] or login.get("role") != "student" or not login.get("token"):
            raise ValueError("verification_student_identity_mismatch")
        run_id = "adr_" + uuid4().hex
        reviewed = _reviewed_answer_texts()
        def transition(path, payload):
            receipt["transition_outcome_unknown"] = True
            _write_receipt(Path(output), receipt)
            result = call(path, method="POST", payload=payload, headers={
                "Authorization": "Bearer " + login["token"], "X-AutoTutor-Verification-Run": run_id,
                "X-AutoTutor-Verification-Attestation": _issue_traffic_token(actor_id=account["actor_id"],
                    verification_run_id=run_id, phase="canary", deployed_commit=commit, config_version=config,
                    secret=source["AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET"]),
            })
            receipt["transition_outcome_unknown"] = False
            _write_receipt(Path(output), receipt)
            return result
        def start(suffix):
            state = transition("/api/autotutor/start", {"student_id": account["actor_id"], "grade": "八年级上册",
                "focus_tags": ["戊戌变法失败原因"], "idempotency_key": run_id + suffix})
            if state.get("status") != "awaiting_answer":
                raise ValueError("rehearsal_content_unavailable")
            return state
        def observe(state, operation="checkpoint", previous=None):
            return call("/api/admin/agent-runtime/autotutor-canary/rehearsals", method="POST", headers=machine,
                payload={"student_id": account["actor_id"], "session_id": state["session_id"],
                    "verification_run_id": run_id, "expected_commit": commit, "expected_config_version": config,
                    "operation": operation, "previous": previous})
        def wait_for(state, predicate):
            while True:
                try:
                    value = observe(state)
                    if predicate(value["payload"]):
                        return value
                except urllib.error.HTTPError as exc:
                    if exc.code not in {502, 503, 504}:
                        raise
                except (urllib.error.URLError, TimeoutError):
                    pass
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("verification_traffic_timeout")
                sleep(min(30, remaining))
        def answer(state, suffix):
            return {"session_id": state["session_id"], "student_id": account["actor_id"],
                    "answer": _answer_for_public_question(state.get("current_question") or {}, reviewed),
                    "expected_revision": state["revision"], "idempotency_key": run_id + suffix}
        def require_check(value, name):
            if value["payload"].get("checks", {}).get(name) is not True:
                raise ValueError("rehearsal_check_failed")

        checkpoint("preparing_restart_session")
        state = start("-restart-start")
        before = observe(state)
        if before["payload"]["selected_executor"] != "graph_active":
            raise ValueError("rehearsal_requires_graph_session")
        receipt["observations"]["restart_before"] = before
        checkpoint("manual_restart_required_keep_commit_and_config")
        wait_for(state, lambda p: p["process_instance"] != before["payload"]["process_instance"])
        restored = observe(state, "restart_verify", before)
        require_check(restored, "state_survived_process_change")
        receipt["observations"]["restart_restored"] = restored
        command = answer(state, "-restart-answer")
        transition("/api/autotutor/answer", command)
        replay = transition("/api/autotutor/answer", command)
        if replay.get("idempotent_replay") is not True:
            raise ValueError("rehearsal_replay_not_confirmed")
        resumed = observe(state, "restart_resume_verify", restored)
        require_check(resumed, "resumed_once_after_process_change")
        receipt["observations"]["restart_resumed"] = resumed
        checkpoint("writer_probe")
        probe = observe(state, "writer_probe")
        require_check(probe, "uncached_admission_denied_on_writer_unavailable")
        receipt["observations"]["writer_probe"] = probe

        state = start("-kill-start")
        before = observe(state)
        if before["payload"]["selected_executor"] != "graph_active":
            raise ValueError("rehearsal_requires_graph_session")
        receipt["observations"]["kill_before"] = before
        checkpoint("manual_enable_kill_switch_required")
        wait_for(state, lambda p: p["kill_switch"] is True)
        transition("/api/autotutor/answer", answer(state, "-kill-answer"))
        killed = observe(state, "kill_switch_verify", before)
        require_check(killed, "kill_switch_downgraded_transition")
        receipt["observations"]["kill_after"] = killed
        checkpoint("manual_restore_kill_switch_false_keep_bps_required")
        restored = wait_for(state, lambda p: p["kill_switch"] is False)
        if restored["payload"]["active_bps"] != before["payload"]["active_bps"]:
            raise ValueError("rehearsal_bps_changed")
        receipt["observations"]["configuration_restored"] = restored
        receipt["status"] = "observed"
        return receipt
    except (Exception, KeyboardInterrupt) as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = _failure_code(exc)
        receipt["next_action"] = "stop_and_inspect_keep_or_restore_legacy_bps_zero"
        raise
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_receipt(Path(output), receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-config-version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3000)
    args = parser.parse_args()
    try:
        run(api_base=args.api_base, commit=args.expected_commit, config=args.expected_config_version,
            output=args.output, timeout=args.timeout_seconds)
    except (Exception, KeyboardInterrupt) as exc:
        # The receipt carries safe diagnostics; never print HTTP bodies or credentials.
        if not Path(args.output).exists():
            _write_receipt(Path(args.output), {"schema_version": 1, "receipt_type": "autotutor_rehearsal_runner",
                "status": "failed", "error_code": _failure_code(exc), "production_ready": False,
                "production_attestation": False})
        return 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
