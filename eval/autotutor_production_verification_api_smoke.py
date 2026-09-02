"""AutoTutor production verification admin endpoints preserve the service contract."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("EDU_AGENT_AUTH_REQUIRED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402

COMMIT = "a" * 40
CONFIG = "v1.49.4-production-verification"


def main() -> None:
    verification = {
        "schema_version": 1, "status": "READY", "decision": "GO", "blockers": [],
        "deployment": {"deployed_commit": COMMIT}, "configuration": {"config_version": CONFIG},
    }
    snapshot = {"schema_version": 1, "snapshot_sha256": "sha256:test", "snapshot": verification}
    client = TestClient(app)
    with patch("agent_runtime.autotutor_canary_verification.build_autotutor_canary_verification", return_value=verification):
        response = client.get("/api/admin/agent-runtime/autotutor-canary/verification", params={
            "expected_commit": COMMIT, "expected_config_version": CONFIG,
        })
    assert response.status_code == 200 and response.json()["decision"] == "GO", response.text
    with patch("agent_runtime.autotutor_canary_verification.build_autotutor_canary_snapshot", return_value=snapshot):
        response = client.post("/api/admin/agent-runtime/autotutor-canary/snapshots", json={
            "expected_commit": COMMIT, "expected_config_version": CONFIG,
            "window_start": "2026-09-02T00:00:00+00:00", "window_end": "2026-09-02T01:00:00+00:00",
        })
    assert response.status_code == 200 and response.json()["snapshot_sha256"] == "sha256:test", response.text
    response = client.post("/api/admin/agent-runtime/autotutor-canary/snapshots", json={
        "expected_commit": "short", "expected_config_version": CONFIG,
        "window_start": "2026-09-02T00:00:00+00:00", "window_end": "2026-09-02T01:00:00+00:00",
    })
    assert response.status_code == 422
    print("autotutor_production_verification_api_smoke=PASS")


if __name__ == "__main__":
    main()
