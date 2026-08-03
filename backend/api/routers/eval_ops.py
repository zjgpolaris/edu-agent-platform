"""Eval 运维路由：/api/eval/*, /api/agent-ops/*, /api/agent-jobs/*"""
import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from security.auth import Actor, assert_student_access, require_auth
from security.audit_log import record_audit_event
from agent_ops import build_agent_ops_summary
from services.agent_job_service import create_job as create_agent_job, get_job as get_agent_job, request_cancel as cancel_agent_job
from security.auth import auth_required

router = APIRouter(tags=["eval_ops"])

_FAILURE_ACTIONS = {"tool.role_denied", "tool.denied", "tool.failed", "tool.confirmation_required", "guardrail.blocked"}
_SUITE_FOR_ACTION = {"tool.role_denied": "tool_registry_smoke", "tool.denied": "tool_registry_smoke", "tool.failed": "tool_registry_smoke", "tool.confirmation_required": "tool_registry_smoke", "guardrail.blocked": "learning_assistant_smoke"}
_DEFAULT_SUITE_FILES = {"tool_registry_smoke": "tool_registry_cases.json", "learning_assistant_smoke": "learning_assistant_cases.json", "history_character": "history_character_cases.json", "rag_retrieval_eval": "rag_retrieval_cases.json"}


def load_eval_runner():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    eval_dir = root / "eval"
    if str(eval_dir) not in sys.path:
        sys.path.insert(0, str(eval_dir))
    import run_core_evals
    return run_core_evals


def require_eval_actor(actor: Actor) -> None:
    if auth_required() and actor.role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="仅教师可访问")


class EvalRunRequest(BaseModel):
    suite: str | None = None
    quick: bool = True


class WeeklySummaryJobRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)


class SaveEvalCaseRequest(BaseModel):
    suite: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    case: dict


@router.get("/api/agent-ops/summary")
async def agent_ops_summary(limit: int = 100, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    return build_agent_ops_summary(limit=limit)


@router.get("/api/eval/suites")
async def eval_suites(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    return {"quick": runner.QUICK_SUITES, "core": runner.CORE_SUITES, "smoke": runner.SMOKE_SUITES, "suites": runner.list_suite_metadata()}


@router.get("/api/eval/latest")
async def eval_latest(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if not runner.LATEST_JSON.exists():
        raise HTTPException(status_code=404, detail="latest eval report not found")
    return json.loads(runner.LATEST_JSON.read_text(encoding="utf-8"))


@router.get("/api/eval/report/json")
async def eval_report_json(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if not runner.LATEST_JSON.exists():
        raise HTTPException(status_code=404, detail="latest eval report not found")
    return FileResponse(runner.LATEST_JSON, media_type="application/json", filename="eduagent-eval-latest.json")


@router.get("/api/eval/report/markdown")
async def eval_report_markdown(actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if not runner.LATEST_MD.exists():
        raise HTTPException(status_code=404, detail="latest eval report not found")
    return FileResponse(runner.LATEST_MD, media_type="text/markdown", filename="eduagent-eval-latest.md")


@router.post("/api/eval/run")
async def eval_run(req: EvalRunRequest, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if req.suite and req.suite not in ("quick", "all"):
        if req.suite not in runner.SUITE_FILES:
            raise HTTPException(status_code=400, detail=f"unknown suite: {req.suite}")
        names = [req.suite]
    elif req.suite == "all" or not req.quick:
        names = runner.CORE_SUITES
    else:
        names = runner.QUICK_SUITES
    results = []
    for name in names:
        try:
            results.append(await run_in_threadpool(runner.run_suite, name))
        except Exception as exc:
            results.append(runner.SuiteResult(name=name, command=[], returncode=1, duration_sec=0, stdout="", stderr="", passed_cases=0, failed_cases_count=1, total_cases=1, metrics={}, failed_cases=[], error=str(exc)))
    summary = runner.build_json_summary(results, include_output=True)
    runner.write_reports(summary)
    return summary


@router.get("/api/eval/run-stream")
async def eval_run_stream(suite: str = "quick", actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    if suite not in ("quick", "all") and suite not in runner.SUITE_FILES:
        raise HTTPException(status_code=400, detail=f"unknown suite: {suite}")
    names = runner.CORE_SUITES if suite == "all" else (runner.QUICK_SUITES if suite == "quick" else [suite])

    async def generate():
        yield f"data: {json.dumps({'type': 'start', 'total': len(names)})}\n\n"
        results = []
        for i, name in enumerate(names):
            yield f"data: {json.dumps({'type': 'running', 'suite': name, 'index': i})}\n\n"
            try:
                r = await run_in_threadpool(runner.run_suite, name)
                results.append(r)
                yield f"data: {json.dumps({'type': 'suite_done', 'suite': name, 'ok': r.ok, 'passed': r.passed_cases or 0, 'total': r.total_cases or 0, 'duration': round(r.duration_sec or 0, 2), 'index': i})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'suite_error', 'suite': name, 'error': str(exc), 'index': i})}\n\n"
        try:
            summary = runner.build_json_summary(results, include_output=True)
            runner.write_reports(summary)
            yield f"data: {json.dumps({'type': 'done', 'summary': summary})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'done_error', 'error': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/eval/history")
async def eval_history(limit: int = 20, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    history_dir = runner.REPORTS_DIR / "history"
    if not history_dir.exists():
        return {"snapshots": []}
    snapshots = []
    for f in sorted(history_dir.glob("*.json"))[-limit:]:
        try:
            snapshots.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"snapshots": snapshots}


@router.get("/api/eval/candidate-cases")
async def eval_candidate_cases(limit: int = 20, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    from security.audit_log import list_audit_events

    def _expected_error(action: str, error_code: str | None = None) -> str | None:
        if error_code:
            return error_code
        return {"tool.role_denied": "role_denied", "tool.confirmation_required": "confirmation_required", "tool.denied": "invalid_confirmation", "guardrail.blocked": "guardrail_blocked"}.get(action)

    def _draft_kind(suite: str) -> str:
        return "learning_assistant" if suite == "learning_assistant_smoke" else "tool_registry"

    def _missing(candidate: dict) -> list[str]:
        missing = []
        suite = candidate.get("suggested_suite") or _SUITE_FOR_ACTION.get(str(candidate.get("action", "")), "tool_registry_smoke")
        if _draft_kind(str(suite)) == "tool_registry":
            if not candidate.get("tool_name"):
                missing.append("tool_name")
            if not isinstance(candidate.get("payload"), dict):
                missing.append("payload")
            if not candidate.get("expected_error") and candidate.get("expected_ok") is None:
                missing.append("expected_error")
        else:
            payload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
            message = candidate.get("query") or payload.get("message")
            if not isinstance(message, str) or not message.strip():
                missing.append("message")
            if not candidate.get("expected_error"):
                missing.append("expected_error")
        return missing

    raw_events = list_audit_events(limit=200)
    candidates = []
    for ev in raw_events:
        action = ev.get("action", "")
        if action not in _FAILURE_ACTIONS:
            continue
        meta = ev.get("metadata") or {}
        input_summary = meta.get("input_summary")
        payload = input_summary if isinstance(input_summary, dict) else None
        suite = _SUITE_FOR_ACTION.get(action, "tool_registry_smoke")
        candidate = {
            "id": ev.get("id", ""), "source": "audit", "action": action, "actor_id": ev.get("actor_id", ""),
            "actor_role": meta.get("actor_role", "student"), "created_at": ev.get("created_at", ""),
            "trace_id": meta.get("trace_id", ""), "tool_name": meta.get("tool_name", ""),
            "error_code": meta.get("error_code", ""), "expected_error": _expected_error(action, meta.get("error_code") if isinstance(meta.get("error_code"), str) else None),
            "query": meta.get("query") or (payload.get("message") if isinstance(payload, dict) and isinstance(payload.get("message"), str) else json.dumps(payload, ensure_ascii=False) if payload else ""),
            "payload": payload, "suggested_suite": suite, "draft_kind": _draft_kind(suite),
        }
        missing = _missing(candidate)
        candidate["missing_fields"] = missing
        candidate["save_ready"] = not missing
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return {"candidates": candidates, "total": len(candidates)}


@router.post("/api/eval/save-case")
async def eval_save_case(req: SaveEvalCaseRequest, actor: Actor = Depends(require_auth)):
    require_eval_actor(actor)
    runner = load_eval_runner()
    datasets_dir = runner.LATEST_JSON.parent.parent / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    filename = _DEFAULT_SUITE_FILES.get(req.suite, f"{req.suite}_cases.json")
    target = datasets_dir / filename
    existing: list = []
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    if not isinstance(existing, list):
        existing = []
    # normalize and deduplicate (reuse logic inline)
    case = req.case
    fp_keys = {"tool_name", "actor_role", "expected_error", "expected_ok", "payload"} if req.suite != "learning_assistant_smoke" else {"message", "actor_role", "grade", "expected_error"}
    fingerprint = json.dumps({k: case.get(k) for k in fp_keys}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    deduplicated = any(isinstance(item, dict) and json.dumps({k: item.get(k) for k in fp_keys}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) == fingerprint for item in existing)
    if not deduplicated:
        existing.append(case)
        target.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    record_audit_event(actor_id=actor.actor_id, action="eval.case_saved", resource_type="eval", resource_id=req.suite, metadata={"name": req.name, "file": filename, "deduplicated": deduplicated, "saved": not deduplicated})
    return {"ok": True, "file": filename, "total": len(existing), "saved": not deduplicated, "deduplicated": deduplicated}


# ── Agent Jobs ─────────────────────────────────────────────────────────────────

@router.post("/api/agent-jobs/weekly-summary", status_code=202)
async def enqueue_weekly_summary_job(req: WeeklySummaryJobRequest, actor: Actor = Depends(require_auth)):
    import os
    assert_student_access(actor, req.student_id)
    trace_id = f"agent-job-{os.urandom(8).hex()}"
    return await run_in_threadpool(create_agent_job, "weekly_summary", {"student_id": req.student_id}, actor_id=actor.actor_id, idempotency_key=req.idempotency_key, trace_id=trace_id, max_attempts=3, timeout_seconds=120)


@router.get("/api/agent-jobs/{job_id}")
async def agent_job_status(job_id: str, actor: Actor = Depends(require_auth)):
    job = await run_in_threadpool(get_agent_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Agent job not found")
    if auth_required() and actor.role != "admin" and job.get("actor_id") != actor.actor_id:
        raise HTTPException(status_code=404, detail="Agent job not found")
    return job


@router.delete("/api/agent-jobs/{job_id}")
async def cancel_agent_job_endpoint(job_id: str, actor: Actor = Depends(require_auth)):
    existing = await run_in_threadpool(get_agent_job, job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent job not found")
    if auth_required() and actor.role != "admin" and existing.get("actor_id") != actor.actor_id:
        raise HTTPException(status_code=404, detail="Agent job not found")
    return await run_in_threadpool(cancel_agent_job, job_id)
