# 登录系统开发文档

## 概述

为 EduAgent 平台新增学生/老师两端登录系统，基于 JWT 认证。复用后端已有的 `Actor` 角色模型和 SQLite 数据库，前端通过全局 `AuthContext` 替换各页面散落的 `studentId` 输入框。

---

## 目标

1. 学生登录后全局持有身份，不再手动输入 student ID
2. 老师登录后可查看所有学生的学习数据
3. 后端 `assert_student_access()` 真正生效（开启 `EDU_AGENT_AUTH_REQUIRED=true`）

---

## 数据库变更

在现有 SQLite（`.data/edu_agent.sqlite3`）新增 `accounts` 表：

```sql
CREATE TABLE IF NOT EXISTS accounts (
  actor_id     TEXT PRIMARY KEY,
  username     TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,        -- bcrypt
  role         TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
  display_name TEXT,
  created_at   TEXT NOT NULL
);
```

- 学生账号：`actor_id = student_id`（与 `students` 表对齐）
- 老师/Admin 账号：`actor_id` 用 `teacher_<username>` 前缀

---

## 后端实现

### 1. 依赖

```
bcrypt>=4.0
pyjwt>=2.8
```

加入 `backend/requirements.txt`。

### 2. `backend/security/auth.py` 改动

新增函数，现有 `Actor`、`get_actor_from_request`、`assert_student_access` 不变：

```python
import bcrypt, jwt, os
from datetime import datetime, timedelta, timezone

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

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
```

修改 `get_actor_from_request`，优先从 `Authorization: Bearer` 解析 JWT：

```python
def get_actor_from_request(request: Request | None) -> Actor:
    if request is None:
        return Actor()
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_token(auth_header[7:])
            return Actor(actor_id=payload["sub"], role=payload["role"])
        except Exception:
            pass
    # 向后兼容旧 header
    actor_id = request.headers.get("x-edu-actor-id") or request.headers.get("x-student-id")
    role = request.headers.get("x-edu-role") or ("student" if actor_id else "anonymous")
    if role not in {"anonymous", "student", "teacher", "admin"}:
        role = "anonymous"
    return Actor(actor_id=actor_id, role=role)
```

### 3. `backend/security/accounts.py`（新文件）

```python
from __future__ import annotations
import sqlite3
from student_profile import db_path, init_db, now_iso
from security.auth import hash_password, verify_password

def _connect():
    import sqlite3
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn

def init_accounts_table():
    init_db()
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
              actor_id TEXT PRIMARY KEY,
              username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
              display_name TEXT,
              created_at TEXT NOT NULL
            )
        """)

def create_account(actor_id: str, username: str, password: str, role: str, display_name: str | None = None):
    init_accounts_table()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO accounts (actor_id, username, password_hash, role, display_name, created_at) VALUES (?,?,?,?,?,?)",
            (actor_id, username, hash_password(password), role, display_name, now_iso()),
        )

def authenticate(username: str, password: str) -> dict | None:
    init_accounts_table()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return {"actor_id": row["actor_id"], "role": row["role"], "display_name": row["display_name"]}
    return None

def list_students() -> list[dict]:
    init_accounts_table()
    with _connect() as conn:
        rows = conn.execute("SELECT actor_id, display_name FROM accounts WHERE role='student'").fetchall()
    return [dict(r) for r in rows]
```

### 4. 新增 API 路由（`backend/api/main.py`）

**登录接口（学生 + 老师共用）：**

```python
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
def login(req: LoginRequest):
    from security.accounts import authenticate
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user["actor_id"], user["role"])
    return {"token": token, "role": user["role"], "actor_id": user["actor_id"], "display_name": user["display_name"]}
```

**学生自助注册（可选，内测阶段可关闭）：**

```python
class RegisterRequest(BaseModel):
    student_id: str
    password: str
    display_name: str | None = None

@app.post("/api/auth/register")
def register_student(req: RegisterRequest):
    from security.accounts import create_account
    try:
        create_account(req.student_id, req.student_id, req.password, "student", req.display_name)
    except Exception:
        raise HTTPException(status_code=409, detail="该学号已注册")
    token = create_token(req.student_id, "student")
    return {"token": token, "role": "student", "actor_id": req.student_id}
```

**老师端接口（需 teacher/admin 角色）：**

```python
def require_teacher(request: Request):
    actor = get_actor_from_request(request)
    if actor.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师可访问")
    return actor

@app.get("/api/teacher/students")
def teacher_list_students(request: Request):
    require_teacher(request)
    from security.accounts import list_students
    return list_students()

@app.get("/api/teacher/students/{student_id}/profile")
def teacher_student_profile(student_id: str, request: Request):
    require_teacher(request)
    return get_student_profile(student_id)

@app.get("/api/teacher/students/{student_id}/events")
def teacher_student_events(student_id: str, request: Request, limit: int = 50):
    require_teacher(request)
    from student_profile import init_db, _connect
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM learning_events WHERE student_id=? ORDER BY created_at DESC LIMIT ?",
            (student_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]
```

### 5. 环境变量

```env
JWT_SECRET=<随机长字符串>
EDU_AGENT_AUTH_REQUIRED=true   # 上线时开启
```

---

## 前端实现

### 1. `frontend/lib/auth.ts`（新文件）

```typescript
export interface AuthUser {
  actorId: string;
  role: "student" | "teacher" | "admin";
  displayName?: string;
  token: string;
}

const KEY = "edu_auth";

export function saveAuth(user: AuthUser) {
  localStorage.setItem(KEY, JSON.stringify(user));
}

export function loadAuth(): AuthUser | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearAuth() {
  localStorage.removeItem(KEY);
}

export function authHeaders(token: string) {
  return { Authorization: `Bearer ${token}` };
}
```

### 2. `frontend/contexts/AuthContext.tsx`（新文件）

```typescript
"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { AuthUser, loadAuth, saveAuth, clearAuth } from "@/lib/auth";

interface AuthContextValue {
  user: AuthUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({} as AuthContextValue);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    setUser(loadAuth());
  }, []);

  async function login(username: string, password: string) {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new Error("用户名或密码错误");
    const data = await res.json();
    const auth: AuthUser = { actorId: data.actor_id, role: data.role, displayName: data.display_name, token: data.token };
    saveAuth(auth);
    setUser(auth);
  }

  function logout() {
    clearAuth();
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
```

### 3. `frontend/app/layout.tsx` 包裹 Provider

```typescript
import { AuthProvider } from "@/contexts/AuthContext";

export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
```

### 4. `frontend/app/login/page.tsx`（新页面）

学生和老师共用同一登录页，登录后按 `role` 跳转：
- `student` → `/`（学习中心）
- `teacher` / `admin` → `/teacher/dashboard`

```typescript
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await login(username, password);
      const role = JSON.parse(localStorage.getItem("edu_auth")!).role;
      router.push(role === "student" ? "/" : "/teacher/dashboard");
    } catch {
      setError("用户名或密码错误");
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>EduAgent 登录</h1>
      <input placeholder="用户名 / 学号" value={username} onChange={e => setUsername(e.target.value)} />
      <input type="password" placeholder="密码" value={password} onChange={e => setPassword(e.target.value)} />
      {error && <p>{error}</p>}
      <button type="submit">登录</button>
    </form>
  );
}
```

### 5. 各页面去掉 studentId 输入框

将各页面中手动维护 `studentId` 的逻辑改为从 `useAuth()` 读取，示例：

```typescript
// 改前
const [studentId, setStudentId] = useState("");
// ...
<input placeholder="student_001" value={studentId} onChange={...} />

// 改后
const { user } = useAuth();
const studentId = user?.actorId ?? "";
```

涉及文件：
- `app/essay-grade/page.tsx`
- `app/quiz-practice/page.tsx`
- `app/history-games/timeline/TimelineGameClient.tsx`
- `app/history-games/card-game/CardGameClient.tsx`
- `app/history-games/multiplayer/MultiplayerGameClient.tsx`
- `app/learning-assistant/page.tsx`
- `app/student-dashboard/page.tsx`

### 6. `frontend/app/teacher/dashboard/page.tsx`（新页面）

老师端展示学生列表，点击进入学生详情（复用 `/student-dashboard` 逻辑）：

```typescript
"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { authHeaders } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function TeacherDashboard() {
  const { user } = useAuth();
  const [students, setStudents] = useState<{ actor_id: string; display_name: string }[]>([]);

  useEffect(() => {
    if (!user?.token) return;
    fetch(`${API}/api/teacher/students`, { headers: authHeaders(user.token) })
      .then(r => r.json())
      .then(setStudents);
  }, [user]);

  return (
    <div>
      <h1>班级学情总览</h1>
      <ul>
        {students.map(s => (
          <li key={s.actor_id}>
            <a href={`/teacher/students/${s.actor_id}`}>{s.display_name || s.actor_id}</a>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

---

## 实施步骤

| 步骤 | 内容 | 优先级 |
|------|------|--------|
| 1 | 后端：安装 `bcrypt`/`pyjwt`，新建 `accounts.py`，修改 `auth.py` | 必须 |
| 2 | 后端：在 `main.py` 注册 `/api/auth/login`、`/api/auth/register` | 必须 |
| 3 | 前端：新建 `lib/auth.ts`、`contexts/AuthContext.tsx`，接入 `layout.tsx` | 必须 |
| 4 | 前端：新建 `/login` 页 | 必须 |
| 5 | 前端：各页面改读 `useAuth().user.actorId` | 必须 |
| 6 | 后端：新增老师端 3 个 API | 老师功能 |
| 7 | 前端：新建 `/teacher/dashboard` 和 `/teacher/students/[id]` | 老师功能 |
| 8 | 设置 `EDU_AGENT_AUTH_REQUIRED=true`，验证权限拦截 | 上线前 |

---

## 初始账号创建

开发期通过脚本建账号，无需管理 UI：

```python
# scripts/create_accounts.py
from security.accounts import create_account

create_account("teacher_zhang", "teacher_zhang", "teacher123", "teacher", "张老师")
create_account("student_001", "student_001", "student123", "student", "李明")
```

```bash
PYTHONPATH=backend python3 scripts/create_accounts.py
```

---

## 安全注意事项

- `JWT_SECRET` 必须从环境变量读取，不得硬编码
- 登录接口加限速（可用 `slowapi`），防暴力破解
- Token 有效期 72 小时，无刷新 token（内测阶段够用）
- 老师端 API 全部校验 `role in {teacher, admin}`，不依赖前端路由保护
