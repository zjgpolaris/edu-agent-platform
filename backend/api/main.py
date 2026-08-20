"""FastAPI 入口 — 挂载所有 APIRouter 子模块"""
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from game_store import init_db
from materials.store import init_material_store
from agent_job_worker import worker_loop as agent_job_worker_loop
from tracing import safe_shutdown
from contextlib import asynccontextmanager

# ── 子路由导入 ─────────────────────────────────────────────────────────────────
from api.routers.auth import router as auth_router
from api.routers.debug import router as debug_router
from api.routers.teacher import router as teacher_router
from api.routers.students import router as students_router
from api.routers.history import router as history_router
from api.routers.chinese import router as chinese_router
from api.routers.textbook import router as textbook_router
from api.routers.materials import router as materials_router
from api.routers.homework import router as homework_router
from api.routers.learning import router as learning_router
from api.routers.review_checkin import router as review_router
from api.routers.assignments import router as assignments_router
from api.routers.eval_ops import router as eval_ops_router
from api.routers.agent_runtime import router as agent_runtime_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_material_store()
    job_worker_stop = asyncio.Event()
    job_worker_task = asyncio.create_task(agent_job_worker_loop(job_worker_stop))
    try:
        yield
    finally:
        job_worker_stop.set()
        await job_worker_task
        safe_shutdown()


app = FastAPI(title="EduAgent API", lifespan=lifespan)

_default_origins = [
    "http://localhost:3000", "http://localhost:3001", "http://localhost:5173",
    "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:5173",
]
_extra_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*_default_origins, *_extra_origins],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 挂载路由 ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(debug_router)
app.include_router(teacher_router)
app.include_router(students_router)
app.include_router(history_router)
app.include_router(chinese_router)
app.include_router(textbook_router)
app.include_router(materials_router)
app.include_router(homework_router)
app.include_router(learning_router)
app.include_router(review_router)
app.include_router(assignments_router)
app.include_router(eval_ops_router)
app.include_router(agent_runtime_router)
