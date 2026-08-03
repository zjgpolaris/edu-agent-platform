"""认证路由：/api/auth/*"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from security.auth import create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6)
    display_name: str | None = None


@router.post("/login")
def auth_login(req: LoginRequest):
    from security.accounts import authenticate
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {
        "token": create_token(user["actor_id"], user["role"]),
        "role": user["role"],
        "actor_id": user["actor_id"],
        "display_name": user["display_name"],
    }


@router.post("/register")
def auth_register(req: RegisterRequest):
    from security.accounts import create_account
    try:
        create_account(req.student_id, req.student_id, req.password, "student", req.display_name)
    except Exception:
        raise HTTPException(status_code=409, detail="该学号已注册")
    return {"token": create_token(req.student_id, "student"), "role": "student", "actor_id": req.student_id}
