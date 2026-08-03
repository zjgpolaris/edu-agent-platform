"""资料库路由：/api/materials/*"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from security.auth import Actor, require_auth
from security.audit_log import record_audit_event
from security.rate_limit import check_rate_limit
from materials.schema import MaterialGenerateRequest, MaterialQuestionRequest, MaterialSaveRequest
from materials.service import MaterialSetupError, analyze_material, answer_material_question, delete_saved_material, get_saved_material, list_saved_materials, parse_material_bytes, save_material_for_rag
from materials.store import MaterialNotFoundError, resolve_owner_key
from tracing import trace_context
from ._shared import trace_meta

router = APIRouter(prefix="/api/materials", tags=["materials"])


@router.post("/parse")
async def parse_material(file: UploadFile = File(...), grade: str | None = Form(None), subject: str | None = Form(None), ocr_mode: str = Form("auto"), preprocess: bool = Form(True), actor: Actor = Depends(require_auth)):
    check_rate_limit(f"materials-parse:{actor.actor_id}", limit=30, window_seconds=3600)
    record_audit_event(actor_id=actor.actor_id, action="materials.parse", metadata={"filename": file.filename, "content_type": file.content_type, "grade": grade, "subject": subject, "ocr_mode": ocr_mode, "preprocess": preprocess})
    data = await file.read()
    with trace_context(name="POST /api/materials/parse", metadata=trace_meta("materials_parse", "/api/materials/parse", filename=file.filename, content_type=file.content_type, grade=grade, subject=subject, ocr_mode=ocr_mode, preprocess=preprocess, bytes=len(data), stream=False), user_id=actor.actor_id):
        try:
            result = await run_in_threadpool(parse_material_bytes, file.filename or "uploaded-material", file.content_type or "", data, ocr_mode=ocr_mode, preprocess=preprocess)
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MaterialSetupError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze")
async def material_analyze(req: MaterialGenerateRequest, actor: Actor = Depends(require_auth)):
    check_rate_limit(f"materials-analyze:{actor.actor_id}", limit=20, window_seconds=3600)
    record_audit_event(actor_id=actor.actor_id, action="materials.analyze", metadata={"grade": req.grade, "subject": req.subject, "task": req.task, "chars": len(req.text)})
    with trace_context(name="POST /api/materials/analyze", metadata=trace_meta("materials_analyze", "/api/materials/analyze", grade=req.grade, subject=req.subject, task=req.task, chars=len(req.text), stream=False), user_id=actor.actor_id, input_data={"text": req.text[:1200]}):
        try:
            result = await run_in_threadpool(analyze_material, req)
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="生成失败，请稍后重试或缩短文本后再试") from exc


@router.post("/save")
async def material_save(req: MaterialSaveRequest, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-save:{owner_key}", limit=20, window_seconds=3600)
    with trace_context(name="POST /api/materials/save", metadata=trace_meta("materials_save", "/api/materials/save", title=req.title, filename=req.filename, source_type=req.source_type, grade=req.grade, subject=req.subject, chars=len(req.text), pages=len(req.pages), stream=False), user_id=actor.actor_id or owner_key):
        try:
            result = await run_in_threadpool(save_material_for_rag, req, owner_key)
            record_audit_event(actor_id=actor.actor_id, action="materials.save", resource_type="material", resource_id=result.material_id, metadata={"title": result.title, "chars": result.text_chars, "pages": result.page_count, "chunks": result.chunk_count})
            return result.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="资料保存失败，请稍后重试") from exc


@router.get("")
async def material_list(request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-list:{owner_key}", limit=120, window_seconds=3600)
    materials = await run_in_threadpool(list_saved_materials, owner_key)
    return {"materials": [item.model_dump() for item in materials]}


@router.get("/{material_id}")
async def material_detail(material_id: str, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    try:
        result = await run_in_threadpool(get_saved_material, owner_key, material_id)
        return result.model_dump()
    except MaterialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{material_id}/ask")
async def material_ask(material_id: str, req: MaterialQuestionRequest, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-ask:{owner_key}", limit=60, window_seconds=3600)
    with trace_context(name="POST /api/materials/{material_id}/ask", metadata=trace_meta("materials_ask", "/api/materials/{material_id}/ask", material_id=material_id, question_chars=len(req.question), k=req.k, stream=False), user_id=actor.actor_id or owner_key, input_data={"question": req.question}):
        try:
            result = await run_in_threadpool(answer_material_question, owner_key, material_id, req)
            record_audit_event(actor_id=actor.actor_id, action="materials.ask", resource_type="material", resource_id=material_id, metadata={"question_chars": len(req.question), "sources": len(result.sources)})
            return result.model_dump()
        except MaterialNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="资料问答失败，请稍后重试") from exc


@router.delete("/{material_id}")
async def material_delete(material_id: str, request: Request, actor: Actor = Depends(require_auth)):
    owner_key = resolve_owner_key(request, actor)
    check_rate_limit(f"materials-delete:{owner_key}", limit=30, window_seconds=3600)
    try:
        await run_in_threadpool(delete_saved_material, owner_key, material_id)
        record_audit_event(actor_id=actor.actor_id, action="materials.delete", resource_type="material", resource_id=material_id)
        return {"ok": True}
    except MaterialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
