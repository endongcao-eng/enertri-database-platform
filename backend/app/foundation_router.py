from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from .audit import write_audit
from .database import MEDIA_DIR, get_db
from .file_service import ALLOWED_SUFFIXES, InvalidStoredUpload, can_access_file, cleanup_expired_files, store_upload
from .models import AuditLog, TaskEvent, TaskFile, User, WorkspaceFile, WorkspaceTask, USER_ROLES
from .permissions import ROLE_LABELS, has_permission
from .security import admin_user, current_user, require_permission, user_permissions
from .simulation import SUPPORTED_SOFTWARE
from .task_service import create_task, event_to_dict, file_to_dict, link_file, submit_task, task_to_dict

router = APIRouter(tags=["V4.2 Engineering Foundation"])


class PptTaskRequest(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    source_text: str = Field(default="", max_length=150000)
    use_external_ai: bool = False


class SimulationTaskRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    software: str
    software_version: str | None = Field(default=None, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)


class UserRoleUpdate(BaseModel):
    role: str
    is_active: bool | None = None
    confirmation: str | None = Field(default=None, max_length=120)


def _request_meta(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


def _task_access(db: Session, task_id: int, user: User) -> WorkspaceTask:
    task = db.scalar(select(WorkspaceTask).options(selectinload(WorkspaceTask.events)).where(WorkspaceTask.id == task_id))
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    permission = "task.own.view" if task.user_id == user.id else "task.other.view"
    if not has_permission(user.role, permission):
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _task_manage_access(db: Session, task_id: int, user: User, own_permission: str) -> WorkspaceTask:
    task = db.scalar(select(WorkspaceTask).options(selectinload(WorkspaceTask.events)).where(WorkspaceTask.id == task_id))
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    permission = own_permission if task.user_id == user.id else "task.other.manage"
    if not has_permission(user.role, permission):
        raise HTTPException(status_code=403, detail=f"缺少权限：{permission}")
    return task


def _failed_upload_task(db: Session, user: User, exc: InvalidStoredUpload, task_type: str, title_prefix: str) -> WorkspaceTask:
    task = create_task(
        db, user_id=user.id, task_type=task_type, title=f"{title_prefix}失败：{exc.record.original_name}",
        input_data={"file_id": exc.record.id, "validation_failed": True},
        model_name="validation-rejected", model_version="V4.2", software_name="EnerTri Safe Upload Validator", software_version="4.2.0",
    )
    task.status = "failed"
    task.current_step = "上传安全校验失败"
    task.error_message = json.dumps(exc.detail, ensure_ascii=False, default=str)
    task.finished_at = datetime.now(timezone.utc)
    db.add(TaskEvent(task_id=task.id, event_type="error", level="error", step="上传安全校验失败", progress=0, message=str(exc.detail)))
    db.commit()
    link_file(db, task.id, exc.record.id, "input")
    return task


@router.get("/api/auth/permissions")
def permissions(user: User = Depends(current_user)):
    return {"role": user.role, "role_label": ROLE_LABELS.get(user.role, user.role), "permissions": user_permissions(user)}


@router.post("/api/tasks/paper-analysis", status_code=202)
def queue_paper_analysis(
    request: Request,
    file: UploadFile = File(...),
    focus: str = Form(default=""),
    confidentiality: str = Form(default="internal"),
    allow_external_ai: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("paper.upload")),
):
    try:
        record, duplicate = store_upload(
            db, user, file, confidentiality=confidentiality, external_ai_allowed=allow_external_ai,
            allowed_suffixes={".pdf", ".docx", ".txt", ".md"},
        )
    except InvalidStoredUpload as exc:
        task = _failed_upload_task(db, user, exc, "paper_analysis", "论文解析")
        write_audit(db, action="paper.upload.rejected", resource_type="workspace_file", resource_id=exc.record.id, actor=user, outcome="failed", details=exc.validation, **_request_meta(request))
        return task_to_dict(task)
    task = create_task(
        db,
        user_id=user.id,
        task_type="paper_analysis",
        title=f"论文解析：{record.original_name}",
        input_data={"file_id": record.id, "focus": focus, "duplicate_detected": duplicate},
        model_name=os.getenv("OPENAI_MODEL") if record.external_ai_allowed else "local-parser",
        model_version="V4.2",
        software_name="EnerTri Paper Pipeline",
        software_version="4.2.0",
    )
    link_file(db, task.id, record.id, "input")
    write_audit(
        db,
        action="task.created",
        resource_type="workspace_task",
        resource_id=task.id,
        actor=user,
        details={"task_type": task.task_type, "file_id": record.id, "duplicate": duplicate, "confidentiality": record.confidentiality, "external_ai_allowed": record.external_ai_allowed},
        **_request_meta(request),
    )
    submit_task(task.id)
    return task_to_dict(task)


@router.post("/api/tasks/ppt-generation", status_code=202)
def queue_ppt_generation(
    payload: PptTaskRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    use_external_ai = bool(payload.use_external_ai and has_permission(user.role, "ai.external"))
    task = create_task(
        db,
        user_id=user.id,
        task_type="ppt_generation",
        title=payload.title,
        input_data={"title": payload.title, "source_text": payload.source_text, "use_external_ai": use_external_ai},
        model_name=os.getenv("OPENAI_MODEL") if use_external_ai else "local-outline",
        model_version="V4.2",
        software_name="python-pptx",
        software_version="1.0.2",
    )
    write_audit(db, action="task.created", resource_type="workspace_task", resource_id=task.id, actor=user, details={"task_type": task.task_type, "external_ai": use_external_ai}, **_request_meta(request))
    submit_task(task.id)
    return task_to_dict(task)


@router.post("/api/tasks/video-analysis", status_code=202)
def queue_video_analysis(
    request: Request,
    file: UploadFile = File(...),
    focus: str = Form(default=""),
    confidentiality: str = Form(default="internal"),
    allow_external_ai: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        record, duplicate = store_upload(
            db, user, file, confidentiality=confidentiality, external_ai_allowed=allow_external_ai,
            allowed_suffixes={".mp4", ".mov", ".avi", ".mkv"},
        )
    except InvalidStoredUpload as exc:
        task = _failed_upload_task(db, user, exc, "video_analysis", "视频分析")
        write_audit(db, action="video.upload.rejected", resource_type="workspace_file", resource_id=exc.record.id, actor=user, outcome="failed", details=exc.validation, **_request_meta(request))
        return task_to_dict(task)
    task = create_task(
        db,
        user_id=user.id,
        task_type="video_analysis",
        title=f"视频分析：{record.original_name}",
        input_data={"file_id": record.id, "focus": focus, "duplicate_detected": duplicate},
        model_name=os.getenv("OPENAI_MODEL") if record.external_ai_allowed else "local-video-probe",
        model_version="V4.2",
        software_name="ffmpeg/ffprobe",
        software_version="system",
    )
    link_file(db, task.id, record.id, "input")
    write_audit(
        db,
        action="task.created",
        resource_type="workspace_task",
        resource_id=task.id,
        actor=user,
        details={"task_type": task.task_type, "file_id": record.id, "duplicate": duplicate, "confidentiality": record.confidentiality, "external_ai_allowed": record.external_ai_allowed},
        **_request_meta(request),
    )
    submit_task(task.id)
    return task_to_dict(task)


@router.post("/api/tasks/simulation-package", status_code=202)
def queue_simulation_package(
    payload: SimulationTaskRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("simulation.commercial")),
):
    if payload.software not in SUPPORTED_SOFTWARE:
        raise HTTPException(status_code=400, detail="不支持的仿真软件")
    task = create_task(
        db,
        user_id=user.id,
        task_type="simulation_package",
        title=f"仿真输入包：{payload.name}",
        input_data=payload.model_dump(),
        model_name="deterministic-template",
        model_version="V4.2",
        software_name=SUPPORTED_SOFTWARE[payload.software],
        software_version=payload.software_version or "unspecified",
    )
    write_audit(
        db,
        action="task.created",
        resource_type="workspace_task",
        resource_id=task.id,
        actor=user,
        details={"task_type": task.task_type, "software": payload.software},
        **_request_meta(request),
    )
    submit_task(task.id)
    return task_to_dict(task)


@router.get("/api/tasks")
def list_tasks(
    status: str | None = Query(default=None),
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = select(WorkspaceTask).order_by(WorkspaceTask.id.desc()).limit(limit)
    if scope != "all" or not has_permission(user.role, "task.other.view"):
        stmt = stmt.where(WorkspaceTask.user_id == user.id)
    if status:
        values = [item.strip() for item in status.split(",") if item.strip()]
        stmt = stmt.where(WorkspaceTask.status.in_(values))
    return [task_to_dict(item) for item in db.scalars(stmt).all()]


@router.get("/api/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = _task_access(db, task_id, user)
    data = task_to_dict(task, include_events=True)
    links = db.scalars(select(TaskFile).where(TaskFile.task_id == task.id)).all()
    data["files"] = [{**file_to_dict(link.file), "file_role": link.file_role} for link in links if link.file and link.file.deleted_at is None]
    return data


@router.get("/api/tasks/{task_id}/events")
def get_task_events(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = _task_access(db, task_id, user)
    return [event_to_dict(event) for event in task.events]


@router.post("/api/tasks/{task_id}/retry", status_code=202)
def retry_task(task_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    source = _task_manage_access(db, task_id, user, "task.own.retry")
    if source.status not in {"succeeded", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="运行中的任务不能重新执行")
    task = create_task(
        db,
        user_id=user.id,
        task_type=source.task_type,
        title=f"重新执行：{source.title}",
        input_data=json.loads(source.input_json or "{}"),
        model_name=source.model_name,
        model_version=source.model_version,
        software_name=source.software_name,
        software_version=source.software_version,
        retry_of_id=source.id,
    )
    for link in db.scalars(select(TaskFile).where(TaskFile.task_id == source.id, TaskFile.file_role == "input")).all():
        link_file(db, task.id, link.file_id, "input")
    write_audit(db, action="task.retried", resource_type="workspace_task", resource_id=task.id, actor=user, details={"retry_of": source.id}, **_request_meta(request))
    submit_task(task.id)
    return task_to_dict(task)


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = _task_manage_access(db, task_id, user, "task.own.cancel")
    if task.status in {"succeeded", "failed", "cancelled"}:
        return task_to_dict(task)
    task.status = "cancelled"
    task.current_step = "等待执行器停止"
    task.finished_at = datetime.now(timezone.utc)
    db.commit()
    write_audit(db, action="task.cancelled", resource_type="workspace_task", resource_id=task.id, actor=user, **_request_meta(request))
    return task_to_dict(task)


@router.post("/api/files/upload")
def upload_file(
    request: Request,
    file: UploadFile = File(...),
    confidentiality: str = Form(default="internal"),
    allow_external_ai: bool = Form(default=False),
    temporary: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        record, duplicate = store_upload(db, user, file, confidentiality=confidentiality, external_ai_allowed=allow_external_ai, allowed_suffixes=ALLOWED_SUFFIXES, temporary=temporary)
    except InvalidStoredUpload as exc:
        write_audit(db, action="file.upload.rejected", resource_type="workspace_file", resource_id=exc.record.id, actor=user, outcome="failed", details=exc.validation, **_request_meta(request))
        raise
    write_audit(db, action="file.uploaded" if not duplicate else "file.duplicate_detected", resource_type="workspace_file", resource_id=record.id, actor=user, details={"sha256": record.sha256, "duplicate": duplicate, "temporary": temporary, "expires_at": record.expires_at, "detected_mime_type": record.detected_mime_type}, **_request_meta(request))
    return {**file_to_dict(record), "duplicate_detected": duplicate}


@router.get("/api/files")
def list_files(
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    confidentiality: str | None = None,
    parse_status: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = select(WorkspaceFile).where(WorkspaceFile.deleted_at.is_(None)).order_by(WorkspaceFile.id.desc()).limit(limit)
    if scope != "all" or not has_permission(user.role, "file.other.view"):
        stmt = stmt.where(WorkspaceFile.uploader_id == user.id)
    if confidentiality:
        stmt = stmt.where(WorkspaceFile.confidentiality == confidentiality)
    if parse_status:
        stmt = stmt.where(WorkspaceFile.parse_status == parse_status)
    return [{**file_to_dict(item), "can_download": can_access_file(user, item, "download"), "can_delete": can_access_file(user, item, "delete")} for item in db.scalars(stmt).all()]


@router.get("/api/files/{file_id}/download")
def download_file(file_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    record = db.get(WorkspaceFile, file_id)
    if not record or record.deleted_at is not None or not can_access_file(user, record, "download"):
        raise HTTPException(status_code=404, detail="file not found")
    path = Path(record.storage_path).resolve()
    media_root = MEDIA_DIR.resolve()
    if not path.exists() or path == media_root or media_root not in path.parents:
        raise HTTPException(status_code=404, detail="file content not found")
    write_audit(db, action="file.downloaded", resource_type="workspace_file", resource_id=record.id, actor=user, **_request_meta(request))
    return FileResponse(path, filename=record.original_name, media_type=record.mime_type)


@router.delete("/api/files/{file_id}")
def delete_file(file_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    record = db.get(WorkspaceFile, file_id)
    if not record or record.deleted_at is not None or not can_access_file(user, record, "delete"):
        raise HTTPException(status_code=404, detail="file not found")
    try:
        Path(record.storage_path).unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"文件删除失败：{exc}") from exc
    record.deleted_at = datetime.now(timezone.utc)
    db.commit()
    write_audit(db, action="file.deleted", resource_type="workspace_file", resource_id=record.id, actor=user, **_request_meta(request))
    return {"deleted": file_id}


@router.get("/api/data/export")
def export_user_data(
    scope: str = Query(default="mine", pattern="^(mine|visible)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("data.export")),
):
    task_stmt = select(WorkspaceTask).order_by(WorkspaceTask.id)
    file_stmt = select(WorkspaceFile).where(WorkspaceFile.deleted_at.is_(None)).order_by(WorkspaceFile.id)
    if scope != "visible" or not has_permission(user.role, "task.other.view"):
        task_stmt = task_stmt.where(WorkspaceTask.user_id == user.id)
    if scope != "visible" or not has_permission(user.role, "file.other.view"):
        file_stmt = file_stmt.where(WorkspaceFile.uploader_id == user.id)
    return {
        "exported_at": datetime.now(timezone.utc),
        "scope": scope,
        "tasks": [task_to_dict(row) for row in db.scalars(task_stmt).all()],
        "files": [file_to_dict(row) for row in db.scalars(file_stmt).all()],
    }


@router.get("/api/admin/audit-logs")
def audit_logs(
    action: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit.view")),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = db.scalars(stmt).all()
    return [{
        "id": row.id,
        "actor_user_id": row.actor_user_id,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "outcome": row.outcome,
        "details": json.loads(row.detail_json) if row.detail_json else None,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "created_at": row.created_at,
    } for row in rows]


@router.get("/api/admin/migrations")
def migration_status(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    from .migration_bootstrap import HEAD_REVISION
    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    recent = db.scalars(select(AuditLog).where(AuditLog.action == "database.migration.completed").order_by(AuditLog.id.desc()).limit(10)).all()
    return {
        "current_revision": revision,
        "expected_revision": HEAD_REVISION,
        "status": "succeeded" if revision == HEAD_REVISION else "attention",
        "records": [{"id": row.id, "outcome": row.outcome, "details": json.loads(row.detail_json) if row.detail_json else None, "created_at": row.created_at} for row in recent],
    }


@router.post("/api/admin/files/cleanup")
def cleanup_files(request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    count = cleanup_expired_files(db)
    write_audit(db, action="file.cleanup", resource_type="workspace_file", actor=user, details={"deleted_count": count}, **_request_meta(request))
    return {"deleted_count": count}


@router.get("/api/admin/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    rows = db.scalars(select(User).order_by(User.id)).all()
    return [{
        "id": row.id, "username": row.username, "display_name": row.display_name,
        "role": row.role, "role_label": ROLE_LABELS.get(row.role, row.role),
        "is_active": row.is_active, "research_direction": row.research_direction,
        "created_at": row.created_at,
    } for row in rows]


@router.patch("/api/admin/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("user.role.manage")),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.role not in USER_ROLES:
        raise HTTPException(status_code=400, detail="无效角色")
    # Existing system administrators are protected, not only the act of granting the role.
    if target.role == "system_admin" and actor.role != "system_admin":
        raise HTTPException(status_code=403, detail="只有系统管理员能够修改系统管理员账户")
    if payload.role == "system_admin" and actor.role != "system_admin":
        raise HTTPException(status_code=403, detail="只有系统管理员可以授予系统管理员角色")
    if target.id == actor.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="不能停用当前登录账户")

    high_privilege_change = target.role in {"admin", "system_admin"} or payload.role in {"admin", "system_admin"} or payload.is_active is False
    if high_privilege_change and payload.confirmation != target.username:
        raise HTTPException(status_code=409, detail=f"高权限账户修改需要二次确认：confirmation 必须填写目标用户名 {target.username}")

    removing_system_admin = target.role == "system_admin" and (payload.role != "system_admin" or payload.is_active is False)
    if removing_system_admin:
        active_system_admins = db.scalar(select(func.count(User.id)).where(User.role == "system_admin", User.is_active.is_(True)))
        if int(active_system_admins or 0) <= 1:
            raise HTTPException(status_code=409, detail="不能停用或降级最后一个可用系统管理员")

    before = {"role": target.role, "is_active": target.is_active}
    target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    db.commit(); db.refresh(target)
    action = "security.privileged_user.updated" if high_privilege_change else "user.role.updated"
    write_audit(db, action=action, resource_type="user", resource_id=target.id, actor=actor, details={"before": before, "after": {"role": target.role, "is_active": target.is_active}, "second_confirmation": bool(high_privilege_change)}, **_request_meta(request))
    return {"id": target.id, "username": target.username, "role": target.role, "role_label": ROLE_LABELS.get(target.role, target.role), "is_active": target.is_active}
