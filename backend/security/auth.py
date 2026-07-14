from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_TRUE_VALUES = {"1", "true", "yes", "on"}

JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    import warnings
    warnings.warn(
        "JWT_SECRET environment variable is not set. Using an insecure default. Set JWT_SECRET in production.",
        RuntimeWarning,
        stacklevel=2,
    )
    JWT_SECRET = "change-me-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

_bearer = HTTPBearer(auto_error=False)


class Actor(BaseModel):
    actor_id: str | None = None
    role: Literal["anonymous", "student", "teacher", "admin"] = "anonymous"


def auth_required() -> bool:
    enabled = os.getenv("EDU_AGENT_AUTH_REQUIRED", "false").strip().lower() in _TRUE_VALUES
    if not enabled:
        import logging
        logging.getLogger(__name__).warning("EDU_AGENT_AUTH_REQUIRED is not set — authentication is DISABLED")
    return enabled


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(actor_id: str, role: str) -> str:
    payload = {
        "sub": actor_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def get_actor_from_request(request: Request | None) -> Actor:
    if request is None:
        return Actor()
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_token(auth_header[7:])
            return Actor(actor_id=payload["sub"], role=payload["role"])  # type: ignore[arg-type]
        except Exception:
            pass
    return Actor()


def assert_student_access(actor: Actor, student_id: str) -> None:
    if not auth_required():
        return
    if actor.role in {"teacher", "admin"}:
        return
    if actor.role == "student" and actor.actor_id == student_id:
        return
    raise HTTPException(status_code=403, detail="无权访问该学生数据。")


def require_auth(creds: HTTPAuthorizationCredentials = Security(_bearer)) -> Actor:
    """Require valid JWT token. Returns Actor if valid, raises 401 if invalid."""
    if not auth_required():
        return Actor(actor_id="dev-teacher", role="teacher")

    token = creds.credentials if creds else None
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    try:
        payload = decode_token(token)
        return Actor(actor_id=payload["sub"], role=payload["role"])  # type: ignore[arg-type]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed")
