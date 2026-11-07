from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .file_service import FILE_STORE_DIR
from .models import HtmlLearningAsset, Term, User
from .schemas import HtmlLibraryUploadResult
from .security import admin_user, optional_current_user
from .utils import normalize_term_name

router = APIRouter(prefix="/api/html-library", tags=["HTML Learning Library"])
HTML_LIBRARY_DIR = FILE_STORE_DIR / "html_library"
HTML_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
MAX_HTML_FILES = 10
MAX_HTML_BYTES = int(os.getenv("HTML_LIBRARY_MAX_MB", "8")) * 1024 * 1024


def _asset_kind(original_name: str) -> tuple[str, str]:
    stem = Path(original_name).stem.strip()
    if stem.endswith("科普"):
        return "article", stem[:-2].strip()
    return "video", stem


def _term_name_map(db: Session) -> dict[str, Term]:
    result: dict[str, Term] = {}
    for term in db.scalars(select(Term)).all():
        for value in (term.zh, term.en, term.ru):
            key = normalize_term_name(value)
            if key and key not in result:
                result[key] = term
    return result


def _refresh_term_flags(db: Session) -> dict[str, int]:
    terms = db.scalars(select(Term)).all()
    name_map: dict[str, Term] = {}
    for term in terms:
        for value in (term.zh, term.en, term.ru):
            key = normalize_term_name(value)
            if key and key not in name_map:
                name_map[key] = term

    for term in terms:
        term.html_video_available = False
        term.html_article_available = False
        term.has_video = bool(term.has_video)

    matched = {"video": 0, "article": 0}
    for asset in db.scalars(select(HtmlLearningAsset)).all():
        kind, term_label = _asset_kind(asset.original_name)
        term = name_map.get(normalize_term_name(term_label))
        asset.term_id = term.id if term else None
        if term:
            if kind == "video":
                term.html_video_available = True
            else:
                term.html_article_available = True
            # The existing field is used by the public overview as the quick
            # "has an associated video" marker. HTML lesson resources count as
            # an association even when the asset is an article.
            term.has_video = True
            matched[kind] += 1
    return matched


def _asset_to_dict(asset: HtmlLearningAsset) -> dict:
    kind, term_label = _asset_kind(asset.original_name)
    return {
        "id": asset.id,
        "original_name": asset.original_name,
        "asset_kind": kind,
        "term_label": term_label,
        "term_id": asset.term_id,
        "open_url": f"/api/html-library/{asset.id}/open",
        "created_at": asset.created_at,
    }


def _asset_path(asset: HtmlLearningAsset) -> Path:
    if not asset:
        raise HTTPException(status_code=404, detail="HTML 内容不存在")
    path = Path(asset.storage_path).resolve()
    root = HTML_LIBRARY_DIR.resolve()
    if path == root or root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="HTML 文件内容不存在")
    return path


@router.get("")
def list_html_assets(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    assets = db.scalars(select(HtmlLearningAsset).order_by(HtmlLearningAsset.id.desc()).limit(500)).all()
    return [_asset_to_dict(asset) for asset in assets]


@router.post("/upload", response_model=HtmlLibraryUploadResult)
def upload_html_assets(
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    if not files or len(files) > MAX_HTML_FILES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_HTML_FILES} 个 HTML 文件")

    uploaded = 0
    replaced = 0
    files_result: list[dict] = []
    uploaded_assets: list[HtmlLearningAsset] = []
    unmatched: list[str] = []
    for upload in files:
        original_name = Path(upload.filename or "").name
        if not original_name or Path(original_name).suffix.casefold() != ".html":
            raise HTTPException(status_code=400, detail=f"仅支持 .html 文件：{original_name or '未命名文件'}")
        data = upload.file.read(MAX_HTML_BYTES + 1)
        if not data:
            raise HTTPException(status_code=400, detail=f"HTML 文件为空：{original_name}")
        if len(data) > MAX_HTML_BYTES:
            raise HTTPException(status_code=413, detail=f"HTML 文件超过 {MAX_HTML_BYTES // 1024 // 1024} MB：{original_name}")

        target = HTML_LIBRARY_DIR / f"{uuid.uuid4().hex}.html"
        target.write_bytes(data)
        existing = db.scalar(select(HtmlLearningAsset).where(HtmlLearningAsset.original_name == original_name))
        if existing:
            Path(existing.storage_path).unlink(missing_ok=True)
            existing.storage_path = str(target)
            existing.uploader_id = user.id
            existing.mime_type = "text/html"
            asset = existing
            replaced += 1
        else:
            asset = HtmlLearningAsset(
                original_name=original_name,
                storage_path=str(target),
                asset_kind=_asset_kind(original_name)[0],
                mime_type="text/html",
                uploader_id=user.id,
            )
            db.add(asset)
        db.flush()
        uploaded_assets.append(asset)
        uploaded += 1

    matched = _refresh_term_flags(db)
    name_map = _term_name_map(db)
    for asset in uploaded_assets:
        _, term_label = _asset_kind(asset.original_name)
        if normalize_term_name(term_label) not in name_map and asset.original_name not in unmatched:
            unmatched.append(asset.original_name)
        files_result.append(_asset_to_dict(asset))
    db.commit()
    for item in files_result:
        write_audit(db, action="html_library.uploaded", resource_type="html_learning_asset", resource_id=str(item["id"]), actor=user, details=item, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    return HtmlLibraryUploadResult(
        uploaded=uploaded,
        replaced=replaced,
        matched=matched["video"] + matched["article"],
        unmatched=unmatched,
        files=files_result,
    )


@router.get("/{asset_id}/open")
def open_html_asset(asset_id: int, request: Request, db: Session = Depends(get_db), user: User | None = Depends(optional_current_user)):
    asset = db.get(HtmlLearningAsset, asset_id)
    path = _asset_path(asset)
    write_audit(db, action="html_library.opened", resource_type="html_learning_asset", resource_id=str(asset_id), actor=user, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": "inline",
            "Content-Security-Policy": "sandbox; default-src 'self' data: https:; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data: https:;",
            "X-Content-Type-Options": "nosniff",
        },
    )
