from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .file_service import FILE_STORE_DIR, InvalidStoredUpload, is_managed_storage_path, store_upload
from .models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeFigure, KnowledgePage, KnowledgeTable, Publication, PublicationSource, TaskEvent, TaskFile, User, WorkspaceFile, WorkspaceTask
from .paper_pipeline import answer_question
from .paper_deletion import delete_document_rows, finalize_paper_deletion
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


class TableCorrectionPayload(BaseModel):
    title: str | None = Field(default=None, max_length=2000)
    page_number: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = None
    data: list[list[Any]] | None = None
    markdown: str | None = None
    extraction_strategy: str | None = Field(default=None, max_length=80)
    confidence: float | None = Field(default=None, ge=0, le=1)


class CentralSavePayload(BaseModel):
    knowledge_base_id: int | None = None


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


@router.post("/literature/publications/{publication_id}/save")
def save_central_publication(
    publication_id: str,
    request: Request,
    payload: CentralSavePayload | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("paper.upload")),
):
    """Save a central-catalog record into the user's KB without inventing a PDF.

    This creates a bibliographic knowledge document.  The document is
    intentionally marked ``catalog`` until the user uploads/attaches a full
    text, so it cannot be mistaken for a parsed original source.
    """
    try:
        item = get_space_energy_literature(db, publication_id)
    except SpaceEnergyCatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="论文主库中未找到该论文")
    kb = db.get(KnowledgeBase, payload.knowledge_base_id) if payload and payload.knowledge_base_id else _ensure_personal_kb(db, user)
    if not kb or not _kb_access(kb, user, manage=True):
        raise HTTPException(status_code=404, detail="knowledge base not found")
    # A catalog row has no local Publication id yet; create or reuse the
    # bibliographic mirror so KnowledgeDocument can retain a stable FK.
    doi = item.get("doi")
    normalized_title = " ".join(re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(item.get("title") or "").casefold()).split())
    local = db.scalar(select(Publication).where(Publication.doi == doi)) if doi else None
    if not local and normalized_title:
        for candidate in db.scalars(select(Publication).where(Publication.normalized_title == normalized_title).limit(10)).all():
            local = candidate
            break
    if not local:
        local = Publication(title=item.get("title") or "未命名论文", normalized_title=normalized_title or str(item.get("title") or "未命名论文").casefold(), doi=doi, primary_source="space_energy")
        db.add(local); db.flush()
    local.title = local.title or item.get("title")
    local.abstract = local.abstract or item.get("abstract")
    local.journal = local.journal or item.get("journal") or item.get("source")
    local.year = local.year or item.get("year")
    local.landing_page_url = local.landing_page_url or item.get("landing_page_url") or item.get("open_url")
    local.fulltext_url = local.fulltext_url or item.get("fulltext_url")
    local.authors_json = json.dumps(item.get("authors") or [], ensure_ascii=False)
    local.keywords_json = json.dumps(item.get("keywords") or item.get("tags") or [], ensure_ascii=False)
    if not db.scalar(select(PublicationSource).where(PublicationSource.publication_id == local.id, PublicationSource.source_name == "space_energy", PublicationSource.source_record_id == str(publication_id))):
        db.add(PublicationSource(publication_id=local.id, source_name="space_energy", source_record_id=str(publication_id), raw_json=json.dumps(item, ensure_ascii=False, default=str)))
    existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == kb.id, KnowledgeDocument.publication_id == local.id, KnowledgeDocument.source_type == "catalog"))
    already_saved = existing is not None
    if not existing:
        existing = KnowledgeDocument(publication_id=local.id, knowledge_base_id=kb.id, title=item.get("title") or "未命名论文", source_type="catalog", owner_user_id=user.id, status="catalog_saved", page_count=0, metadata_json=json.dumps({"central_catalog_id": str(publication_id), "source": "space_energy", "fulltext_url": item.get("fulltext_url")}, ensure_ascii=False))
        db.add(existing)
    db.commit(); db.refresh(existing)
    write_audit(db, action="literature.central.saved_to_knowledge_base", resource_type="knowledge_document", resource_id=existing.id, actor=user, details={"central_id": str(publication_id), "knowledge_base_id": kb.id}, **_meta(request))
    return {"saved": True, "already_saved": already_saved, "document_id": existing.id, "knowledge_base_id": kb.id, "publication": publication_to_dict(db, local), "source_type": "catalog", "fulltext_url": item.get("fulltext_url")}


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

    source_id = source.id if source else None
    deletion = delete_document_rows(db, doc)
    db.commit()
    finalize_paper_deletion(deletion)
    write_audit(db, action="paper.knowledge_document.deleted", resource_type="knowledge_document", resource_id=document_id, actor=user, details={"file_id": source_id, "active_tasks_cancelled": deletion.active_tasks_cancelled}, **_meta(request))
    return {"deleted": document_id, "structured_results_deleted": True, "source_file_deleted": bool(deletion.remove_paths), "task_results_cleared": deletion.task_results_cleared, "tasks_deleted": deletion.tasks_deleted}


@router.post("/knowledge/documents/{document_id}/reprocess", status_code=202)
def reprocess_knowledge_document(document_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Re-run parsing for an existing upload after the extraction pipeline is upgraded."""
    doc = _document_access(db, document_id, user, manage=True)
    if user.role != "system_admin" and not (has_permission(user.role, "knowledge.own.manage") or has_permission(user.role, "knowledge.enterprise.manage")):
        raise HTTPException(status_code=403, detail="当前账号没有重新解析知识库文档的权限")
    source = db.get(WorkspaceFile, doc.file_id) if doc.file_id else None
    if not source or source.deleted_at is not None or not Path(source.storage_path).is_file():
        raise HTTPException(status_code=409, detail="原始论文文件不存在，无法重新解析")
    if Path(source.original_name).suffix.lower() not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="仅支持重新解析 PDF / DOCX 文档")
    active = db.scalar(
        select(WorkspaceTask).join(TaskFile, TaskFile.task_id == WorkspaceTask.id)
        .where(TaskFile.file_id == source.id, WorkspaceTask.task_type == "paper_ingest", WorkspaceTask.status.in_(("queued", "running")))
        .order_by(WorkspaceTask.id.desc())
    )
    if active:
        return {**task_to_dict(active), "document_id": doc.id, "already_running": True}
    doc.status = "pending"
    source.parse_status = "pending"
    db.commit()
    task = create_task(
        db, user_id=user.id, task_type="paper_ingest", title=f"重新解析论文：{doc.title}",
        input_data={"file_id": source.id, "document_id": doc.id, "reprocess": True},
        model_name="local-evidence-pipeline", model_version="V4.7", software_name="PyMuPDF/pdfplumber/multi-strategy-table-parser", software_version="4.7.0", timeout_seconds=3600,
    )
    link_file(db, task.id, source.id, "input")
    write_audit(db, action="paper.knowledge_ingest.reprocess_queued", resource_type="knowledge_document", resource_id=doc.id, actor=user, details={"task_id": task.id, "file_id": source.id}, **_meta(request))
    submit_task(task.id)
    return {**task_to_dict(task), "document_id": doc.id, "already_running": False}


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
    # Rows created before webprep.23 did not carry bbox/strategy metadata. In
    # PDFs those legacy rows are frequently paragraph-shaped text grids (the
    # exact failure mode fixed by the stricter extractor), so do not render
    # them as scientific tables. They remain in the database until the user
    # explicitly reprocesses the original file.
    hidden_legacy_tables = 0
    visible_tables = []
    for table in tables:
        legacy_pdf_candidate = (
            Path(source.original_name).suffix.lower() == ".pdf" if source else Path(doc.title).suffix.lower() == ".pdf"
        ) and not table.bbox_json and (table.extraction_strategy or "unknown") == "unknown" and float(table.confidence or 0) <= 0
        if legacy_pdf_candidate:
            hidden_legacy_tables += 1
            continue
        visible_tables.append(table)
    if hidden_legacy_tables:
        metadata.setdefault("table_extraction", {})["hidden_legacy_table_count"] = hidden_legacy_tables
    return {
        "id": doc.id, "title": doc.title, "status": "missing" if source_missing else doc.status, "parse_status": doc.status, "page_count": doc.page_count, "file_id": doc.file_id, "source_exists": source_exists, "source_missing": source_missing, "file_type": Path(source.original_name).suffix.lower() if source else Path(doc.title).suffix.lower(), "knowledge_base_id": doc.knowledge_base_id,
        "structure": structure, "metadata": metadata,
        "pages": [{"page_number": p.page_number, "text": p.text, "ocr_used": p.ocr_used, "extraction_method": p.extraction_method, "page_url": f"/api/files/{doc.file_id}/download#page={p.page_number}" if doc.file_id else None} for p in pages],
        "tables": [{"id": t.id, "table_number": t.table_number, "page_number": t.page_number, "title": t.title, "data": json.loads(t.data_json or "[]"), "markdown": t.markdown, "bbox": json.loads(t.bbox_json) if t.bbox_json else None, "extraction_strategy": t.extraction_strategy, "confidence": t.confidence, "preview_url": f"/api/knowledge/documents/{doc.id}/tables/{t.id}/preview" if t.preview_path else None, "corrected": bool(t.correction_json)} for t in visible_tables],
        "figures": [{"id": f.id, "figure_number": f.figure_number, "page_number": f.page_number, "caption": f.caption, "preview_url": f"/api/knowledge/documents/{doc.id}/figures/{f.id}/preview" if f.image_path else None} for f in figures],
    }


def _table_or_404(db: Session, document_id: int, table_id: int) -> KnowledgeTable:
    table = db.scalar(select(KnowledgeTable).where(KnowledgeTable.id == table_id, KnowledgeTable.document_id == document_id))
    if not table:
        raise HTTPException(status_code=404, detail="table not found")
    return table


def _safe_preview_path(value: str | None) -> Path:
    if not value:
        raise HTTPException(status_code=404, detail="preview not available")
    path = Path(value).resolve()
    if not is_managed_storage_path(path) or not path.is_file():
        raise HTTPException(status_code=404, detail="preview not available")
    return path


@router.get("/knowledge/documents/{document_id}/tables/{table_id}/preview")
def table_preview(document_id: int, table_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _document_access(db, document_id, user)
    table = _table_or_404(db, doc.id, table_id)
    path = _safe_preview_path(table.preview_path)
    return FileResponse(path, filename=path.name, media_type="image/png")


@router.patch("/knowledge/documents/{document_id}/tables/{table_id}")
def correct_table(document_id: int, table_id: int, payload: TableCorrectionPayload, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("knowledge.own.manage"))):
    doc = _document_access(db, document_id, user, manage=True)
    table = _table_or_404(db, doc.id, table_id)
    if payload.bbox is not None and len(payload.bbox) != 4:
        raise HTTPException(status_code=422, detail="bbox 必须是 [x0, y0, x1, y1]")
    if payload.title is not None: table.title = payload.title
    if payload.page_number is not None: table.page_number = payload.page_number
    if payload.bbox is not None:
        x0, y0, x1, y1 = payload.bbox
        if x1 <= x0 or y1 <= y0: raise HTTPException(status_code=422, detail="bbox 的右下角必须大于左上角")
        table.bbox_json = json.dumps([round(float(v), 3) for v in payload.bbox], ensure_ascii=False)
    if payload.data is not None:
        table.data_json = json.dumps(payload.data, ensure_ascii=False, default=str)
        if payload.markdown is None:
            rows = [[str(cell or "").strip() for cell in row] for row in payload.data]
            width = max((len(row) for row in rows), default=0)
            padded = [row + [""] * (width - len(row)) for row in rows]
            table.markdown = "| " + " | ".join(padded[0]) + " |\n| " + " | ".join(["---"] * width) + " |\n" + "\n".join("| " + " | ".join(row) + " |" for row in padded[1:]) if padded else ""
    if payload.markdown is not None: table.markdown = payload.markdown
    if payload.extraction_strategy is not None: table.extraction_strategy = payload.extraction_strategy
    if payload.confidence is not None: table.confidence = payload.confidence
    correction = json.loads(table.correction_json or "{}")
    correction.update({"corrected_at": datetime.now(timezone.utc).isoformat(), "corrected_by": user.id, "fields": payload.model_dump(exclude_none=True)})
    table.correction_json = json.dumps(correction, ensure_ascii=False, default=str)
    # Re-crop from the original PDF when a reviewer supplied a new bbox.
    if payload.bbox is not None and doc.file_id:
        source = db.get(WorkspaceFile, doc.file_id)
        try:
            import fitz
            if source and Path(source.storage_path).suffix.lower() == ".pdf" and Path(source.storage_path).is_file():
                path = Path(table.preview_path) if table.preview_path else FILE_STORE_DIR / f"doc_{doc.id}_figures" / f"table_{table.id}_corrected.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                pdf = fitz.open(source.storage_path); page = pdf.load_page(table.page_number - 1); rect = fitz.Rect(*payload.bbox) & page.rect
                page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False).save(str(path)); pdf.close(); table.preview_path = str(path)
        except Exception:
            pass
    db.commit(); db.refresh(table)
    write_audit(db, action="paper.table.corrected", resource_type="knowledge_table", resource_id=table.id, actor=user, details={"document_id": doc.id, "fields": payload.model_dump(exclude_none=True)}, **_meta(request))
    return {"id": table.id, "document_id": doc.id, "table_number": table.table_number, "page_number": table.page_number, "title": table.title, "data": json.loads(table.data_json or "[]"), "markdown": table.markdown, "bbox": json.loads(table.bbox_json) if table.bbox_json else None, "extraction_strategy": table.extraction_strategy, "confidence": table.confidence, "preview_url": f"/api/knowledge/documents/{doc.id}/tables/{table.id}/preview" if table.preview_path else None, "corrected": True}


@router.get("/knowledge/documents/{document_id}/figures/{figure_id}/preview")
def figure_preview(document_id: int, figure_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = _document_access(db, document_id, user)
    figure = db.scalar(select(KnowledgeFigure).where(KnowledgeFigure.id == figure_id, KnowledgeFigure.document_id == doc.id))
    if not figure: raise HTTPException(status_code=404, detail="figure not found")
    path = _safe_preview_path(figure.image_path)
    return FileResponse(path, filename=path.name)


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
