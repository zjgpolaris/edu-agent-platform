from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from services.agent_job_service import execute_job, list_pending_jobs, recover_stale_jobs
from services.weekly_summary_service import build_weekly_summary
from trace_store import trace_context

logger = logging.getLogger(__name__)


def _weekly_summary(payload: dict[str, Any]) -> dict[str, Any]:
    student_id = payload.get("student_id")
    if not isinstance(student_id, str) or not student_id:
        raise ValueError("weekly_summary job requires student_id")
    return build_weekly_summary(student_id)


JOB_HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "weekly_summary": _weekly_summary,
}


def run_registered_job(job: dict[str, Any]) -> dict[str, Any]:
    handler = JOB_HANDLERS.get(job["job_type"])
    if handler is None:
        return execute_job(job["id"], lambda _: (_ for _ in ()).throw(ValueError("unknown job type")))
    trace_id = job.get("trace_id") or f"agent-job-{job['id']}"
    with trace_context(trace_id):
        return execute_job(job["id"], handler)


async def worker_loop(stop: asyncio.Event, *, poll_seconds: float = 1.0) -> None:
    stale_before = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await asyncio.to_thread(recover_stale_jobs, stale_before)
    while not stop.is_set():
        jobs = await asyncio.to_thread(list_pending_jobs, 10)
        for job in jobs:
            if stop.is_set():
                break
            try:
                await asyncio.to_thread(run_registered_job, job)
            except Exception:
                logger.exception("agent_job_worker_failed job_id=%s", job.get("id"))
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            pass
