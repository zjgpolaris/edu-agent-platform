from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_TRUE_VALUES = {"1", "true", "yes", "on"}

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

_bearer = HTTPBearer(auto_error=False)


class Actor(BaseModel):
    actor_id: str | None = None
    role: Literal["anonymous", "student", "teacher", "admin"] = "anonymous"
    account_status: Literal["anonymous", "active", "disabled"] = "active"
    traffic_cohort: Literal["anonymous", "demo", "unverified", "verified", "operator"] = "unverified"

    @property
    def rollout_eligible(self) -> bool:
        return self.account_status == "active" and self.traffic_cohort == "verified"


def _deployment_environment() -> str:
    from deployment import deployment_environment

    return deployment_environment()


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if secret:
        return secret
    if _deployment_environment() == "production":
        raise RuntimeError("JWT_SECRET is required in production")
    return "change-me-in-production"


def auth_required() -> bool:
    if _deployment_environment() == "production":
        return True
    enabled = os.getenv("EDU_AGENT_AUTH_REQUIRED", "false").strip().lower() in _TRUE_VALUES
    if not enabled:
        import logging
        logging.getLogger(__name__).warning("EDU_AGENT_AUTH_REQUIRED is not set — authentication is DISABLED")
    return enabled


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(actor_id: str, role: str, *, expires_hours: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    ttl = expires_hours if expires_hours is not None else (1 if role == "admin" else JWT_EXPIRE_HOURS)
    payload = {
        "sub": actor_id,
        "role": role,
        "iat": now,
        "jti": uuid4().hex,
        "exp": now + timedelta(hours=max(1, min(int(ttl), JWT_EXPIRE_HOURS))),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])


def _database_authority_required() -> bool:
    return _deployment_environment() == "production" or os.getenv("EDU_AGENT_AUTH_DB_AUTHORITY", "false").strip().lower() in _TRUE_VALUES


def _actor_from_payload(payload: dict) -> Actor:
    actor_id = str(payload.get("sub") or "")
    role = str(payload.get("role") or "")
    if not actor_id or role not in {"student", "teacher", "admin"}:
        raise jwt.InvalidTokenError("invalid actor claims")
    if _database_authority_required():
        from security.accounts import get_account

        account = get_account(actor_id)
        if not account or account.get("account_status") != "active":
            raise HTTPException(status_code=401, detail="account_inactive")
        return Actor(
            actor_id=actor_id,
            role=account["role"],
            account_status=account["account_status"],
            traffic_cohort=account["traffic_cohort"],
        )
    return Actor(actor_id=actor_id, role=role)  # type: ignore[arg-type]


def get_actor_from_request(request: Request | None) -> Actor:
    if request is None:
        return Actor(account_status="anonymous", traffic_cohort="anonymous")
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_token(auth_header[7:])
            return _actor_from_payload(payload)
        except Exception:
            pass
    return Actor(account_status="anonymous", traffic_cohort="anonymous")


def assert_student_access(actor: Actor, student_id: str) -> None:
    if not auth_required():
        return
    if actor.role in {"teacher", "admin"}:
        return
    if actor.role == "student" and actor.actor_id == student_id:
        return
    raise HTTPException(status_code=403, detail="无权访问该学生数据。")


def teacher_has_student_access(teacher_id: str | None, student_id: str) -> bool:
    """Use existing assignment ownership as the current class-membership boundary."""
    if not teacher_id:
        return False
    try:
        from sqlalchemy import inspect as sa_inspect, text
        from db.engine import get_connection

        with get_connection() as conn:
            if "assignments" not in set(sa_inspect(conn).get_table_names()):
                return False
            rows = conn.execute(
                text("SELECT assignee_ids_json FROM assignments WHERE teacher_id=:teacher_id"),
                {"teacher_id": teacher_id},
            ).scalars().all()
        return any(student_id in (json.loads(value or "[]") if isinstance(value, str) else []) for value in rows)
    except Exception:
        return False


def assert_teacher_student_access(actor: Actor, student_id: str, *, resource_owner_id: str | None = None) -> None:
    if not auth_required() or actor.role == "admin":
        return
    if actor.role == "teacher" and (
        (resource_owner_id and actor.actor_id == resource_owner_id)
        or teacher_has_student_access(actor.actor_id, student_id)
    ):
        return
    raise HTTPException(status_code=403, detail="教师无权访问该学生或班级资源。")


def require_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)) -> Actor:
    """Require valid JWT token. Returns Actor if valid, raises 401 if invalid."""
    if not auth_required():
        return Actor(actor_id="dev-teacher", role="teacher", traffic_cohort="demo")

    token = creds.credentials if creds else None
    if not token:
        raise HTTPException(status_code=401, detail="missing_authorization_token")

    try:
        return _actor_from_payload(decode_token(token))
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")


def require_teacher(actor: Actor = Depends(require_auth)) -> Actor:
    if actor.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="insufficient_role")
    return actor


def require_admin(actor: Actor = Depends(require_auth)) -> Actor:
    if not auth_required():
        return Actor(actor_id="dev-admin", role="admin", traffic_cohort="demo")
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="insufficient_role")
    return actor
