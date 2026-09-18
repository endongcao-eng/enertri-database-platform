from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from docx import Document
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_service import AIFile, AIResponseError, AIUnavailableError, ai_service
from .artifacts import create_pptx, safe_filename
from .audit import write_audit
from .database import ARTIFACT_DIR, WORKSPACE_DIR, SessionLocal
from .file_service import register_generated_file
from .file_validation import FileValidationError, validate_file_bytes
from .task_queue import recover_expired_tasks
from .paper_pipeline import ingest_document
from .models import AIUsageRecord, KnowledgeDocument, SimulationArtifact, SimulationJob, TaskEvent, TaskFile, WorkspaceFile, WorkspaceTask
from .simulation import SUPPORTED_SOFTWARE, create_simulation_package

STEP_DELAY = float(os.getenv("TASK_STEP_DELAY_SECONDS", "0.05"))

PAPER_PROMPT = """请对论文进行结构化解析，区分原文事实、推断和未知信息。输出中文 Markdown，包含：文献信息、核心思想、材料/对象、方法参数、核心数据、结论、创新、局限、复现风险和建议核查位置。不得编造数据。"""


class TaskCancelled(Exception):
    pass


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except Exception:
        return {"raw": value}


def task_to_dict(task: WorkspaceTask, *, include_events: bool = False) -> dict[str, Any]:
    result = json_loads(task.result_json, {})
    data = {
        "id": task.id,
        "task_code": task.task_code,
        "task_type": task.task_type,
        "title": task.title,
        "user_id": task.user_id,
        "status": task.status,
        "progress": task.progress,
        "current_step": task.current_step,
        "input": json_loads(task.input_json, {}),
        "result": result,
        "error_message": task.error_message,
        "model_name": task.model_name,
        "model_version": task.model_version,
        "software_name": task.software_name,
        "software_version": task.software_version,
        "retry_of_id": task.retry_of_id,
        "worker_id": task.worker_id,
        "attempt_count": task.attempt_count,
        "heartbeat_at": task.heartbeat_at,
        "lease_expires_at": task.lease_expires_at,
        "last_claimed_at": task.last_claimed_at,
        "timeout_seconds": task.timeout_seconds,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }
    if include_events:
        data["events"] = [event_to_dict(event) for event in task.events]
    return data


def event_to_dict(event: TaskEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "level": event.level,
        "step": event.step,
        "progress": event.progress,
        "message": event.message,
        "data": json_loads(event.data_json, None),
        "created_at": event.created_at,
    }


def file_to_dict(record: WorkspaceFile) -> dict[str, Any]:
    return {
        "id": record.id,
        "original_name": record.original_name,
        "storage_name": record.storage_name,
        "file_type": record.file_type,
        "mime_type": record.mime_type,
        "detected_mime_type": record.detected_mime_type,
        "validation": json_loads(record.validation_json, None),
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "uploader_id": record.uploader_id,
        "task_id": record.task_id,
        "confidentiality": record.confidentiality,
        "parse_status": record.parse_status,
        "external_ai_allowed": record.external_ai_allowed,
        "duplicate_of_id": record.duplicate_of_id,
        "expires_at": record.expires_at,
        "created_at": record.created_at,
        "download_url": f"/api/files/{record.id}/download",
    }


def create_task(
    db: Session,
    *,
    user_id: int,
    task_type: str,
    title: str,
    input_data: Any,
    model_name: str | None = None,
    model_version: str | None = None,
    software_name: str | None = None,
    software_version: str | None = None,
    retry_of_id: int | None = None,
    timeout_seconds: int | None = None,
) -> WorkspaceTask:
    from .controls import task_admission
    task_admission(db, user_id)
    task = WorkspaceTask(
        task_code=str(uuid.uuid4()),
        user_id=user_id,
        task_type=task_type,
        title=title[:255],
        status="queued",
        progress=0,
        current_step="等待调度",
        input_json=json.dumps(input_data, ensure_ascii=False, default=str),
        model_name=model_name,
        model_version=model_version,
        software_name=software_name,
        software_version=software_version,
        retry_of_id=retry_of_id,
        timeout_seconds=timeout_seconds or int(os.getenv(f"TASK_TIMEOUT_{task_type.upper()}_SECONDS", os.getenv("TASK_DEFAULT_TIMEOUT_SECONDS", "1800"))),
    )
    db.add(task)
    db.flush()
    db.add(TaskEvent(task_id=task.id, event_type="status", step="等待调度", progress=0, message="任务已进入队列"))
    db.commit()
    db.refresh(task)
    return task


def link_file(db: Session, task_id: int, file_id: int, role: str) -> None:
    existing = db.get(TaskFile, {"task_id": task_id, "file_id": file_id})
    if not existing:
        db.add(TaskFile(task_id=task_id, file_id=file_id, file_role=role))
    file_record = db.get(WorkspaceFile, file_id)
    if file_record and not file_record.task_id:
        file_record.task_id = task_id
    db.commit()


def add_event(
    db: Session,
    task: WorkspaceTask,
    *,
    progress: int | None,
    step: str,
    message: str,
    event_type: str = "progress",
    level: str = "info",
    data: Any = None,
) -> None:
    db.refresh(task)
    if task.status == "cancelled":
        raise TaskCancelled()
    if progress is not None:
        task.progress = max(0, min(100, progress))
    task.current_step = step
    db.add(TaskEvent(
        task_id=task.id,
        event_type=event_type,
        level=level,
        step=step,
        progress=progress,
        message=message,
        data_json=json.dumps(data, ensure_ascii=False, default=str) if data is not None else None,
    ))
    db.commit()
    if STEP_DELAY:
        time.sleep(STEP_DELAY)


def _revalidate_record(db: Session, record: WorkspaceFile) -> dict[str, Any]:
    path = Path(record.storage_path)
    try:
        validation = validate_file_bytes(record.original_name, path.read_bytes(), record.mime_type)
    except FileValidationError as exc:
        record.parse_status = "failed"
        record.validation_json = json.dumps({"valid": False, "error": str(exc), **(exc.details or {})}, ensure_ascii=False, default=str)
        db.commit()
        raise RuntimeError(f"输入文件内容验证失败：{exc}") from exc
    record.detected_mime_type = validation.get("detected_mime_type")
    record.validation_json = json.dumps(validation, ensure_ascii=False, default=str)
    db.commit()
    return validation


def _extract_text(path: Path, suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".xml"}:
        return path.read_text(encoding="utf-8", errors="replace")[:120_000]
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:80])[:120_000]
    if suffix == ".docx":
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)[:120_000]
    return ""


def _local_paper_analysis(filename: str, text: str, focus: str) -> str:
    normalized = " ".join(text.split())
    excerpt = normalized[:1800] or "未能从文件中提取可读文本。"
    focus_line = focus.strip() or "未指定特别关注点"
    return f"""# 文献信息
- 文件：{filename}
- 解析模式：本地基础解析（未向外部 AI 发送文件）
- 特别关注：{focus_line}

# 核心思想
根据可提取文本，本论文围绕以下内容展开：{excerpt[:420]}

# 研究方法与关键参数
- 已完成文本层结构抽取；图片、公式和复杂表格仍需人工核查。
- 建议重点检查原文的 Materials/Methods、Results 和 Conclusion 部分。

# 核心数据
- 本地模式不对数值进行自动猜测或补全。
- 请在原文中核对单位、样本量、误差、对照组和统计显著性。

# 核心结论
{excerpt[420:840] or '当前文本不足以可靠归纳结论。'}

# 创新点与局限
- 可能创新点需结合作者明确声明和同领域文献对比确认。
- 当前结果未解析图像、扫描页和复杂公式，不能替代专家精读。

# 建议进一步核查的原文位置
- 摘要、方法、结果图表、讨论、结论、补充材料与数据可用性声明。
"""


def _paper_handler(db: Session, task: WorkspaceTask, payload: dict[str, Any]) -> dict[str, Any]:
    file_id = int(payload["file_id"])
    record = db.get(WorkspaceFile, file_id)
    if not record:
        raise RuntimeError("输入文件不存在")
    path = Path(record.storage_path)
    if not path.exists():
        record.parse_status = "failed"; db.commit()
        raise RuntimeError("输入文件已从存储中丢失")
    _revalidate_record(db, record)

    add_event(db, task, progress=12, step="校验文件", message="已完成扩展名、MIME、魔数、文件结构与解析器验证")
    text = _extract_text(path, path.suffix)
    record.parse_status = "parsing"
    db.commit()
    add_event(db, task, progress=35, step="提取内容", message=f"已提取 {len(text)} 个文本字符")

    allow_external = bool(record.external_ai_allowed) and record.confidentiality != "restricted"
    output: str
    mode = "local"
    if allow_external and ai_service.status().get("configured"):
        add_event(db, task, progress=55, step="模型分析", message="正在调用经授权的外部 AI 模型")
        try:
            ai_file = AIFile(filename=record.original_name, content=path.read_bytes(), content_type=record.mime_type)
            output = ai_service.generate_text(
                PAPER_PROMPT + (f"\n用户特别关注：{payload.get('focus')}" if payload.get("focus") else ""),
                files=[ai_file],
                instructions="你是材料、焊接和工程科研文献分析专家。",
                user_id=task.user_id, reasoning_effort="high",
            )
            mode = "external_ai"
            db.add(AIUsageRecord(task_id=task.id, user_id=task.user_id, provider="OpenAI-compatible", model=task.model_name or "configured-model", external=True))
            db.commit()
        except (AIUnavailableError, AIResponseError) as exc:
            add_event(db, task, progress=62, step="本地降级", message=f"外部 AI 不可用，切换本地解析：{exc}", level="warning")
            output = _local_paper_analysis(record.original_name, text, payload.get("focus", ""))
    else:
        reason = "文件保密策略禁止外发" if not allow_external else "未配置外部 AI"
        add_event(db, task, progress=58, step="本地解析", message=reason)
        output = _local_paper_analysis(record.original_name, text, payload.get("focus", ""))

    record.parse_status = "parsed"
    db.commit()
    add_event(db, task, progress=86, step="整理结果", message="正在生成结构化解析结果")
    return {
        "analysis_markdown": output,
        "analysis_mode": mode,
        "input_file_id": record.id,
        "external_ai_used": mode == "external_ai",
        "download_files": [],
    }


def _ppt_handler(db: Session, task: WorkspaceTask, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or task.title)
    source_text = str(payload.get("source_text") or "").strip()
    add_event(db, task, progress=15, step="解析提纲", message="正在从输入内容提取汇报结构")
    if not source_text:
        source_text = "# 项目概览\n- 研究背景与目标\n- 技术路线\n- 当前结果\n- 风险与下一步"
    content = source_text
    if payload.get("use_external_ai") and ai_service.status().get("configured"):
        add_event(db, task, progress=42, step="优化内容", message="正在调用外部 AI 优化学术汇报结构")
        try:
            content = ai_service.generate_text(
                f"请把以下内容整理为学术汇报PPT的Markdown提纲，每页一个二级标题、3-6条要点，不编造数据。\n\n{source_text}",
                instructions="你是严谨的学术汇报编辑。",
                user_id=task.user_id, reasoning_effort="medium",
            )
            db.add(AIUsageRecord(task_id=task.id, user_id=task.user_id, provider="OpenAI-compatible", model=task.model_name or "configured-model", external=True))
            db.commit()
        except (AIUnavailableError, AIResponseError) as exc:
            add_event(db, task, progress=50, step="本地降级", message=f"AI 优化不可用，使用本地提纲：{exc}", level="warning")
    add_event(db, task, progress=68, step="生成PPT", message="正在生成可编辑的 16:9 PPTX 文件")
    task_dir = ARTIFACT_DIR / f"task_{task.id}"
    filename = safe_filename(title, ".pptx")
    path = task_dir / filename
    create_pptx(path, title, content)
    record = register_generated_file(db, task.user_id, path, task_id=task.id, confidentiality="internal")
    link_file(db, task.id, record.id, "output")
    add_event(db, task, progress=90, step="登记成果", message="PPT 已写入统一文件库并完成权限登记")
    return {
        "summary": "PPT 生成完成",
        "output_file_id": record.id,
        "download_url": f"/api/files/{record.id}/download",
        "download_files": [file_to_dict(record)],
    }


def _probe_video(path: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    metadata: dict[str, Any] = {"filename": path.name, "size_bytes": path.stat().st_size}
    if not shutil.which("ffprobe"):
        warnings.append("服务器未安装 ffprobe，仅记录文件级信息。")
        return metadata, warnings
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,format_name,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
        if completed.returncode != 0:
            warnings.append("ffprobe 无法解析该视频，可能是文件损坏或编码不受支持。")
            return metadata, warnings
        raw = json.loads(completed.stdout.decode("utf-8", errors="replace") or "{}")
        metadata["format"] = raw.get("format") or {}
        metadata["streams"] = raw.get("streams") or []
    except Exception as exc:
        warnings.append(f"视频元数据读取失败：{exc}")
    return metadata, warnings


def _video_local_report(record: WorkspaceFile, metadata: dict[str, Any], warnings: list[str], focus: str, frame_count: int) -> str:
    fmt = metadata.get("format") or {}
    streams = metadata.get("streams") or []
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    duration = fmt.get("duration") or "未知"
    return f"""# 视频分析报告

## 文件信息
- 文件：{record.original_name}
- 大小：{record.size_bytes} bytes
- SHA-256：{record.sha256}
- 保密等级：{record.confidentiality}
- 外部 AI：未使用

## 媒体元数据
- 容器：{fmt.get('format_name') or '未知'}
- 时长：{duration} s
- 视频编码：{video_stream.get('codec_name') or '未知'}
- 分辨率：{video_stream.get('width') or '未知'} × {video_stream.get('height') or '未知'}
- 帧率：{video_stream.get('avg_frame_rate') or video_stream.get('r_frame_rate') or '未知'}
- 已抽取关键帧：{frame_count}

## 用户关注点
{focus.strip() or '未指定'}

## 基础结论
- 已完成文件校验、媒体元数据读取和关键帧抽取尝试。
- 本地模式不对焊缝缺陷、熔池状态或质量等级做无依据判定。
- 可靠质量分析仍需结合时间轴、电流/电压/速度、标定尺度、工件位置和 NDT/试验标签。

## 警告与限制
{chr(10).join(f'- {item}' for item in warnings) if warnings else '- 未发现媒体解析警告；仍需人工核验视频内容。'}
"""


def _video_handler(db: Session, task: WorkspaceTask, payload: dict[str, Any]) -> dict[str, Any]:
    record = db.get(WorkspaceFile, int(payload["file_id"]))
    if not record:
        raise RuntimeError("输入视频不存在")
    path = Path(record.storage_path)
    if not path.exists():
        record.parse_status = "failed"; db.commit()
        raise RuntimeError("输入视频已从存储中丢失")
    _revalidate_record(db, record)
    add_event(db, task, progress=12, step="校验视频", message="已完成扩展名、MIME、魔数与 ffprobe 可解析性验证")
    metadata, warnings = _probe_video(path)
    add_event(db, task, progress=34, step="读取元数据", message="已读取视频容器、编码、时长和流信息")

    frames: list[AIFile] = []
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory(prefix=f"enertri_video_{task.id}_") as tmp:
            pattern = Path(tmp) / "frame_%02d.jpg"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", "fps=1/3,scale=1280:-2", "-frames:v", "8", str(pattern)]
            try:
                completed = subprocess.run(command, capture_output=True, check=False, timeout=90)
                if completed.returncode == 0:
                    frames = [AIFile(filename=item.name, content=item.read_bytes(), content_type="image/jpeg", detail="high") for item in sorted(Path(tmp).glob("frame_*.jpg"))]
                else:
                    warnings.append("ffmpeg 关键帧抽取失败，报告仅包含媒体元数据。")
            except Exception as exc:
                warnings.append(f"关键帧抽取失败：{exc}")
            add_event(db, task, progress=58, step="抽取关键帧", message=f"关键帧抽取完成，共 {len(frames)} 帧")
            allow_external = bool(record.external_ai_allowed and record.confidentiality != "restricted")
            mode = "local"
            if allow_external and ai_service.status().get("configured") and frames:
                add_event(db, task, progress=70, step="模型分析", message="正在调用经授权的外部 AI 分析关键帧")
                try:
                    report = ai_service.generate_text(
                        f"分析焊接/工程视频关键帧。关注点：{payload.get('focus') or '过程稳定性、异常事件与质量线索'}。区分观察、推断和未知；不得编造时间、尺寸或缺陷等级。",
                        files=frames,
                        instructions="你是焊接视频与工程视觉分析专家。",
                        user_id=task.user_id, reasoning_effort="high",
                    )
                    mode = "external_ai"
                    db.add(AIUsageRecord(task_id=task.id, user_id=task.user_id, provider="OpenAI-compatible", model=task.model_name or "configured-model", external=True))
                    db.commit()
                except (AIUnavailableError, AIResponseError) as exc:
                    warnings.append(f"外部 AI 不可用，已降级为本地报告：{exc}")
                    report = _video_local_report(record, metadata, warnings, str(payload.get("focus") or ""), len(frames))
            else:
                report = _video_local_report(record, metadata, warnings, str(payload.get("focus") or ""), len(frames))
    else:
        warnings.append("服务器未安装 ffmpeg，未抽取关键帧。")
        add_event(db, task, progress=58, step="抽取关键帧", message="ffmpeg 不可用，跳过关键帧抽取", level="warning")
        mode = "local"
        report = _video_local_report(record, metadata, warnings, str(payload.get("focus") or ""), 0)

    add_event(db, task, progress=84, step="生成报告", message="正在生成并登记视频分析报告")
    task_dir = ARTIFACT_DIR / f"task_{task.id}"
    report_path = task_dir / safe_filename(f"{Path(record.original_name).stem}_视频分析", ".md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    output = register_generated_file(db, task.user_id, report_path, task_id=task.id, confidentiality=record.confidentiality)
    link_file(db, task.id, output.id, "output")
    record.parse_status = "parsed"
    db.commit()
    return {
        "summary": "视频分析完成",
        "analysis_mode": mode,
        "metadata": metadata,
        "warnings": warnings,
        "input_file_id": record.id,
        "output_file_id": output.id,
        "download_url": f"/api/files/{output.id}/download",
        "download_files": [file_to_dict(output)],
    }


def _simulation_package_handler(db: Session, task: WorkspaceTask, payload: dict[str, Any]) -> dict[str, Any]:
    software = str(payload.get("software") or "")
    if software not in SUPPORTED_SOFTWARE:
        raise RuntimeError("不支持的仿真软件")
    name = str(payload.get("name") or task.title)
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise RuntimeError("仿真参数必须是 JSON 对象")
    add_event(db, task, progress=14, step="校验参数", message=f"已校验 {SUPPORTED_SOFTWARE[software]} 参数与任务元数据")
    workdir = WORKSPACE_DIR / "simulations" / f"task_{task.id}"
    sim_job = SimulationJob(
        user_id=task.user_id,
        workspace_task_id=task.id,
        name=name[:255],
        software=software,
        software_version=str(payload.get("software_version") or "unspecified"),
        status="running",
        parameters_json=json.dumps(parameters, ensure_ascii=False),
        workdir=str(workdir),
    )
    db.add(sim_job)
    db.commit()
    db.refresh(sim_job)
    try:
        add_event(db, task, progress=42, step="生成输入", message="正在生成前处理、求解器输入和参数清单")
        archive = create_simulation_package(workdir, name, software, parameters)
        add_event(db, task, progress=76, step="打包成果", message="仿真输入文件已压缩为 ZIP")
        sim_job.package_path = str(archive)
        sim_job.status = "completed"
        result = {"status": "completed", "package": archive.name, "software": software}
        sim_job.result_json = json.dumps(result, ensure_ascii=False)
        db.commit()
        output = register_generated_file(db, task.user_id, archive, task_id=task.id, confidentiality="internal")
        link_file(db, task.id, output.id, "output")
        db.add(SimulationArtifact(simulation_job_id=sim_job.id, task_id=task.id, file_id=output.id, artifact_type="input_package", metadata_json=json.dumps({"software": software, "software_version": sim_job.software_version}, ensure_ascii=False)))
        db.commit()
        add_event(db, task, progress=92, step="登记成果", message="仿真输入包已写入统一文件库和仿真成果表")
        return {
            "summary": "仿真输入包生成完成",
            "simulation_job_id": sim_job.id,
            "software": software,
            "software_label": SUPPORTED_SOFTWARE[software],
            "output_file_id": output.id,
            "download_url": f"/api/files/{output.id}/download",
            "download_files": [file_to_dict(output)],
        }
    except Exception:
        sim_job.status = "failed"
        db.commit()
        raise


def _paper_ingest_handler(db: Session, task: WorkspaceTask, payload: dict[str, Any]) -> dict[str, Any]:
    document = db.get(KnowledgeDocument, int(payload["document_id"]))
    record = db.get(WorkspaceFile, int(payload["file_id"]))
    if not document or not record:
        raise RuntimeError("论文知识库文档或源文件不存在")
    if record.parse_status == "failed":
        document.status = "failed"; db.commit()
        raise RuntimeError("源文件在上传安全校验阶段已失败")
    document.status = "parsing"
    record.parse_status = "parsing"
    db.commit()
    try:
        _revalidate_record(db, record)
        result = ingest_document(
            db, document, record,
            progress=lambda progress, step, message: add_event(db, task, progress=progress, step=step, message=message),
        )
        return {
            **result,
            "summary": "论文已进入结构化知识库，可进行页码级证据问答",
            "document_url": f"/api/knowledge/documents/{document.id}",
            "qa_url": f"/api/knowledge/documents/{document.id}/qa",
            "input_file_id": record.id,
        }
    except Exception:
        document.status = "failed"
        record.parse_status = "failed"
        db.commit()
        raise


HANDLERS: dict[str, Callable[[Session, WorkspaceTask, dict[str, Any]], dict[str, Any]]] = {
    "paper_analysis": _paper_handler,
    "paper_ingest": _paper_ingest_handler,
    "ppt_generation": _ppt_handler,
    "video_analysis": _video_handler,
    "simulation_package": _simulation_package_handler,
}


def run_claimed_task(task_id: int, worker_id: str) -> None:
    """Execute a task only when an independent worker owns its active lease."""
    with SessionLocal() as db:
        task = db.get(WorkspaceTask, task_id)
        if not task or task.status != "running" or task.worker_id != worker_id:
            return
        handler = HANDLERS.get(task.task_type)
        if not handler:
            task.status = "failed"
            task.error_message = f"未注册任务处理器：{task.task_type}"
            task.finished_at = datetime.now(timezone.utc)
            task.lease_expires_at = None
            db.commit()
            return
        try:
            task.current_step = "启动任务"
            db.add(TaskEvent(task_id=task.id, event_type="status", step="启动任务", progress=task.progress, message=f"独立 Worker {worker_id} 开始执行任务"))
            db.commit()
            payload = json_loads(task.input_json, {})
            result = handler(db, task, payload)
            db.refresh(task)
            if task.status == "cancelled":
                return
            if task.worker_id != worker_id:
                raise RuntimeError("任务租约所有者发生变化，拒绝提交旧 Worker 的结果")
            task.status = "succeeded"
            task.progress = 100
            task.current_step = "已完成"
            task.result_json = json.dumps(result, ensure_ascii=False, default=str)
            task.finished_at = datetime.now(timezone.utc)
            task.heartbeat_at = datetime.now(timezone.utc)
            task.lease_expires_at = None
            db.add(TaskEvent(task_id=task.id, event_type="status", step="已完成", progress=100, message="任务执行成功"))
            write_audit(db, action="task.succeeded", resource_type="workspace_task", resource_id=task.id, actor_user_id=task.user_id, details={"task_type": task.task_type, "worker_id": worker_id, "attempt_count": task.attempt_count}, commit=False)
            db.commit()
        except TaskCancelled:
            task = db.get(WorkspaceTask, task_id)
            if task and task.worker_id == worker_id:
                task.status = "cancelled"
                task.finished_at = datetime.now(timezone.utc)
                task.lease_expires_at = None
                db.add(TaskEvent(task_id=task.id, event_type="status", level="warning", step="已取消", progress=task.progress, message="任务已取消"))
                db.commit()
        except Exception as exc:
            db.rollback()
            task = db.get(WorkspaceTask, task_id)
            if task and task.worker_id == worker_id and task.status != "cancelled":
                task.status = "failed"
                task.error_message = str(exc)
                task.current_step = "执行失败"
                task.finished_at = datetime.now(timezone.utc)
                task.lease_expires_at = None
                db.add(TaskEvent(task_id=task.id, event_type="error", level="error", step="执行失败", progress=task.progress, message=str(exc), data_json=json.dumps({"traceback": traceback.format_exc()[-8000:]}, ensure_ascii=False)))
                write_audit(db, action="task.failed", resource_type="workspace_task", resource_id=task.id, actor_user_id=task.user_id, outcome="failed", details={"error": str(exc), "worker_id": worker_id}, commit=False)
                db.commit()


def _run_inline_for_tests(task_id: int) -> None:
    worker_id = f"inline-test-{os.getpid()}"
    with SessionLocal() as db:
        task = db.get(WorkspaceTask, task_id)
        if not task or task.status != "queued":
            return
        now = datetime.now(timezone.utc)
        task.status = "running"
        task.worker_id = worker_id
        task.attempt_count = int(task.attempt_count or 0) + 1
        task.last_claimed_at = now
        task.heartbeat_at = now
        task.lease_expires_at = now
        task.started_at = now
        task.progress = 3
        db.commit()
    run_claimed_task(task_id, worker_id)


def submit_task(task_id: int) -> None:
    """Production mode only persists a queued task; the independent worker claims it.

    The explicit inline mode exists solely for deterministic unit tests and must not be used in deployment.
    """
    if os.getenv("TASK_EXECUTION_MODE", "database_worker").lower() == "inline":
        _run_inline_for_tests(task_id)


def recover_interrupted_tasks() -> int:
    # Backward-compatible name: V4.2 only recovers actually expired leases.
    return recover_expired_tasks()
