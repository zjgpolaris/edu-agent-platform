"""Least-privilege machine identity for AutoTutor production verification."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from typing import Mapping

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
