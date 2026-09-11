from __future__ import annotations

import io
import json
import mimetypes
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader


class FileValidationError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


EXPECTED_MIMES: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/zip"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
    ".zip": {"application/zip", "application/x-zip", "application/x-zip-compressed"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".tif": {"image/tiff"}, ".tiff": {"image/tiff"},
    ".bmp": {"image/bmp", "image/x-ms-bmp"},
    ".mp4": {"video/mp4", "application/mp4"},
    ".mov": {"video/quicktime", "video/mp4"},
    ".avi": {"video/x-msvideo", "video/avi"},
    ".mkv": {"video/x-matroska", "application/octet-stream"},
    ".txt": {"text/plain"}, ".md": {"text/plain", "text/markdown"},
    ".csv": {"text/plain", "text/csv", "application/csv"},
    ".json": {"application/json", "text/plain"},
    ".xml": {"application/xml", "text/xml", "text/plain"},
}


def _magic_mime(data: bytes, suffix: str) -> str:
    if shutil.which("file"):
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            completed = subprocess.run(
                ["file", "--brief", "--mime-type", tmp.name],
                capture_output=True,
                check=False,
                timeout=10,
                text=True,
            )
        detected = completed.stdout.strip().lower()
        if detected:
            return detected
    # Conservative built-in fallback for environments without libmagic CLI.
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] in {b"II*\x00", b"MM\x00*"}:
        return "image/tiff"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and data[8:12] == b"AVI ":
        return "video/x-msvideo"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    return mimetypes.guess_type(f"x{suffix}")[0] or "application/octet-stream"


def _safe_zip(data: bytes, suffix: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos:
                raise FileValidationError("压缩包为空")
            if len(infos) > 5000:
                raise FileValidationError("压缩包文件条目过多")
            total_uncompressed = 0
            names: set[str] = set()
            for info in infos:
                name = info.filename.replace("\\", "/")
                names.add(name)
                parts = Path(name).parts
                if name.startswith("/") or ".." in parts:
                    raise FileValidationError("压缩包包含路径穿越条目")
                total_uncompressed += max(0, int(info.file_size))
                if info.compress_size and info.file_size / max(info.compress_size, 1) > 250:
                    raise FileValidationError("压缩包存在异常压缩比")
            if total_uncompressed > 750 * 1024 * 1024:
                raise FileValidationError("压缩包解压后体积过大")
            required = {
                ".docx": {"[Content_Types].xml", "word/document.xml"},
                ".pptx": {"[Content_Types].xml", "ppt/presentation.xml"},
                ".xlsx": {"[Content_Types].xml", "xl/workbook.xml"},
            }.get(suffix)
            if required and not required.issubset(names):
                missing = sorted(required - names)
                raise FileValidationError(f"Office 文件结构不完整：缺少 {', '.join(missing)}")
            # Validate central directory and CRCs for a bounded number of files.
            bad = archive.testzip()
            if bad:
                raise FileValidationError(f"压缩包 CRC 校验失败：{bad}")
            return {"entries": len(infos), "uncompressed_bytes": total_uncompressed}
    except zipfile.BadZipFile as exc:
        raise FileValidationError("文件不是有效 ZIP/Office 压缩结构") from exc


def validate_file_bytes(filename: str, data: bytes, declared_mime: str | None = None) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    detected = _magic_mime(data, suffix)
    expected = EXPECTED_MIMES.get(suffix, set())
    checks: list[dict[str, Any]] = [
        {"name": "extension", "ok": bool(expected), "value": suffix},
        {"name": "declared_mime", "ok": True, "value": declared_mime or None},
        {"name": "magic_mime", "ok": not expected or detected in expected, "value": detected, "expected": sorted(expected)},
    ]
    if expected and detected not in expected:
        # libmagic often reports OOXML as application/zip; already allowed above.
        raise FileValidationError(
            f"文件内容与扩展名不匹配：{suffix} 实际识别为 {detected}",
            details={"detected_mime_type": detected, "checks": checks},
        )

    details: dict[str, Any] = {"detected_mime_type": detected, "checks": checks, "parser": None}
    try:
        if suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise FileValidationError("PDF 魔数无效")
            reader = PdfReader(io.BytesIO(data), strict=False)
            details["parser"] = {"type": "pypdf", "pages": len(reader.pages)}
            if len(reader.pages) < 1:
                raise FileValidationError("PDF 不包含页面")
        elif suffix in {".docx", ".pptx", ".xlsx", ".zip"}:
            details["parser"] = {"type": "zip", **_safe_zip(data, suffix)}
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                details["parser"] = {"type": "Pillow", "format": image.format, "width": image.width, "height": image.height}
                if image.width * image.height > 100_000_000:
                    raise FileValidationError("图像像素数量过大")
        elif suffix in {".mp4", ".mov", ".avi", ".mkv"}:
            if not shutil.which("ffprobe"):
                raise FileValidationError("服务器未安装 ffprobe，无法安全验证视频")
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
                tmp.write(data); tmp.flush()
                completed = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,codec_name", "-of", "json", tmp.name],
                    capture_output=True, check=False, timeout=30, text=True,
                )
            if completed.returncode != 0:
                raise FileValidationError("ffprobe 无法识别该视频；文件可能损坏或伪造扩展名")
            parsed = json.loads(completed.stdout or "{}")
            streams = parsed.get("streams") or []
            if not any(item.get("codec_type") == "video" for item in streams):
                raise FileValidationError("媒体文件中没有可识别的视频流")
            details["parser"] = {"type": "ffprobe", **parsed}
        elif suffix == ".json":
            json.loads(data.decode("utf-8-sig"))
            details["parser"] = {"type": "json"}
        elif suffix == ".xml":
            ElementTree.fromstring(data)
            details["parser"] = {"type": "xml"}
        elif suffix in {".txt", ".md", ".csv"}:
            data.decode("utf-8-sig")
            details["parser"] = {"type": "utf-8"}
    except FileValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError, ElementTree.ParseError) as exc:
        raise FileValidationError(f"文件解析失败：{exc}", details=details) from exc
    except Exception as exc:
        raise FileValidationError(f"文件验证失败：{exc}", details=details) from exc

    details["valid"] = True
    return details
