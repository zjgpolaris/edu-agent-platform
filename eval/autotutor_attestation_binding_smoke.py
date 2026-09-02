"""v1.49.8 workflow, remote client and receipt attestation binding."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_autotutor_canary_evidence import persist_remote_evidence  # noqa: E402
from scripts.verify_autotutor_canary_deployment import (  # noqa: E402
    build_workflow_receipt,
    require_bootstrap_attestation,
    seal_workflow_receipt,
    verify_remote,
)

COMMIT = "8" * 40
CONFIG = "v1.49.8-attestation-binding"
BOOTSTRAP = "c" * 64


class Response:
    def __init__(self, payload: dict):
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def read(self) -> bytes: return json.dumps(self.payload).encode()


def main() -> None:
    assert require_bootstrap_attestation(BOOTSTRAP) == BOOTSTRAP
    for invalid, reason in (("", "bootstrap_attestation_missing"), ("not-a-digest", "bootstrap_attestation_invalid")):
        try:
            require_bootstrap_attestation(invalid)
        except PermissionError as exc:
            assert str(exc) == reason
        else:
            raise AssertionError("invalid bootstrap attestation must fail before network access")

    calls = []

    def open_stub(request, timeout=0):
        calls.append(request)
        if "/api/health" in request.full_url:
            return Response({"ok": True})
        return Response({
            "phase": "ready_for_manual_one_percent",
            "status": "READY",
            "decision": "GO",
            "blockers": [],
            "deployment": {"deployed_commit": COMMIT, "environment": "production"},
            "configuration": {"config_version": CONFIG},
        })

    artifact = verify_remote(
        api_base="https://example.invalid",
        token="machine-token-not-written-to-artifact",
        bootstrap_sha256=BOOTSTRAP,
        expected_commit=COMMIT,
        expected_config_version=CONFIG,
        phase="preflight",
        urlopen=open_stub,
        sleep=lambda _seconds: None,
    )
    assert calls[-1].headers["X-autotutor-bootstrap-sha256"] == BOOTSTRAP
    assert BOOTSTRAP not in json.dumps(artifact)

    receipt = build_workflow_receipt(
        artifact,
        expected_commit=COMMIT,
        expected_config_version=CONFIG,
        phase="preflight",
        bootstrap_sha256=BOOTSTRAP,
    )
    assert receipt["schema_version"] == 2
    assert receipt["bootstrap_attestation_sha256"] == BOOTSTRAP
    digest = receipt["receipt_sha256"]
    tampered = {**receipt, "bootstrap_attestation_sha256": "d" * 64}
    assert seal_workflow_receipt(tampered)["receipt_sha256"] != digest

    evidence = {"evidence_sha256": "sha256:evidence"}
    evidence_calls = []

    def evidence_open(request, timeout=0):
        evidence_calls.append(request)
        return Response(evidence)

    with patch("scripts.build_autotutor_canary_evidence.urllib.request.urlopen", evidence_open):
        persisted = persist_remote_evidence(
            "https://example.invalid/evidence",
            evidence,
            token="machine-token-not-written-to-artifact",
            bootstrap_sha256=BOOTSTRAP,
        )
    assert persisted == evidence
    assert evidence_calls[0].headers["X-autotutor-bootstrap-sha256"] == BOOTSTRAP
    assert hashlib.sha256(BOOTSTRAP.encode()).hexdigest() not in json.dumps(receipt)
    print("autotutor_attestation_binding_smoke=PASS")


if __name__ == "__main__":
    main()
