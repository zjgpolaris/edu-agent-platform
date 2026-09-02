"""Remote verifier handles cold starts, provenance and secret-free artifacts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_autotutor_canary_deployment import _assert_pii_free, _exit_code, verify_remote  # noqa: E402

COMMIT = "d" * 40
CONFIG = "v1.49.5-production-attestation"


class Response:
    def __init__(self, payload: dict):
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def read(self) -> bytes: return json.dumps(self.payload).encode()


def main() -> None:
    workflow = (ROOT / ".github" / "workflows" / "autotutor-production-verification.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow and "schedule:" not in workflow and "push:" not in workflow
    assert "environment: production-verification" in workflow and "retention-days: 30" in workflow
    assert "--persist-url" in workflow and "--require-go" in workflow
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE" in render and "value: legacy" in render
    assert "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS" in render and "value: \"0\"" in render
    calls = []

    def open_stub(request, timeout=0):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise TimeoutError("cold start")
        if "/api/health" in request.full_url:
            return Response({"ok": True})
        return Response({"status": "READY", "decision": "GO", "blockers": [],
                         "deployment": {"deployed_commit": COMMIT},
                         "configuration": {"config_version": CONFIG}})

    artifact = verify_remote(api_base="https://example.invalid", token="super-secret", expected_commit=COMMIT,
                             expected_config_version=CONFIG, phase="preflight", urlopen=open_stub, sleep=lambda _seconds: None)
    assert artifact["cold_start_recovered"] and _exit_code(artifact) == 0
    assert calls[-1][0].headers["Authorization"] == "Bearer super-secret"
    assert "super-secret" not in json.dumps(artifact)
    _assert_pii_free(artifact)
    try:
        _assert_pii_free({"student_id": "unsafe"})
    except ValueError:
        pass
    else:
        raise AssertionError("PII field must be rejected")
    print("autotutor_production_remote_cli_smoke=PASS")


if __name__ == "__main__":
    main()
