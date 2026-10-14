from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .file_service import FILE_STORE_DIR, InvalidStoredUpload, store_upload
from .models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeFigure, KnowledgePage, KnowledgeTable, Publication, PublicationSource, TaskEvent, TaskFile, User, WorkspaceFile, WorkspaceTask
from .paper_pipeline import answer_question
from .permissions import has_permission
from .publication_service import ADAPTERS, publication_to_dict, search_publications, upsert_search_results
from .space_energy_catalog import SpaceEnergyCatalogError, connection_status as space_energy_connection_status, get_literature as get_space_energy_literature, list_literatures as list_space_energy_literatures
from .security import current_user, require_permission
from .task_service import create_task, link_file, submit_task, task_to_dict

router = APIRouter(prefix="/api", tags=["V4.2 Literature & Knowledge System"])


class LiteratureSearchPayload(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    sources: list[str] = Field(default_factory=lambda: ["space_energy", "openalex", "crossref"])
    year_from: int | None = None
    year_to: int | None = None
    open_access: bool | None = None
    language: str | None = None
    limit: int = Field(default=15, ge=1, le=50)


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    scope_type: str = Field(default="personal")
    description: str = Field(default="", max_length=4000)
    allow_team_search: bool = False
    allow_ai: bool = True
    allow_export: bool = True
    retain_original: bool = True


class QAPayload(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _ensure_personal_kb(db: Session, user: User) -> KnowledgeBase:
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.owner_user_id == user.id, KnowledgeBase.scope_type == "personal").order_by(KnowledgeBase.id))
    if kb:
        return kb
    kb = KnowledgeBase(name=f"{user.display_name}的个人知识库", scope_type="personal", owner_user_id=user.id, description="自动创建的个人论文知识库", allow_team_search=False, allow_ai=True, allow_export=True, retain_original=True)
    db.add(kb); db.commit(); db.refresh(kb)
    return kb


def _kb_access(kb: KnowledgeBase, user: User, *, manage: bool = False) -> bool:
    if kb.owner_user_id == user.id:
        return has_permission(user.role, "knowledge.own.manage")
    if user.role == "system_admin":
        return True
    if manage:
        return has_permission(user.role, "knowledge.enterprise.manage")
    return bool(kb.allow_team_search and has_permission(user.role, "knowledge.shared.search"))


def _document_access(db: Session, document_id: int, user: User, *, manage: bool = False) -> KnowledgeDocument:
    doc = db.get(KnowledgeDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    kb = db.get(KnowledgeBase, doc.knowledge_base_id) if doc.knowledge_base_id else None
    if doc.owner_user_id != user.id and not (kb and _kb_access(kb, user, manage=manage)) and user.role != "system_admin":
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@router.post("/literature/search")
def multi_source_literature_search(payload: LiteratureSearchPayload, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        result = search_publications(payload.query, sources=payload.sources, limit=payload.limit, year_from=payload.year_from, year_to=payload.year_to, open_access=payload.open_access, language=payload.language)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    saved = upsert_search_results(db, result)
    result["saved_publication_ids"] = [row.id for row in saved]
    write_audit(db, action="literature.multi_source.searched", resource_type="publication", actor=user, details={"query": payload.query, "sources": payload.sources, "raw_count": result["raw_count"], "deduplicated_count": result["deduplicated_count"]}, **_meta(request))
    return result


@router.get("/literature/publications")
def list_publications(q: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Browse the live canonical catalog; never fall back to the local publication cache."""
    try:
        result = list_space_energy_literatures(db, q=q, limit=limit, offset=offset)
    except SpaceEnergyCatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@router.get("/literature/central/status")
def central_literature_status(_: User = Depends(current_user)):
    return space_energy_connection_status()


@router.get("/literature/publications/{publication_id}")
def get_publication(publication_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    try:
        item = get_space_energy_literature(db, publication_id)
    except SpaceEnergyCatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="论文主库中未找到该论文")
    return item


def _live_related(db: Session, publication_id: int, method: str, limit: int) -> dict[str, Any]:
    row = db.get(Publication, publication_id)
    if not row: raise HTTPException(status_code=404, detail="publication not found")
    source_rows = db.scalars(select(PublicationSource).where(PublicationSource.publication_id == row.id).order_by(PublicationSource.id)).all()
    errors = []
    for source in source_rows:
        adapter = ADAPTERS.get(source.source_name.lower())
        if not adapter: continue
        identifier = row.doi or source.source_record_id
        try:
            value = getattr(adapter, method)(identifier, limit=limit) if method in {"get_citations", "get_references"} else getattr(adapter, method)(identifier)
            return {"source": source.source_name, "items": value if isinstance(value, list) else value}
        except Exception as exc:
            errors.append(f"{source.source_name}: {exc}")
    raise HTTPException(status_code=502, detail="; ".join(errors) or "没有可用来源适配器")


@router.get("/literature/publications/{publication_id}/citations")
def publication_citations(publication_id: int, limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _live_related(db, publication_id, "get_citations", limit)


@router.get("/literature/publications/{publication_id}/references")
def publication_references(publication_id: int, limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _live_related(db, publication_id, "get_references", limit)


@router.get("/literature/publications/{publication_id}/fulltext")
def publication_fulltext(publication_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _live_related(db, publication_id, "get_fulltext_link", 1)


@router.get("/literature/authors/{source}/{identifier:path}")
def literature_author(source: str, identifier: str, _: User = Depends(current_user)):
    adapter = ADAPTERS.get(source.lower())
    if not adapter: raise HTTPException(status_code=404, detail="unknown source adapter")
    try: return adapter.get_author(identifier)
    except Exception as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/knowledge/bases")
def list_knowledge_bases(db: Session = Depends(get_db), user: User = Depends(current_user)):
    _ensure_personal_kb(db, user)
    stmt = select(KnowledgeBase).where(or_(KnowledgeBase.owner_user_id == user.id, KnowledgeBase.allow_team_search.is_(True))).order_by(KnowledgeBase.id)
    rows = [kb for kb in db.scalars(stmt).all() if _kb_access(kb, user, manage=False)]
    return [{"id": kb.id, "name": kb.name, "scope_type": kb.scope_type, "owner_user_id": kb.owner_user_id, "description": kb.description, "allow_team_search": kb.allow_team_search, "allow_ai": kb.allow_ai, "allow_export": kb.allow_export, "retain_original": kb.retain_original} for kb in rows]


@router.post("/knowledge/bases")
def create_knowledge_base(payload: KnowledgeBaseCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("knowledge.own.manage"))):
    if payload.scope_type not in {"personal", "group", "project", "enterprise", "public_terms"}:
        raise HTTPException(status_code=400, detail="无效知识库层级")
    if payload.scope_type in {"enterprise", "public_terms"} and not has_permission(user.role, "knowledge.enterprise.manage"):
        raise HTTPException(status_code=403, detail="当前角色不能创建企业/公共知识库")
    kb = KnowledgeBase(name=payload.name, scope_type=payload.scope_type, owner_user_id=user.id, description=payload.description, allow_team_search=payload.allow_team_search, allow_ai=payload.allow_ai, allow_export=payload.allow_export, retain_original=payload.retain_original)
    db.add(kb); db.commit(); db.refresh(kb)
    write_audit(db, action="knowledge_base.created", resource_type="knowledge_base", resource_id=kb.id, actor=user, details=payload.model_dump(), **_meta(request))
    return {"id": kb.id, **payload.model_dump(), "owner_user_id": user.id}


@router.post("/knowledge/documents/upload", status_code=202)
def upload_paper_to_knowledge(
    request: Request,
    file: UploadFile = File(...),
    knowledge_base_id: int | None = Form(default=None),
    confidentiality: str = Form(default="internal"),
    allow_external_ai: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("paper.upload")),
):
    kb = db.get(KnowledgeBase, knowledge_base_id) if knowledge_base_id else _ensure_personal_kb(db, user)
    if not kb or not _kb_access(kb, user, manage=True):
        raise HTTPException(status_code=404, detail="knowledge base not found")
    try:
        record, duplicate = store_upload(db, user, file, confidentiality=confidentiality, external_ai_allowed=allow_external_ai, allowed_suffixes={".pdf", ".docx"})
    except InvalidStoredUpload as exc:
        doc = KnowledgeDocument(file_id=exc.record.id, knowledge_base_id=kb.id, title=exc.record.original_name, source_type="upload", owner_user_id=user.id, status="failed", page_count=0, metadata_json=json.dumps({"validation": exc.validation}, ensure_ascii=False))
        db.add(doc); db.commit(); db.refresh(doc)
        task = create_task(db, user_id=user.id, task_type="paper_ingest", title=f"论文入库失败：{exc.record.original_name}", input_data={"file_id": exc.record.id, "document_id": doc.id}, model_name="local-evidence-pipeline", model_version="V4.2", software_name="EnerTri Paper Knowledge Pipeline", software_version="4.2.0")
        task.status = "failed"; task.current_step = "上传安全校验失败"; task.error_message = str(exc.detail); task.finished_at = datetime.now(timezone.utc)
        db.add(TaskEvent(task_id=task.id, event_type="error", level="error", step="上传安全校验失败", progress=0, message=str(exc.detail)))
        db.commit(); link_file(db, task.id, exc.record.id, "input")
        write_audit(db, action="paper.upload.rejected", resource_type="workspace_file", resource_id=exc.record.id, actor=user, outcome="failed", details=exc.validation, **_meta(request))
        return {**task_to_dict(task), "document_id": doc.id, "file_id": exc.record.id, "file_parse_status": "failed"}
    doc = KnowledgeDocument(file_id=record.id, knowledge_base_id=kb.id, title=record.original_name, source_type="upload", owner_user_id=user.id, status="pending", metadata_json=json.dumps({"knowledge_base_policy": {"allow_ai": kb.allow_ai, "allow_export": kb.allow_export, "retain_original": kb.retain_original}}, ensure_ascii=False))
    db.add(doc); db.commit(); db.refresh(doc)
    task = create_task(db, user_id=user.id, task_type="paper_ingest", title=f"文档知识化：{record.original_name}", input_data={"file_id": record.id, "document_id": doc.id, "duplicate_detected": duplicate}, model_name="local-evidence-pipeline", model_version="V4.7", software_name="PyMuPDF/python-docx/local-vector", software_version="4.7.0", timeout_seconds=3600)
    link_file(db, task.id, record.id, "input")
    write_audit(db, action="paper.knowledge_ingest.queued", resource_type="knowledge_document", resource_id=doc.id, actor=user, details={"task_id": task.id, "file_id": record.id, "knowledge_base_id": kb.id, "duplicate": duplicate}, **_meta(request))
    submit_task(task.id)
    return {**task_to_dict(task), "document_id": doc.id, "knowledge_base_id": kb.id}


@router.get("/knowledge/documents")
def list_documents(knowledge_base_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(KnowledgeDocument).order_by(KnowledgeDocument.id.desc())
    if knowledge_base_id: stmt = stmt.where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
    rows = []
    for doc in db.scalars(stmt).all():
        try: _document_access(db, doc.id, user)
        except HTTPException: continue
        source = db.get(WorkspaceFile, doc.file_id) if doc.file_id else None
        source_path = Path(source.storage_path) if source and source.deleted_at is None else None
        source_exists = bool(source_path and source_path.is_file())
        source_missing = doc.source_type == "upload" and not source_exists
        file_type = Path(source.original_name).suffix.lower() if source else Path(doc.title).suffix.lower()
        rows.append({"id": doc.id, "title": doc.title, "status": "missing" if source_missing else doc.status, "parse_status": doc.status, "source_type": doc.source_type, "deletable": doc.source_type == "upload" and file_type in {".pdf", ".docx"}, "source_exists": source_exists, "source_missing": source_missing, "page_count": doc.page_count, "knowledge_base_id": doc.knowledge_base_id, "file_id": doc.file_id, "file_type": file_type, "created_at": doc.created_at})
    return rows


@router.delete("/knowledge/documents/{document_id}")
def delete_knowledge_document(document_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _document_access(db, document_id, user, manage=True)
    if user.role != "system_admin" and not (has_permission(user.role, "knowledge.own.manage") or has_permission(user.role, "knowledge.enterprise.manage")):
        raise HTTPException(status_code=403, detail="当前账号没有删除知识库文档的权限")
    if doc.source_type != "upload":
        raise HTTPException(status_code=400, detail="仅支持删除个人知识库中上传的 PDF / DOCX 文档")
    source = db.get(WorkspaceFile, doc.file_id) if doc.file_id else None
    suffix = Path(source.original_name).suffix.lower() if source else Path(doc.title).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="仅支持删除 PDF / DOCX 文档")

    # Stop a queued/running ingestion job before removing its source and extracted data.
    source_id = source.id if source else None
    paper_tasks = []
    active_tasks = []
    if source_id:
        paper_tasks = db.scalars(
            select(WorkspaceTask).join(TaskFile, TaskFile.task_id == WorkspaceTask.id)
            .where(TaskFile.file_id == source_id, WorkspaceTask.task_type == "paper_ingest")
        ).all()
        active_tasks = [task for task in paper_tasks if task.status in {"queued", "running"}]
        now = datetime.now(timezone.utc)
        for task in paper_tasks:
            task.result_json = None
        for task in active_tasks:
            task.status = "cancelled"
            task.current_step = "文档已删除"
            task.error_message = "用户删除了对应的论文文档"
            task.finished_at = now
            task.lease_expires_at = None
            db.add(TaskEvent(task_id=task.id, event_type="status", level="warning", step="文档已删除", progress=task.progress, message="论文文档及其解析结果已删除"))

    figure_dirs = set()
    expected_figure_dir_name = f"doc_{doc.id}_figures"
    for figure in db.scalars(select(KnowledgeFigure).where(KnowledgeFigure.document_id == doc.id)).all():
        if not figure.image_path:
            continue
        figure_dir = Path(figure.image_path).parent.resolve()
        if figure_dir.name == expected_figure_dir_name and figure_dir.is_relative_to(FILE_STORE_DIR.resolve()):
            figure_dirs.add(figure_dir)

    # Structured content has explicit deletes for databases that do not enforce FK cascades.
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    db.execute(delete(KnowledgePage).where(KnowledgePage.document_id == doc.id))
    db.execute(delete(KnowledgeTable).where(KnowledgeTable.document_id == doc.id))
    db.execute(delete(KnowledgeFigure).where(KnowledgeFigure.document_id == doc.id))
    db.delete(doc)

    # A duplicate upload can reuse a WorkspaceFile. Preserve that file while another
    # knowledge document still references it; otherwise remove the original and tombstone it.
    remove_path = None
    if source:
        remaining_refs = db.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.file_id == source.id, KnowledgeDocument.id != doc.id).limit(1))
        if not remaining_refs:
            remove_path = Path(source.storage_path)
            source.deleted_at = datetime.now(timezone.utc)
    db.commit()

    if remove_path:
        try:
            remove_path.unlink(missing_ok=True)
        except OSError:
            # Keep the database deletion successful; a later storage cleanup can remove the orphan.
            pass
    for figure_dir in figure_dirs:
        shutil.rmtree(figure_dir, ignore_errors=True)
    write_audit(db, action="paper.knowledge_document.deleted", resource_type="knowledge_document", resource_id=document_id, actor=user, details={"file_id": source_id, "active_tasks_cancelled": len(active_tasks)}, **_meta(request))
    return {"deleted": document_id, "structured_results_deleted": True, "source_file_deleted": bool(remove_path), "task_results_cleared": len(paper_tasks)}


@router.get("/knowledge/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _document_access(db, document_id, user)
    source = db.get(WorkspaceFile, doc.file_id) if doc.file_id else None
    source_exists = bool(source and source.deleted_at is None and Path(source.storage_path).is_file())
    source_missing = doc.source_type == "upload" and not source_exists
    pages = db.scalars(select(KnowledgePage).where(KnowledgePage.document_id == doc.id).order_by(KnowledgePage.page_number)).all()
    tables = db.scalars(select(KnowledgeTable).where(KnowledgeTable.document_id == doc.id).order_by(KnowledgeTable.page_number, KnowledgeTable.id)).all()
    figures = db.scalars(select(KnowledgeFigure).where(KnowledgeFigure.document_id == doc.id).order_by(KnowledgeFigure.page_number, KnowledgeFigure.id)).all()
    structure = json.loads(doc.structure_json or "{}")
    metadata = json.loads(doc.metadata_json or "{}")
    return {
        "id": doc.id, "title": doc.title, "status": "missing" if source_missing else doc.status, "parse_status": doc.status, "page_count": doc.page_count, "file_id": doc.file_id, "source_exists": source_exists, "source_missing": source_missing, "file_type": Path(source.original_name).suffix.lower() if source else Path(doc.title).suffix.lower(), "knowledge_base_id": doc.knowledge_base_id,
        "structure": structure, "metadata": metadata,
        "pages": [{"page_number": p.page_number, "text": p.text, "ocr_used": p.ocr_used, "extraction_method": p.extraction_method, "page_url": f"/api/files/{doc.file_id}/download#page={p.page_number}" if doc.file_id else None} for p in pages],
        "tables": [{"id": t.id, "table_number": t.table_number, "page_number": t.page_number, "title": t.title, "data": json.loads(t.data_json), "markdown": t.markdown} for t in tables],
        "figures": [{"id": f.id, "figure_number": f.figure_number, "page_number": f.page_number, "caption": f.caption} for f in figures],
    }


@router.post("/knowledge/documents/{document_id}/qa")
def document_qa(document_id: int, payload: QAPayload, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _document_access(db, document_id, user)
    if doc.status != "ready": raise HTTPException(status_code=409, detail="文档尚未完成解析")
    kb = db.get(KnowledgeBase, doc.knowledge_base_id) if doc.knowledge_base_id else None
    if kb and not kb.allow_ai:
        # V4.2 local retrieval is still allowed, but no external AI is called; make policy explicit.
        policy = "knowledge_base_ai_disabled_local_retrieval_only"
    else:
        policy = "local_evidence_qa"
    result = answer_question(db, doc, payload.question)
    for ev in result.get("evidence") or []:
        ev["page_url"] = f"/api/files/{doc.file_id}/download#page={ev['page']}" if doc.file_id else None
    result.update({"document_id": doc.id, "question": payload.question, "policy": policy})
    write_audit(db, action="paper.qa.answered", resource_type="knowledge_document", resource_id=doc.id, actor=user, details={"question": payload.question, "evidence_pages": [e.get("page") for e in result.get("evidence") or []]}, **_meta(request))
    return result
