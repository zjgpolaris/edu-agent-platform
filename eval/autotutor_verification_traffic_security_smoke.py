"""Controlled traffic attestations are bound, expiring, allowlisted and single-use."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-verification-traffic-security.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException  # noqa: E402
from db.engine import engine  # noqa: E402
from db.schema import metadata  # noqa: E402
from security.auth import Actor  # noqa: E402
from security.autotutor_verification_auth import (  # noqa: E402
    issue_autotutor_verification_traffic_token,
    resolve_autotutor_verification_traffic,
)

COMMIT = "a" * 40
CONFIG = "v1.49.9-production-canary"
ACTOR = "verification-student-01"
RUN_ID = "avr_security_smoke_01"
ENV = {
    "EDU_AGENT_AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET": "s" * 48,
    "EDU_AGENT_AUTOTUTOR_VERIFICATION_STUDENT_IDS": ACTOR,
    "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "active_canary",
    "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "100",
    "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": CONFIG,
    "EDU_AGENT_AUTOTUTOR_GRAPH_BUCKET_SALT": "security-smoke",
    "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true",
    "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
    "EDU_AGENT_ENVIRONMENT": "production",
    "EDU_AGENT_DEPLOYED_COMMIT": COMMIT,
}


def _token(**overrides: str) -> str:
    values = {
        "actor_id": ACTOR, "verification_run_id": RUN_ID, "phase": "canary",
        "deployed_commit": COMMIT, "config_version": CONFIG,
    }
    values.update(overrides)
    return issue_autotutor_verification_traffic_token(**values, env=ENV)


def main() -> None:
    metadata.create_all(engine)
    actor = Actor(actor_id=ACTOR, role="student", account_status="active", traffic_cohort="verified")
    with patch("deployment.deployment_environment", return_value="production"), patch(
        "deployment.deployed_commit", return_value=COMMIT
    ):
        organic = resolve_autotutor_verification_traffic(
            actor=actor, verification_run_id=None, attestation=None, env=ENV
        )
        assert organic.traffic_source == "organic" and organic.verification_run_id is None

        token = _token()
        accepted = resolve_autotutor_verification_traffic(
            actor=actor, verification_run_id=RUN_ID, attestation=token, env=ENV
        )
        assert accepted.traffic_source == "release_verification" and accepted.phase == "canary"

        try:
            resolve_autotutor_verification_traffic(
                actor=actor, verification_run_id=RUN_ID, attestation=token, env=ENV
            )
            raise AssertionError("replayed nonce was accepted")
        except HTTPException as exc:
            assert exc.status_code == 403 and exc.detail == "verification_attestation_replayed"

        for invalid_actor in (
            Actor(actor_id="other", role="student", account_status="active", traffic_cohort="verified"),
            Actor(actor_id=ACTOR, role="student", account_status="disabled", traffic_cohort="verified"),
        ):
            try:
                resolve_autotutor_verification_traffic(
                    actor=invalid_actor, verification_run_id=RUN_ID, attestation=_token(), env=ENV
                )
                raise AssertionError("untrusted actor was accepted")
            except HTTPException as exc:
                assert exc.status_code == 403

        control_token = _token(phase="control")
        try:
            resolve_autotutor_verification_traffic(
                actor=actor, verification_run_id=RUN_ID, attestation=control_token, env=ENV
            )
            raise AssertionError("wrong phase was accepted")
        except HTTPException as exc:
            assert exc.status_code == 403 and exc.detail == "verification_phase_config_mismatch"
    print("autotutor_verification_traffic_security_smoke=PASS")


if __name__ == "__main__":
    main()
