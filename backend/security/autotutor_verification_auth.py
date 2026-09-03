"""Least-privilege machine identity for AutoTutor production verification."""
from __future__ import annotations

import hashlib
import hmac
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from fastapi import Header, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from security.audit_log import record_audit_event
from security.auth import Actor, auth_required, require_auth

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_MIN_TOKEN_LENGTH = 32
_MACHINE_ACTOR_PREFIX = "autotutor-verifier:"
_bearer = HTTPBearer(auto_error=False)
_TRAFFIC_TOKEN_PREFIX = "atv1_"
_VERIFICATION_RUN_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_VALID_VERIFICATION_PHASES = {"control", "canary", "rollback"}


@dataclass(frozen=True)
class AutoTutorVerificationIdentitySettings:
    required: bool
    current_sha256: str
    current_key_id: str
    next_sha256: str
    next_key_id: str
    bootstrap_sha256: str
    errors: tuple[str, ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AutoTutorVerificationIdentitySettings":
        source = os.environ if env is None else env
        required = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_MACHINE_REQUIRED", "false")).strip().lower() in _TRUE_VALUES
        current_sha256 = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_SHA256", "")).strip()
        current_key_id = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_TOKEN_KEY_ID", "current")).strip()
        next_sha256 = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_NEXT_TOKEN_SHA256", "")).strip()
        next_key_id = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_NEXT_TOKEN_KEY_ID", "")).strip()
        bootstrap_sha256 = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_BOOTSTRAP_SHA256", "")).strip()
        errors: list[str] = []
        if current_sha256 and not _SHA256_RE.fullmatch(current_sha256):
            errors.append("current_digest_invalid")
        if current_sha256 and not _KEY_ID_RE.fullmatch(current_key_id):
            errors.append("current_key_id_invalid")
        if not current_sha256 and current_key_id not in {"", "current"}:
            errors.append("current_slot_incomplete")
        if bool(next_sha256) != bool(next_key_id):
            errors.append("next_slot_incomplete")
        if next_sha256 and not _SHA256_RE.fullmatch(next_sha256):
            errors.append("next_digest_invalid")
        if next_key_id and not _KEY_ID_RE.fullmatch(next_key_id):
            errors.append("next_key_id_invalid")
        if current_sha256 and next_sha256 and hmac.compare_digest(current_sha256, next_sha256):
            errors.append("rotation_digest_duplicate")
        if bootstrap_sha256 and not _SHA256_RE.fullmatch(bootstrap_sha256):
            errors.append("bootstrap_digest_invalid")
        return cls(
            required=required,
            current_sha256=current_sha256,
            current_key_id=current_key_id or "current",
            next_sha256=next_sha256,
            next_key_id=next_key_id,
            bootstrap_sha256=bootstrap_sha256,
            errors=tuple(dict.fromkeys(errors)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.current_sha256)

    @property
    def valid(self) -> bool:
        return self.configured and not self.errors

    @property
    def bootstrap_attested(self) -> bool:
        return bool(_SHA256_RE.fullmatch(self.bootstrap_sha256))

    @property
    def rotation_state(self) -> str:
        if self.errors:
            return "invalid"
        if not self.configured:
            return "missing"
        return "dual" if self.next_sha256 else "current_only"

    def safe_summary(self) -> dict[str, object]:
        return {
            "required": self.required,
            "configured": self.configured,
            "valid": self.valid,
            "rotation_state": self.rotation_state,
            "bootstrap_attested": self.bootstrap_attested,
            "errors": list(self.errors),
        }

    def match_token(self, token: str) -> str | None:
        if not self.valid or len(token) < _MIN_TOKEN_LENGTH:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        current_match = hmac.compare_digest(digest, self.current_sha256)
        next_match = bool(self.next_sha256) and hmac.compare_digest(digest, self.next_sha256)
        if current_match:
            return self.current_key_id
        if next_match:
            return self.next_key_id
        return None

    def match_bootstrap_attestation(self, candidate: str) -> bool:
        if not self.bootstrap_attested or not _SHA256_RE.fullmatch(candidate):
            return False
        return hmac.compare_digest(candidate, self.bootstrap_sha256)


def is_autotutor_verification_principal(actor: Actor) -> bool:
    return bool(actor.actor_id and actor.actor_id.startswith(_MACHINE_ACTOR_PREFIX))


def autotutor_verification_principal_kind(actor: Actor) -> str:
    return "machine" if is_autotutor_verification_principal(actor) else "admin"


def require_autotutor_verifier(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
    bootstrap_sha256: str | None = Header(default=None, alias="X-AutoTutor-Bootstrap-SHA256"),
) -> Actor:
    """Accept the scoped machine token or a normal admin JWT."""
    if not auth_required():
        return Actor(actor_id="dev-admin", role="admin", traffic_cohort="demo")

    token = creds.credentials if creds else ""
    settings = AutoTutorVerificationIdentitySettings.from_env()
    key_id = settings.match_token(token)
    if key_id:
        if settings.required and not settings.match_bootstrap_attestation((bootstrap_sha256 or "").strip()):
            record_audit_event(
                actor_id=f"{_MACHINE_ACTOR_PREFIX}{key_id}",
                action="autotutor.verification.auth_failed",
                resource_type="autotutor_production_verification",
                success=False,
                metadata={"reason": "bootstrap_attestation_invalid", "principal_kind": "machine"},
            )
            raise HTTPException(status_code=403, detail="bootstrap_attestation_invalid")
        return Actor(
            actor_id=f"{_MACHINE_ACTOR_PREFIX}{key_id}",
            role="admin",
            account_status="active",
            traffic_cohort="operator",
        )

    try:
        actor = require_auth(creds)  # type: ignore[arg-type]
    except HTTPException as exc:
        record_audit_event(
            actor_id=None,
            action="autotutor.verification.auth_failed",
            resource_type="autotutor_production_verification",
            success=False,
            metadata={"reason": str(exc.detail), "principal_kind": "unknown"},
        )
        raise
    if actor.role != "admin":
        record_audit_event(
            actor_id=actor.actor_id,
            action="autotutor.verification.auth_failed",
            resource_type="autotutor_production_verification",
            success=False,
            metadata={"reason": "insufficient_role", "principal_kind": "jwt"},
        )
        raise HTTPException(status_code=403, detail="insufficient_role")
    return actor


@dataclass(frozen=True)
class AutoTutorVerificationTraffic:
    traffic_source: str = "organic"
    verification_run_id: str | None = None
    phase: str | None = None


def _traffic_secret(env: Mapping[str, str] | None = None) -> bytes:
    source = os.environ if env is None else env
    secret = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_TRAFFIC_SECRET", ""))
    if len(secret) < _MIN_TOKEN_LENGTH:
        raise ValueError("verification_traffic_secret_missing")
    return secret.encode("utf-8")


def _allowed_verification_students(env: Mapping[str, str] | None = None) -> set[str]:
    source = os.environ if env is None else env
    raw = str(source.get("EDU_AGENT_AUTOTUTOR_VERIFICATION_STUDENT_IDS", ""))
    return {value.strip() for value in raw.split(",") if value.strip()}


def _encode_traffic_token(payload: dict[str, object], secret: bytes) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return _TRAFFIC_TOKEN_PREFIX + base64.urlsafe_b64encode(raw + signature).decode("ascii").rstrip("=")


def _decode_traffic_token(token: str, secret: bytes) -> dict[str, object]:
    if not token.startswith(_TRAFFIC_TOKEN_PREFIX):
        raise ValueError("verification_attestation_invalid")
    encoded = token.removeprefix(_TRAFFIC_TOKEN_PREFIX)
    encoded += "=" * (-len(encoded) % 4)
    try:
        packed = base64.urlsafe_b64decode(encoded.encode("ascii"))
        if len(packed) <= hashlib.sha256().digest_size:
            raise ValueError("verification_attestation_invalid")
        raw = packed[:-hashlib.sha256().digest_size]
        signature = packed[-hashlib.sha256().digest_size:]
        expected = hmac.new(secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("verification_attestation_invalid")
        payload = json.loads(raw)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("verification_attestation_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("verification_attestation_invalid")
    return payload


def issue_autotutor_verification_traffic_token(
    *,
    actor_id: str,
    verification_run_id: str,
    phase: str,
    deployed_commit: str,
    config_version: str,
    ttl_seconds: int = 300,
    nonce: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Create a short-lived, one-request attestation for a dedicated student."""
    if not _VERIFICATION_RUN_RE.fullmatch(verification_run_id):
        raise ValueError("verification_run_id_invalid")
    if phase not in _VALID_VERIFICATION_PHASES:
        raise ValueError("verification_phase_invalid")
    if actor_id not in _allowed_verification_students(env):
        raise ValueError("verification_actor_not_allowlisted")
    now = int(time.time())
    payload: dict[str, object] = {
        "v": 1,
        "actor_id": actor_id,
        "verification_run_id": verification_run_id,
        "phase": phase,
        "deployed_commit": deployed_commit,
        "config_version": config_version,
        "iat": now,
        "exp": now + max(1, min(int(ttl_seconds), 900)),
        "nonce": nonce or uuid4().hex,
    }
    return _encode_traffic_token(payload, _traffic_secret(env))


def _consume_verification_nonce(payload: dict[str, object]) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from agent_runtime.event_store import ensure_runtime_tables
    from db.engine import get_connection

    nonce = str(payload["nonce"])
    nonce_sha256 = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    actor_sha256 = hashlib.sha256(str(payload["actor_id"]).encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc).isoformat()
    ensure_runtime_tables()
    try:
        with get_connection() as conn:
            conn.execute(text("DELETE FROM autotutor_verification_nonces WHERE expires_at<:now"), {"now": now_iso})
            conn.execute(text("""INSERT INTO autotutor_verification_nonces (
                nonce_sha256, verification_run_id, actor_id_sha256, expires_at, created_at
            ) VALUES (:nonce, :run_id, :actor, :expires, :created)"""), {
                "nonce": nonce_sha256,
                "run_id": str(payload["verification_run_id"]),
                "actor": actor_sha256,
                "expires": expires_iso,
                "created": now_iso,
            })
    except IntegrityError as exc:
        raise ValueError("verification_attestation_replayed") from exc


def resolve_autotutor_verification_traffic(
    *,
    actor: Actor,
    verification_run_id: str | None,
    attestation: str | None,
    env: Mapping[str, str] | None = None,
) -> AutoTutorVerificationTraffic:
    """Validate optional controlled-traffic headers; ordinary requests stay organic."""
    # FastAPI dependency defaults remain Header objects when route functions are
    # invoked directly by smoke tests or internal callers.
    verification_run_id = verification_run_id if isinstance(verification_run_id, str) else None
    attestation = attestation if isinstance(attestation, str) else None
    if not verification_run_id and not attestation:
        return AutoTutorVerificationTraffic()
    if not verification_run_id or not attestation:
        raise HTTPException(status_code=403, detail="verification_headers_incomplete")
    try:
        payload = _decode_traffic_token(attestation, _traffic_secret(env))
        now = int(time.time())
        required = {"actor_id", "verification_run_id", "phase", "deployed_commit", "config_version", "iat", "exp", "nonce"}
        if not required.issubset(payload):
            raise ValueError("verification_attestation_invalid")
        if str(payload["verification_run_id"]) != verification_run_id or not _VERIFICATION_RUN_RE.fullmatch(verification_run_id):
            raise ValueError("verification_run_id_mismatch")
        if actor.role != "student" or actor.account_status != "active" or actor.traffic_cohort != "verified":
            raise ValueError("verification_actor_not_trusted")
        if actor.actor_id != str(payload["actor_id"]) or actor.actor_id not in _allowed_verification_students(env):
            raise ValueError("verification_actor_not_allowlisted")
        if int(payload["iat"]) > now + 30 or int(payload["exp"]) < now or int(payload["exp"]) - int(payload["iat"]) > 900:
            raise ValueError("verification_attestation_expired")
        phase = str(payload["phase"])
        if phase not in _VALID_VERIFICATION_PHASES:
            raise ValueError("verification_phase_invalid")
        from agents.autotutor_execution import AutoTutorExecutorSettings
        from deployment import deployed_commit, deployment_environment

        settings = AutoTutorExecutorSettings.from_env(env)
        if deployment_environment() != "production":
            raise ValueError("verification_environment_not_production")
        if payload["deployed_commit"] != deployed_commit() or payload["config_version"] != settings.config_version:
            raise ValueError("verification_deployment_mismatch")
        if phase == "canary" and not (settings.mode == "active_canary" and 1 <= settings.active_bps <= 100):
            raise ValueError("verification_phase_config_mismatch")
        if phase in {"control", "rollback"} and not (settings.mode == "legacy" and settings.active_bps == 0):
            raise ValueError("verification_phase_config_mismatch")
        _consume_verification_nonce(payload)
        record_audit_event(
            actor_id=actor.actor_id,
            action="autotutor.verification_traffic.allowed",
            resource_type="autotutor_verification_run",
            resource_id=hashlib.sha256(verification_run_id.encode("utf-8")).hexdigest()[:16],
            success=True,
            metadata={"phase": phase, "traffic_source": "release_verification"},
        )
        return AutoTutorVerificationTraffic("release_verification", verification_run_id, phase)
    except HTTPException:
        raise
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "verification_attestation_invalid"
        record_audit_event(
            actor_id=actor.actor_id,
            action="autotutor.verification_traffic.denied",
            resource_type="autotutor_verification_run",
            success=False,
            metadata={"reason": reason[:120]},
        )
        raise HTTPException(status_code=403, detail=reason) from exc
