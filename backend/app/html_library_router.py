from __future__ import annotations

import io
import mimetypes
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .file_service import FILE_STORE_DIR
from .models import HtmlLearningAsset, Term, User
from .schemas import HtmlBundleUploadResult, HtmlLibraryUploadResult
from .security import admin_user, optional_current_user
from .utils import normalize_term_name

router = APIRouter(prefix="/api/html-library", tags=["HTML Learning Library"])
HTML_LIBRARY_DIR = FILE_STORE_DIR / "html_library"
BUNDLE_DIR = HTML_LIBRARY_DIR / "bundles"
HTML_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
MAX_HTML_FILES = 10
MAX_HTML_BYTES = int(os.getenv("HTML_LIBRARY_MAX_MB", "8")) * 1024 * 1024
MAX_BUNDLE_ARCHIVES = 10
MAX_BUNDLE_BYTES = int(os.getenv("HTML_BUNDLE_MAX_MB", "128")) * 1024 * 1024
MAX_BUNDLE_UNPACKED_BYTES = int(os.getenv("HTML_BUNDLE_UNPACKED_MAX_MB", "512")) * 1024 * 1024
MAX_BUNDLES_PER_ARCHIVE = 10


def _asset_kind(original_name: str) -> tuple[str, str]:
    stem = Path(original_name).stem.strip()
    if stem.endswith("科普"):
        return "article", stem[:-2].strip()
    return "video", stem


def _canonical_bundle_label(label: str) -> str:
    value = unicodedata.normalize("NFKC", str(label or "")).strip()
    value = re.sub(r"^\s*\d+\s*[-_.、_：:]+\s*", "", value)
    if value.endswith("科普"):
        value = value[:-2].strip()
    return value or "未命名科普页面"


def _asset_label(asset: HtmlLearningAsset) -> tuple[str, str]:
    if asset.is_bundle:
        return "article", _canonical_bundle_label(asset.bundle_name or asset.original_name)
    return _asset_kind(asset.original_name)


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
        kind, term_label = _asset_label(asset)
        term = name_map.get(normalize_term_name(term_label))
        asset.term_id = term.id if term else None
        if term:
            if kind == "video":
                term.html_video_available = True
            else:
                term.html_article_available = True
            term.has_video = True
            matched[kind] += 1
    return matched


def _asset_to_dict(asset: HtmlLearningAsset) -> dict:
    kind, term_label = _asset_label(asset)
    open_url = f"/api/html-library/{asset.id}/bundle/index.html" if asset.is_bundle else f"/api/html-library/{asset.id}/open"
    return {
        "id": asset.id,
        "original_name": asset.original_name,
        "asset_kind": kind,
        "term_label": term_label,
        "term_id": asset.term_id,
        "is_bundle": bool(asset.is_bundle),
        "bundle_name": asset.bundle_name,
        "open_url": open_url,
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


def _bundle_file_path(asset: HtmlLearningAsset, subpath: str) -> Path:
    if not asset or not asset.is_bundle or not asset.bundle_root:
        raise HTTPException(status_code=404, detail="科普页面包不存在")
    root = Path(asset.bundle_root).resolve()
    candidate = (root / subpath).resolve()
    if candidate == root or root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="科普页面资源不存在")
    return candidate


def _bundle_slug(label: str) -> str:
    value = unicodedata.normalize("NFKC", label).strip().lower()
    value = re.sub(r"[^\w\u4e00-\u9fff\u0400-\u04ff.-]+", "-", value, flags=re.UNICODE)
    value = value.strip(".-_")
    return value[:180] or uuid.uuid4().hex


def _safe_member_name(name: str) -> str:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=400, detail="ZIP 中包含不安全的路径")
    return "/".join(part for part in path.parts if part not in ("", "."))


def _bundle_prefixes(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    prefixes: dict[str, str] = {}
    for info in archive.infolist():
        name = _safe_member_name(info.filename)
        if name.casefold().endswith("index.html"):
            prefix = name[:-len("index.html")]
            raw_label = prefix.rstrip("/").split("/")[-1] if prefix else Path(archive.filename or "page").stem
            prefixes[prefix] = raw_label
    if not prefixes:
        raise HTTPException(status_code=400, detail="每个科普页面包都必须包含 index.html")
    if len(prefixes) > MAX_BUNDLES_PER_ARCHIVE:
        raise HTTPException(status_code=400, detail=f"一个 ZIP 最多包含 {MAX_BUNDLES_PER_ARCHIVE} 个科普页面包")
    return sorted(prefixes.items(), key=lambda item: item[0])


def _extract_bundles(data: bytes, archive_name: str) -> list[tuple[str, Path]]:
    staging = Path(tempfile.mkdtemp(prefix="html-bundle-", dir=str(BUNDLE_DIR)))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [(info, _safe_member_name(info.filename)) for info in archive.infolist()]
            unpacked_size = sum(max(0, info.file_size) for info, _ in members)
            if unpacked_size > MAX_BUNDLE_UNPACKED_BYTES:
                raise HTTPException(status_code=413, detail="ZIP 解压后的内容超过允许大小")
            for info, _ in members:
                if stat.S_ISLNK((info.external_attr >> 16) & 0o170000):
                    raise HTTPException(status_code=400, detail="ZIP 不允许包含符号链接")
            outputs: list[tuple[str, Path]] = []
            for prefix, raw_label in _bundle_prefixes(archive):
                label = _canonical_bundle_label(raw_label)
                target = staging / _bundle_slug(label)
                target.mkdir(parents=True, exist_ok=True)
                found = False
                for info, name in members:
                    if not name.startswith(prefix) or info.is_dir() or info.filename.endswith(("/", "\\")):
                        continue
                    relative = name[len(prefix):]
                    if not relative or relative.startswith("/"):
                        continue
                    safe_relative = _safe_member_name(relative)
                    destination = (target / safe_relative).resolve()
                    if target.resolve() not in destination.parents:
                        raise HTTPException(status_code=400, detail="ZIP 中包含不安全的相对路径")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(info))
                    found = found or safe_relative.casefold() == "index.html"
                if not found:
                    raise HTTPException(status_code=400, detail=f"页面包缺少 index.html：{raw_label}")
                outputs.append((label, target))
            return outputs
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail=f"不是有效的 ZIP 文件：{archive_name}") from exc
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _audit_meta(request: Request) -> dict:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


@router.get("")
def list_html_assets(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    assets = db.scalars(select(HtmlLearningAsset).order_by(HtmlLearningAsset.id.desc()).limit(500)).all()
    return [_asset_to_dict(asset) for asset in assets]


@router.post("/upload", response_model=HtmlLibraryUploadResult)
def upload_html_assets(request: Request, files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(admin_user)):
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
            existing.is_bundle = False
            existing.bundle_name = None
            existing.bundle_root = None
            asset = existing
            replaced += 1
        else:
            asset = HtmlLearningAsset(original_name=original_name, storage_path=str(target), asset_kind=_asset_kind(original_name)[0], mime_type="text/html", uploader_id=user.id)
            db.add(asset)
        db.flush()
        uploaded_assets.append(asset)
        uploaded += 1
    matched = _refresh_term_flags(db)
    name_map = _term_name_map(db)
    for asset in uploaded_assets:
        _, term_label = _asset_label(asset)
        if normalize_term_name(term_label) not in name_map and asset.original_name not in unmatched:
            unmatched.append(asset.original_name)
        files_result.append(_asset_to_dict(asset))
    db.commit()
    for item in files_result:
        write_audit(db, action="html_library.uploaded", resource_type="html_learning_asset", resource_id=str(item["id"]), actor=user, details=item, **_audit_meta(request))
    return HtmlLibraryUploadResult(uploaded=uploaded, replaced=replaced, matched=matched["video"] + matched["article"], unmatched=unmatched, files=files_result)


@router.post("/bundles/upload", response_model=HtmlBundleUploadResult)
def upload_html_bundles(request: Request, files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if not files or len(files) > MAX_BUNDLE_ARCHIVES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_BUNDLE_ARCHIVES} 个 ZIP 页面包")
    extracted: list[tuple[str, Path, str]] = []
    staging_roots: list[Path] = []
    try:
        for upload in files:
            archive_name = Path(upload.filename or "").name
            if Path(archive_name).suffix.casefold() != ".zip":
                raise HTTPException(status_code=400, detail=f"仅支持 .zip 页面包：{archive_name or '未命名文件'}")
            data = upload.file.read(MAX_BUNDLE_BYTES + 1)
            if not data:
                raise HTTPException(status_code=400, detail=f"ZIP 文件为空：{archive_name}")
            if len(data) > MAX_BUNDLE_BYTES:
                raise HTTPException(status_code=413, detail=f"ZIP 文件超过 {MAX_BUNDLE_BYTES // 1024 // 1024} MB：{archive_name}")
            outputs = _extract_bundles(data, archive_name)
            if outputs:
                staging_roots.append(outputs[0][1].parent)
            extracted.extend((label, path, archive_name) for label, path in outputs)
    except Exception:
        for root in staging_roots:
            shutil.rmtree(root, ignore_errors=True)
        raise
    if len(extracted) > MAX_BUNDLES_PER_ARCHIVE * MAX_BUNDLE_ARCHIVES:
        for root in staging_roots:
            shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="本次上传的科普页面包数量过多")

    uploaded = 0
    replaced = 0
    bundles_result: list[dict] = []
    uploaded_assets: list[HtmlLearningAsset] = []
    source_by_label = {label: source for label, _, source in extracted}
    try:
        for label, staged_path, _ in extracted:
            target = BUNDLE_DIR / _bundle_slug(label)
            existing = db.scalar(select(HtmlLearningAsset).where(HtmlLearningAsset.is_bundle.is_(True), HtmlLearningAsset.bundle_name == label))
            if existing:
                shutil.rmtree(Path(existing.bundle_root), ignore_errors=True)
                existing.storage_path = str(target / "index.html")
                existing.bundle_root = str(target)
                existing.bundle_name = label
                existing.original_name = f"{label}.bundle.zip"
                existing.asset_kind = "article"
                existing.mime_type = "text/html"
                existing.uploader_id = user.id
                existing.is_bundle = True
                asset = existing
                replaced += 1
            else:
                asset = HtmlLearningAsset(original_name=f"{label}.bundle.zip", storage_path=str(target / "index.html"), asset_kind="article", is_bundle=True, bundle_name=label, bundle_root=str(target), mime_type="text/html", uploader_id=user.id)
                db.add(asset)
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(staged_path), str(target))
            db.flush()
            uploaded_assets.append(asset)
            uploaded += 1
        matched = _refresh_term_flags(db)
        for asset in uploaded_assets:
            bundles_result.append({**_asset_to_dict(asset), "source_archive": source_by_label.get(asset.bundle_name)})
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        for root in staging_roots:
            shutil.rmtree(root, ignore_errors=True)
    name_map = _term_name_map(db)
    unmatched = [item["bundle_name"] for item in bundles_result if normalize_term_name(item["term_label"]) not in name_map]
    for item in bundles_result:
        write_audit(db, action="html_library.bundle_uploaded", resource_type="html_learning_asset", resource_id=str(item["id"]), actor=user, details=item, **_audit_meta(request))
    return HtmlBundleUploadResult(uploaded=uploaded, replaced=replaced, matched=matched["article"], unmatched=unmatched, bundles=bundles_result)


@router.get("/{asset_id}/open")
def open_html_asset(asset_id: int, request: Request, db: Session = Depends(get_db), user: User | None = Depends(optional_current_user)):
    asset = db.get(HtmlLearningAsset, asset_id)
    if asset and asset.is_bundle:
        return open_bundle_asset(asset_id, "index.html", request, db, user)
    path = _asset_path(asset)
    write_audit(db, action="html_library.opened", resource_type="html_learning_asset", resource_id=str(asset_id), actor=user, **_audit_meta(request))
    return FileResponse(path, media_type="text/html; charset=utf-8", headers={"Content-Disposition": "inline", "Content-Security-Policy": "sandbox; default-src 'self' data: https:; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data: https:;", "X-Content-Type-Options": "nosniff"})


@router.get("/{asset_id}/bundle/{subpath:path}")
def open_bundle_asset(asset_id: int, subpath: str, request: Request, db: Session = Depends(get_db), user: User | None = Depends(optional_current_user)):
    asset = db.get(HtmlLearningAsset, asset_id)
    path = _bundle_file_path(asset, subpath)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    write_audit(db, action="html_library.bundle_opened", resource_type="html_learning_asset", resource_id=str(asset_id), actor=user, details={"path": subpath}, **_audit_meta(request))
    return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline", "Content-Security-Policy": "sandbox allow-scripts; default-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; img-src 'self' data: https:; media-src 'self' data: https:; font-src 'self' data: https:;", "X-Content-Type-Options": "nosniff"})
