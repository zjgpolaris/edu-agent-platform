"""v1.49.6 CI provenance, deployment convergence and receipt contracts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_autotutor_canary_deployment import (  # noqa: E402
    _assert_pii_free,
    _exit_code,
    attach_evidence_to_receipt,
    build_workflow_receipt,
    validate_ci_provenance,
    verify_remote,
)

COMMIT = "a" * 40
OLD_COMMIT = "b" * 40
CONFIG = "v1.49.6-production-execution"
CI = {
    "schema_version": 1,
    "workflow": "EduAgent CI",
    "status": "verified",
    "conclusion": "success",
    "event": "push",
    "head_sha": COMMIT,
    "run_id": "12345",
}


class Response:
    def __init__(self, payload: dict):
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def read(self) -> bytes: return json.dumps(self.payload).encode()


def _verification(commit: str) -> dict:
    return {
        "phase": "ready_for_manual_one_percent",
        "status": "READY",
        "decision": "GO",
        "blockers": [],
        "deployment": {"deployed_commit": commit, "environment": "production"},
        "configuration": {"config_version": CONFIG},
        "window": {"start": "2026-09-02T00:00:00+00:00", "end": None},
        "evidence": {"present": False, "stage": None, "sha256": None},
    }


def main() -> None:
    assert validate_ci_provenance(CI, expected_commit=COMMIT)["run_id"] == "12345"
    for invalid in (
        {**CI, "status": "pending", "conclusion": ""},
        {**CI, "conclusion": "failure"},
        {**CI, "event": "pull_request"},
        {**CI, "head_sha": OLD_COMMIT},
    ):
        try:
            validate_ci_provenance(invalid, expected_commit=COMMIT)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid CI provenance must fail closed")

    responses = [
        {"ok": True},
        _verification(OLD_COMMIT),
        _verification(COMMIT),
        _verification(COMMIT),
    ]

    def open_stub(_request, timeout=0):
        assert timeout > 0
        return Response(responses.pop(0))

    artifact = verify_remote(
        api_base="https://example.invalid",
        token="never-exported",
        expected_commit=COMMIT,
        expected_config_version=CONFIG,
        phase="preflight",
        wait_for_deployment=True,
        deployment_timeout_seconds=300,
        require_ci_provenance=True,
        ci_provenance=CI,
        urlopen=open_stub,
        sleep=lambda _seconds: None,
    )
    assert artifact["deployment_converged"] is True
    assert artifact["deployment_attempts"] == 3
    assert artifact["ci"]["status"] == "verified"
    assert _exit_code(artifact) == 0
    assert "never-exported" not in json.dumps(artifact)

    snapshot_responses = [{"ok": True}, _verification(COMMIT)]

    def snapshot_stub(_request, timeout=0):
        assert timeout > 0
        return Response(snapshot_responses.pop(0))

    snapshot_artifact = verify_remote(
        api_base="https://example.invalid",
        token="never-exported",
        expected_commit=COMMIT,
        expected_config_version=CONFIG,
        phase="control_snapshot",
        window_start="2026-09-02T00:00:00Z",
        window_end="2026-09-02T01:00:00Z",
        wait_for_deployment=True,
        deployment_timeout_seconds=300,
        urlopen=snapshot_stub,
        sleep=lambda _seconds: None,
    )
    assert snapshot_artifact["deployment_attempts"] == 1
    assert snapshot_responses == []

    receipt = build_workflow_receipt(
        artifact,
        expected_commit=COMMIT,
        expected_config_version=CONFIG,
        phase="preflight",
        ci_provenance=CI,
    )
    digest = receipt.pop("receipt_sha256")
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    _assert_pii_free(receipt)
    assert "never-exported" not in json.dumps(receipt)
    attached = attach_evidence_to_receipt(receipt, {
        "evidence_stage": "candidate", "evidence_sha256": "sha256:evidence",
    })
    assert attached["evidence_stage"] == "candidate"
    assert attached["evidence_sha256"] == "sha256:evidence"
    assert attached["receipt_sha256"] != digest

    timeout_responses = [{"ok": True}, _verification(OLD_COMMIT)]

    def timeout_stub(_request, timeout=0):
        return Response(timeout_responses.pop(0))

    try:
        verify_remote(
            api_base="https://example.invalid", token="hidden", expected_commit=COMMIT,
            expected_config_version=CONFIG, phase="preflight", wait_for_deployment=True,
            deployment_timeout_seconds=0, ci_provenance=CI, urlopen=timeout_stub,
            sleep=lambda _seconds: None,
        )
    except ValueError as exc:
        assert str(exc) == "deployment_not_converged"
    else:
        raise AssertionError("deployment convergence timeout must fail closed")

    assert _exit_code({"result": {"status": "NOT_READY", "decision": "NO_GO"}}) == 6

    for field in ("secret", "cookie", "prompt", "response"):
        try:
            _assert_pii_free({"nested": {field: "unsafe"}})
        except ValueError:
            pass
        else:
            raise AssertionError(f"privacy scan must reject {field}")

    print("autotutor_production_execution_closure_smoke=PASS")


if __name__ == "__main__":
    main()
