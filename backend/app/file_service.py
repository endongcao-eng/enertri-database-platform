from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import MEDIA_DIR
from .models import User, WorkspaceFile
from .file_validation import FileValidationError, validate_file_bytes
from .permissions import has_permission

FILE_STORE_DIR = Path(os.getenv("FILE_STORE_DIR", str(MEDIA_DIR / "files"))).resolve()
FILE_STORE_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_BYTES = int(os.getenv("FILE_MAX_MB", os.getenv("WORKSPACE_MAX_FILE_MB", "30"))) * 1024 * 1024
TEMP_FILE_RETENTION_HOURS = max(1, int(os.getenv("TEMP_FILE_RETENTION_HOURS", "24")))
ALLOWED_SUFFIXES = {
    ".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".json", ".xml",
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp",
    ".pptx", ".zip", ".mp4", ".mov", ".avi", ".mkv",
}


class InvalidStoredUpload(HTTPException):
    def __init__(self, record: WorkspaceFile, message: str, validation: dict):
        self.record = record
        self.validation = validation
        super().__init__(status_code=400, detail={"message": message, "file_id": record.id, "parse_status": "failed", "validation": validation})


def _read_limited(stream: BinaryIO) -> bytes:
    data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_FILE_BYTES // 1024 // 1024} MB 限制")
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    return data


def store_upload(
    db: Session,
    user: User,
    upload: UploadFile,
    *,
    confidentiality: str = "internal",
    external_ai_allowed: bool = True,
    task_id: int | None = None,
    allowed_suffixes: set[str] | None = None,
    parse_status: str = "pending",
    temporary: bool = False,
) -> tuple[WorkspaceFile, bool]:
    cleanup_expired_files(db)
    original = Path(upload.filename or "upload.bin").name
    suffix = Path(original).suffix.lower()
    allowed = allowed_suffixes or ALLOWED_SUFFIXES
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式：{suffix or '无扩展名'}")
    if confidentiality not in {"public", "internal", "confidential", "restricted"}:
        raise HTTPException(status_code=400, detail="无效的保密等级")
    if confidentiality == "restricted":
        external_ai_allowed = False
    if external_ai_allowed and not has_permission(user.role, "ai.external"):
        external_ai_allowed = False

    data = _read_limited(upload.file)
    digest = hashlib.sha256(data).hexdigest()
    try:
        validation = validate_file_bytes(original, data, upload.content_type)
        detected_mime = validation.get("detected_mime_type")
    except FileValidationError as exc:
        validation = {"valid": False, "error": str(exc), **(exc.details or {})}
        detected_mime = validation.get("detected_mime_type") or "application/octet-stream"
        now = datetime.now(timezone.utc)
        quarantine_dir = FILE_STORE_DIR / "quarantine" / now.strftime("%Y") / now.strftime("%m")
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        storage_name = f"quarantine_{uuid.uuid4().hex}{suffix}"
        path = quarantine_dir / storage_name
        path.write_bytes(data)
        record = WorkspaceFile(
            original_name=original, storage_name=storage_name, storage_path=str(path),
            file_type=suffix.lstrip(".") or "binary", mime_type=upload.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream",
            detected_mime_type=detected_mime, validation_json=json.dumps(validation, ensure_ascii=False, default=str),
            size_bytes=len(data), sha256=digest, uploader_id=user.id, task_id=task_id,
            confidentiality=confidentiality, parse_status="failed", external_ai_allowed=False,
            expires_at=now + timedelta(hours=TEMP_FILE_RETENTION_HOURS),
        )
        db.add(record); db.commit(); db.refresh(record)
        raise InvalidStoredUpload(record, str(exc), validation) from exc
    duplicate = db.scalar(
        select(WorkspaceFile).where(
            WorkspaceFile.uploader_id == user.id,
            WorkspaceFile.sha256 == digest,
            WorkspaceFile.deleted_at.is_(None),
        ).order_by(WorkspaceFile.id.desc())
    )
    if duplicate:
        # Reusing bytes must never weaken an existing or newly requested security policy.
        confidentiality_rank = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        if confidentiality_rank[confidentiality] > confidentiality_rank[duplicate.confidentiality]:
            duplicate.confidentiality = confidentiality
        duplicate.external_ai_allowed = bool(
            duplicate.external_ai_allowed
            and external_ai_allowed
            and duplicate.confidentiality != "restricted"
        )
        if task_id is not None and duplicate.task_id is None:
            duplicate.task_id = task_id
        if not temporary:
            duplicate.expires_at = None
        db.commit()
        db.refresh(duplicate)
        return duplicate, True

    now = datetime.now(timezone.utc)
    target_dir = FILE_STORE_DIR / now.strftime("%Y") / now.strftime("%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{uuid.uuid4().hex}{suffix}"
    path = target_dir / storage_name
    path.write_bytes(data)
    record = WorkspaceFile(
        original_name=original,
        storage_name=storage_name,
        storage_path=str(path),
        file_type=suffix.lstrip(".") or "binary",
        mime_type=upload.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream",
        detected_mime_type=detected_mime,
        validation_json=json.dumps(validation, ensure_ascii=False, default=str),
        size_bytes=len(data),
        sha256=digest,
        uploader_id=user.id,
        task_id=task_id,
        confidentiality=confidentiality,
        parse_status=parse_status,
        external_ai_allowed=external_ai_allowed,
        expires_at=now + timedelta(hours=TEMP_FILE_RETENTION_HOURS) if temporary else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, False


def register_generated_file(
    db: Session,
    user_id: int,
    path: Path,
    *,
    task_id: int | None,
    confidentiality: str = "internal",
    parse_status: str = "not_applicable",
) -> WorkspaceFile:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    record = WorkspaceFile(
        original_name=path.name,
        storage_name=f"task_{task_id or 'generated'}_{path.name}",
        storage_path=str(path.resolve()),
        file_type=path.suffix.lower().lstrip(".") or "binary",
        mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        detected_mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        validation_json=json.dumps({"valid": True, "generated": True}, ensure_ascii=False),
        size_bytes=len(data),
        sha256=digest,
        uploader_id=user_id,
        task_id=task_id,
        confidentiality=confidentiality,
        parse_status=parse_status,
        external_ai_allowed=False,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def can_access_file(user: User, record: WorkspaceFile, action: str = "view") -> bool:
    own = record.uploader_id == user.id
    permission = {
        (True, "view"): "file.own.view", (False, "view"): "file.other.view",
        (True, "download"): "file.own.download", (False, "download"): "file.other.download",
        (True, "delete"): "file.own.delete", (False, "delete"): "file.other.manage",
    }.get((own, action))
    if not permission or not has_permission(user.role, permission):
        return False
    # Quarantined/failed validation files are never downloadable.
    if action == "download" and record.parse_status == "failed":
        return False
    return True


def cleanup_expired_files(db: Session) -> int:
    now = datetime.now(timezone.utc)
    records = db.scalars(select(WorkspaceFile).where(WorkspaceFile.expires_at < now, WorkspaceFile.deleted_at.is_(None))).all()
    count = 0
    for record in records:
        try:
            Path(record.storage_path).unlink(missing_ok=True)
        except OSError:
            continue
        record.deleted_at = now
        count += 1
    db.commit()
    return count
