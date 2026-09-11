from __future__ import annotations

import io
import json
import mimetypes
import math
import statistics
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_service import AIFile, AIResponseError, AIUnavailableError, ai_service
from .artifacts import create_docx, create_pptx, safe_filename
from .database import ARTIFACT_DIR, WORKSPACE_DIR, get_db
from .literature import research_hotspots, search_openalex
from .models import AssistantJob, SimulationJob, User
from .schemas import HotspotRequest, LiteratureSearchRequest, SimulationCreateRequest, TelemetryBatchRequest, WeldingRequest, WritingRequest
from .security import current_user, require_permission
from .simulation import SUPPORTED_SOFTWARE, create_simulation_package, execution_status, launch_simulation, refresh_result
from .welding import analyze_defect, analyze_elements, assess_weldability, process_plan, select_filler
from .permissions import has_permission
from .file_validation import FileValidationError, validate_file_bytes

router = APIRouter(prefix="/api/workspace", tags=["AI Research & Welding Workspace"])
MAX_FILE_BYTES = int(os.getenv("WORKSPACE_MAX_FILE_MB", "30")) * 1024 * 1024
MAX_FILES = int(os.getenv("WORKSPACE_MAX_FILES", "8"))
ALLOWED_ANALYSIS_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
ALLOWED_MULTIMODAL_SUFFIXES = ALLOWED_ANALYSIS_SUFFIXES | {".json", ".xml", ".mp4", ".mov", ".avi", ".mkv"}

RESEARCH_TASK_NAMES = {
    "literature_review": "文献综述",
    "academic_report": "学术报告",
    "grant_proposal": "科研基金申请书",
    "academic_ppt": "学术汇报 PPT",
    "production_report": "生产问题分析报告",
}

PAPER_ANALYSIS_PROMPT = """请以严谨的科研助理身份阅读所附论文。必须区分论文明确陈述的事实、你的推断和无法确认的信息。按以下结构输出中文 Markdown：
# 文献信息
# 核心思想
# 试验材料/研究对象
# 研究方法与关键参数
# 核心数据（尽可能保留单位、样本量、误差和对照）
# 核心结论
# 创新点
# 局限性与可复现性风险
# 与焊接/材料研究的潜在关联
# 建议进一步核查的原文位置
不得编造原文没有的数据；外文术语首次出现时给出中文翻译和原文。"""

IMAGE_PROMPTS = {
    "SEM": "分析 SEM 图像：形貌、尺寸、分布、断口机制、孔洞/裂纹/第二相，并指出仅凭图像不能确认的内容。若缺少标尺必须说明。",
    "TEM": "分析 TEM/HRTEM/SAED 图像：晶粒/位错/析出相/晶格条纹/衍射信息，并区分观察与推断。",
    "EBSD": "分析 EBSD 图：IPF、晶界、KAM、再结晶、织构和相分布；若图例或标尺不清，明确限制。",
    "EDS": "分析 EDS 面扫/线扫/能谱：元素富集、偏析、夹杂或第二相；提醒定量结果需校正、标准样和采集条件。",
    "spectrum": "分析所附光谱：峰位、峰强、峰宽、基线、可能物相/官能团及异常，避免在缺少标定时过度定量。",
    "Raman": "分析拉曼光谱：峰位、位移、FWHM、D/G 等可能指标、物相和应力/缺陷线索；明确需要原始数据和拟合条件。",
    "Xray_NDT": "按焊接射线检测思路分析底片/数字图像的缺陷类型、位置、形态和可能成因；不能替代持证人员按标准评级。",
    "UT": "按超声检测思路分析 A 扫/B 扫/C 扫波形或截图：回波位置、幅度、声程、可能反射体和耦合/几何干扰；不能替代校准与标准评级。",
    "weld_pool": "分析熔焊过程图像：电弧/熔池/匙孔/飞溅/焊缝成形、稳定性和缺陷线索，并提取可观察特征参数。",
}


def _job_to_dict(job: AssistantJob) -> dict[str, Any]:
    output_json = None
    if job.output_json:
        try:
            output_json = json.loads(job.output_json)
        except Exception:
            output_json = {"raw": job.output_json}
    return {
        "id": job.id,
        "domain": job.domain,
        "task_type": job.task_type,
        "title": job.title,
        "status": job.status,
        "output_text": job.output_text,
        "output_json": output_json,
        "artifact_url": f"/api/workspace/artifacts/{job.id}" if job.artifact_path else None,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _simulation_to_dict(job: SimulationJob) -> dict[str, Any]:
    result = None
    if job.result_json:
        try:
            result = json.loads(job.result_json)
        except Exception:
            result = {"raw": job.result_json}
    try:
        parameters = json.loads(job.parameters_json)
    except Exception:
        parameters = {}
    return {
        "id": job.id,
        "name": job.name,
        "software": job.software,
        "software_label": SUPPORTED_SOFTWARE.get(job.software, job.software),
        "status": job.status,
        "parameters": parameters,
        "package_url": f"/api/workspace/simulations/{job.id}/download" if job.package_path else None,
        "result": result,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _record_job(
    db: Session,
    user: User,
    *,
    domain: str,
    task_type: str,
    title: str,
    input_data: Any,
    output_text: str | None = None,
    output_json: Any = None,
    artifact_path: str | None = None,
    status: str = "completed",
) -> AssistantJob:
    job = AssistantJob(
        user_id=user.id,
        domain=domain,
        task_type=task_type,
        title=title[:255],
        status=status,
        input_json=json.dumps(input_data, ensure_ascii=False, default=str),
        output_text=output_text,
        output_json=json.dumps(output_json, ensure_ascii=False, default=str) if output_json is not None else None,
        artifact_path=artifact_path,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _read_upload(file: UploadFile, allowed: set[str]) -> AIFile:
    filename = Path(file.filename or "upload.bin").name
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式：{suffix or '无扩展名'}")
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"文件 {filename} 超过 {MAX_FILE_BYTES // 1024 // 1024} MB 限制")
    if not content:
        raise HTTPException(status_code=400, detail=f"文件 {filename} 为空")
    try:
        validate_file_bytes(filename, content, file.content_type)
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=f"文件 {filename} 安全校验失败：{exc}") from exc
    if suffix in {".tif", ".tiff", ".bmp"}:
        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 50_000_000:
                    raise HTTPException(status_code=413, detail=f"图像 {filename} 像素数过大")
                image.load()
                if image.width > 4096 or image.height > 4096:
                    image.thumbnail((4096, 4096))
                converted = image.convert("RGB")
                buffer = io.BytesIO()
                converted.save(buffer, format="PNG", optimize=True)
                filename = f"{Path(filename).stem}_converted.png"
                content = buffer.getvalue()
                return AIFile(filename=filename, content=content, content_type="image/png")
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status_code=400, detail=f"无法解析图像 {filename}：{exc}") from exc
    return AIFile(filename=filename, content=content, content_type=file.content_type or mimetypes.guess_type(filename)[0])


def _ai_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AIUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _writing_prompt(payload: WritingRequest) -> str:
    task_name = RESEARCH_TASK_NAMES[payload.task_type]
    references = json.dumps(payload.literature[:50], ensure_ascii=False, indent=2)
    data = json.dumps(payload.data, ensure_ascii=False, indent=2)
    specialized = {
        "literature_review": "形成有主题主线、研究分歧、方法比较、证据强弱、空白和未来方向的综述。引用仅使用所给文献，采用 [作者, 年份] 或 [序号] 占位，不得杜撰 DOI。",
        "academic_report": "采用摘要、背景、目标、材料与方法、结果、讨论、结论、局限和参考依据结构；数据不足处明确标注待补。",
        "grant_proposal": "采用立项依据、科学问题、研究目标、研究内容、技术路线、创新点、可行性、年度计划、预期成果、风险与替代方案结构。避免夸大和虚构前期成果。",
        "academic_ppt": "先输出适合 10–15 页专业学术 PPT 的 Markdown：每页以 ## 标题开始，下面 3–6 条短要点；包含问题、现状、方法、数据、讨论、结论和展望。",
        "production_report": "采用问题描述、材料与结构、过程数据、现象、根因树、证据、纠正措施、验证计划、责任与风险结构。",
    }[payload.task_type]
    return f"""请撰写《{payload.title}》的{task_name}。\n\n要求：{specialized}\n用户补充要求：{payload.instructions or '无'}\n\n原始思想/文本：\n{payload.source_text or '未提供'}\n\n结构化数据：\n{data}\n\n已给文献元数据：\n{references}\n\n输出中文 Markdown。事实、推断和建议必须清楚区分；对于缺失信息使用“待补充/需验证”，不得编造实验数据、文献或结论。"""


def _paper_review_prompt(literature: dict[str, Any]) -> str:
    return f"""请作为客观、严格且建设性的同行评审专家审阅所附研究论文，并结合下列检索到的相关文献元数据进行比对。\n\n相关文献：\n{json.dumps(literature, ensure_ascii=False, indent=2)}\n\n按以下结构输出中文 Markdown：\n# 总体评价与推荐意见（接收/小修/大修/拒稿，给出置信度）\n# 论文贡献和优点\n# 与现有文献相比的原创性\n# 研究设计与方法问题\n# 数据、统计和图表问题\n# 结论是否被证据支持\n# 可复现性、伦理和数据可用性\n# 必须修改的问题（编号）\n# 建议修改的问题（编号）\n# 给编辑的客观结论\n只能引用提供的文献元数据和论文原文；不得虚构比对文献内容。"""


def _maybe_augment(prompt: str, result: dict[str, Any], use_ai: bool, user_id: int) -> str | None:
    if not use_ai:
        return None
    try:
        return ai_service.generate_text(
            f"{prompt}\n\n规则引擎结果：\n{json.dumps(result, ensure_ascii=False, indent=2)}",
            instructions="你是焊接冶金和焊接工程专家。先尊重规则结果，再指出输入不足和验证要求；不要把初步建议写成已批准 WPS。",
            user_id=user_id, reasoning_effort="medium",
        )
    except (AIUnavailableError, AIResponseError) as exc:
        return f"AI 补充分析不可用：{exc}"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _telemetry_features(payload: TelemetryBatchRequest) -> dict[str, Any]:
    """Extract transparent, deterministic features from streamed welding telemetry."""
    channels: dict[str, list[float]] = {}
    timestamps_ms: list[float] = []
    ignored = 0
    reserved = {"timestamp_ms", "time_ms", "time_s", "timestamp", "values", "label"}
    for sample in payload.samples:
        merged: dict[str, Any] = {}
        values = sample.get("values")
        if isinstance(values, dict):
            merged.update(values)
        merged.update({k: v for k, v in sample.items() if k not in reserved})
        ts = _finite_number(sample.get("timestamp_ms", sample.get("time_ms")))
        if ts is None:
            time_s = _finite_number(sample.get("time_s"))
            if time_s is not None:
                ts = time_s * 1000.0
        if ts is not None:
            timestamps_ms.append(ts)
        found = False
        for key, value in merged.items():
            number = _finite_number(value)
            if number is None:
                continue
            channels.setdefault(str(key).strip().casefold(), []).append(number)
            found = True
        if not found:
            ignored += 1

    if not channels:
        raise HTTPException(status_code=422, detail="samples 中没有可分析的数值通道")

    stats: dict[str, dict[str, float | int | None]] = {}
    anomaly_count = 0
    total_points = 0
    for key, values in channels.items():
        count = len(values)
        mean = statistics.fmean(values)
        stdev = statistics.pstdev(values) if count > 1 else 0.0
        rms = math.sqrt(statistics.fmean([v * v for v in values]))
        cv = abs(stdev / mean) if abs(mean) > 1e-12 else None
        local_anomalies = sum(1 for v in values if stdev > 0 and abs(v - mean) / stdev > 3.0)
        anomaly_count += local_anomalies
        total_points += count
        stats[key] = {
            "count": count,
            "mean": round(mean, 6),
            "std": round(stdev, 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "rms": round(rms, 6),
            "cv": round(cv, 6) if cv is not None else None,
            "three_sigma_anomalies": local_anomalies,
        }

    sampling_rate_hz = None
    duration_s = None
    if len(timestamps_ms) >= 2:
        ordered = sorted(timestamps_ms)
        deltas = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
        if deltas:
            median_delta = statistics.median(deltas)
            sampling_rate_hz = round(1000.0 / median_delta, 3) if median_delta > 0 else None
            duration_s = round((ordered[-1] - ordered[0]) / 1000.0, 3)

    aliases = {
        "current": ("current_a", "current", "welding_current", "i"),
        "voltage": ("voltage_v", "voltage", "arc_voltage", "u"),
        "speed": ("travel_speed_mm_s", "travel_speed", "welding_speed_mm_s", "speed"),
    }
    def find_stat(kind: str):
        for name in aliases[kind]:
            if name in stats:
                return stats[name]
        return None

    current = find_stat("current")
    voltage = find_stat("voltage")
    speed = find_stat("speed")
    efficiency_value = _finite_number(payload.metadata.get("efficiency"))
    efficiency = efficiency_value if efficiency_value is not None and 0 < efficiency_value <= 1.5 else 0.8
    heat_input_kj_mm = None
    if current and voltage and speed and float(speed["mean"] or 0) > 0:
        heat_input_kj_mm = round(efficiency * float(current["mean"]) * float(voltage["mean"]) / float(speed["mean"]) / 1000.0, 4)

    findings: list[dict[str, Any]] = []
    score = 100.0
    for label, item, threshold, penalty in [
        ("焊接电流", current, 0.10, 18),
        ("电弧电压", voltage, 0.08, 18),
        ("焊接速度", speed, 0.10, 15),
    ]:
        if item and item.get("cv") is not None:
            cv = float(item["cv"])
            level = "稳定" if cv <= threshold * 0.5 else "需关注" if cv <= threshold else "波动较大"
            findings.append({"signal": label, "cv": cv, "assessment": level, "threshold": threshold})
            if cv > threshold:
                score -= min(penalty, penalty * cv / threshold)
    anomaly_ratio = anomaly_count / total_points if total_points else 0.0
    score -= min(20.0, anomaly_ratio * 400.0)
    score = round(max(0.0, min(100.0, score)), 1)
    grade = "稳定" if score >= 85 else "基本稳定" if score >= 70 else "需复核" if score >= 50 else "高风险"

    return {
        "session_id": payload.session_id,
        "process": payload.process,
        "sample_count": len(payload.samples),
        "ignored_samples": ignored,
        "channel_count": len(channels),
        "sampling_rate_hz_estimate": sampling_rate_hz,
        "duration_s": duration_s,
        "channel_statistics": stats,
        "derived_features": {
            "heat_input_kj_mm_estimate": heat_input_kj_mm,
            "efficiency_assumption": efficiency if heat_input_kj_mm is not None else None,
            "three_sigma_anomaly_ratio": round(anomaly_ratio, 6),
            "stability_findings": findings,
        },
        "preliminary_quality": {"score": score, "grade": grade, "known_quality": payload.known_quality},
        "limitations": [
            "评分基于通用统计稳定性规则，不等同于产品验收结论。",
            "通道名称、量纲、标定、同步和工件位置必须由采集网关保证。",
            "缺陷判定需结合图像、声学、温度场、焊缝几何和 NDT/破坏性试验标注验证。",
        ],
    }


@router.get("/status")
def workspace_status(_: User = Depends(current_user)):
    return {
        "version": "4.1.0",
        "ai": ai_service.status(),
        "literature": {"primary": "OpenAlex", "fallback": "Crossref", "openalex_api_key_configured": bool(os.getenv("OPENALEX_API_KEY"))},
        "simulation": execution_status(),
        "capabilities": {
            "research": ["全球文献检索", "研究热点", "论文结构化阅读", "文献综述", "学术报告", "基金申请书", "学术 PPT", "同行评审"],
            "production": ["焊接性", "合金元素", "工艺窗口", "焊材选择", "缺陷分析", "NDT 图像", "生产报告", "多模态特征", "实时数据接入", "质量评估"],
            "simulation": list(SUPPORTED_SOFTWARE),
        },
    }


@router.get("/jobs")
def list_jobs(limit: int = Query(default=30, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(AssistantJob).where(AssistantJob.user_id == user.id).order_by(AssistantJob.id.desc()).limit(limit)
    return [_job_to_dict(job) for job in db.scalars(stmt).all()]


@router.post("/literature/search")
def literature_search(payload: LiteratureSearchRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        result = search_openalex(**payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    job = _record_job(db, user, domain="research", task_type="literature_search", title=f"文献检索：{payload.query}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/literature/hotspots")
def literature_hotspots(payload: HotspotRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        result = research_hotspots(**payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    job = _record_job(db, user, domain="research", task_type="hotspots", title=f"研究热点：{payload.query}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/papers/analyze")
def analyze_paper(
    file: UploadFile = File(...),
    focus: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai.external")),
):
    ai_file = _read_upload(file, ALLOWED_ANALYSIS_SUFFIXES)
    prompt = PAPER_ANALYSIS_PROMPT + (f"\n用户特别关注：{focus}" if focus else "")
    try:
        output = ai_service.generate_text(prompt, files=[ai_file], instructions="你是材料、焊接和工程科研文献分析专家。", user_id=user.id, reasoning_effort="high")
    except (AIUnavailableError, AIResponseError) as exc:
        raise _ai_error(exc)
    job = _record_job(db, user, domain="research", task_type="paper_analysis", title=f"论文阅读：{ai_file.filename}", input_data={"filename": ai_file.filename, "focus": focus}, output_text=output)
    return _job_to_dict(job)


@router.post("/papers/review")
def review_paper(
    file: UploadFile = File(...),
    literature_query: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai.external")),
):
    ai_file = _read_upload(file, ALLOWED_ANALYSIS_SUFFIXES)
    literature = {"items": [], "warning": "未提供检索词"}
    if literature_query.strip():
        try:
            literature = search_openalex(literature_query.strip(), limit=15, sort="cited_by_count:desc")
        except Exception as exc:
            literature = {"items": [], "warning": str(exc)}
    try:
        output = ai_service.generate_text(_paper_review_prompt(literature), files=[ai_file], instructions="你是独立同行评审专家，不迎合作者。", user_id=user.id, reasoning_effort="high")
    except (AIUnavailableError, AIResponseError) as exc:
        raise _ai_error(exc)
    job = _record_job(db, user, domain="research", task_type="paper_review", title=f"论文审稿：{ai_file.filename}", input_data={"filename": ai_file.filename, "literature_query": literature_query}, output_text=output, output_json={"literature": literature})
    return _job_to_dict(job)


@router.post("/writing/generate")
def generate_writing(payload: WritingRequest, db: Session = Depends(get_db), user: User = Depends(require_permission("ai.external"))):
    try:
        output = ai_service.generate_text(_writing_prompt(payload), instructions="你是负责任的学术写作助手，禁止伪造数据、引用或研究成果。", user_id=user.id, reasoning_effort="high")
    except (AIUnavailableError, AIResponseError) as exc:
        raise _ai_error(exc)
    artifact_path = None
    if payload.output_format in {"docx", "pptx"}:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        job_dir = ARTIFACT_DIR / f"user_{user.id}"
        suffix = ".docx" if payload.output_format == "docx" else ".pptx"
        path = job_dir / f"{timestamp}_{safe_filename(payload.title, suffix)}"
        if payload.output_format == "docx":
            create_docx(path, payload.title, output, {"类型": RESEARCH_TASK_NAMES[payload.task_type]})
        else:
            create_pptx(path, payload.title, output)
        artifact_path = str(path)
    job = _record_job(db, user, domain="research" if payload.task_type != "production_report" else "production", task_type=payload.task_type, title=payload.title, input_data=payload.model_dump(), output_text=output, artifact_path=artifact_path)
    return _job_to_dict(job)


@router.get("/artifacts/{job_id}")
def download_artifact(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(AssistantJob, job_id)
    if not job or (job.user_id != user.id and user.role not in {"admin", "system_admin"}) or not job.artifact_path:
        raise HTTPException(status_code=404, detail="artifact not found")
    path = Path(job.artifact_path)
    if not path.exists() or ARTIFACT_DIR not in path.resolve().parents:
        raise HTTPException(status_code=404, detail="artifact file not found")
    return FileResponse(path, filename=path.name)


@router.post("/images/analyze")
def analyze_image(
    file: UploadFile = File(...),
    analysis_type: str = Form(default="SEM"),
    context: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai.external")),
):
    ai_file = _read_upload(file, {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".pdf"})
    base = IMAGE_PROMPTS.get(analysis_type, "分析该科研或工程图像，提取可观察特征、可能机制、定量线索和不确定性。")
    prompt = f"{base}\n样品/工艺背景：{context or '未提供'}\n按“观察结果—定量信息—机理解释—结论—局限—建议补充数据”输出。"
    try:
        output = ai_service.generate_text(prompt, files=[ai_file], instructions="你是材料表征和焊接检测专家。不得伪造标尺、峰值或定量数据。", user_id=user.id, reasoning_effort="high")
    except (AIUnavailableError, AIResponseError) as exc:
        raise _ai_error(exc)
    job = _record_job(db, user, domain="analysis", task_type=f"image_{analysis_type}", title=f"{analysis_type} 分析：{ai_file.filename}", input_data={"filename": ai_file.filename, "context": context}, output_text=output)
    return _job_to_dict(job)


def _extract_video_frames(ai_file: AIFile) -> tuple[list[AIFile], str | None]:
    if not shutil.which("ffmpeg"):
        return [], "服务器未安装 ffmpeg，视频未抽帧；请上传关键帧图片或安装 ffmpeg。"
    with tempfile.TemporaryDirectory(prefix="enertri_video_") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / ai_file.filename
        source.write_bytes(ai_file.content)
        pattern = tmp_path / "frame_%02d.jpg"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vf", "fps=1/2,scale=1280:-2", "-frames:v", "8", str(pattern)]
        completed = subprocess.run(command, capture_output=True, check=False, timeout=60)
        if completed.returncode != 0:
            return [], f"视频抽帧失败：{completed.stderr.decode('utf-8', errors='ignore')[:300]}"
        frames = [AIFile(filename=p.name, content=p.read_bytes(), content_type="image/jpeg", detail="high") for p in sorted(tmp_path.glob("frame_*.jpg"))]
        return frames, None


@router.post("/multimodal/analyze")
def analyze_multimodal(
    files: list[UploadFile] = File(...),
    task: str = Form(default="提取熔焊过程特征参数并进行缺陷判断和质量评估"),
    context: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai.external")),
):
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"请上传 1–{MAX_FILES} 个文件")
    ai_files: list[AIFile] = []
    warnings: list[str] = []
    names: list[str] = []
    for file in files:
        item = _read_upload(file, ALLOWED_MULTIMODAL_SUFFIXES)
        names.append(item.filename)
        if Path(item.filename).suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}:
            frames, warning = _extract_video_frames(item)
            ai_files.extend(frames)
            if warning:
                warnings.append(warning)
        else:
            ai_files.append(item)
    if not ai_files:
        raise HTTPException(status_code=400, detail="没有可供模型分析的文件；视频需安装 ffmpeg 或改传关键帧")
    prompt = f"""任务：{task}\n背景：{context or '未提供'}\n输入文件：{', '.join(names)}\n请融合图纸/文本/图像/过程数据，输出：\n1. 每个数据源识别结果与可信度\n2. 时间/空间/工件位置对齐假设\n3. 熔焊过程特征参数（弧长、熔池宽度、匙孔、飞溅、温度/电流/电压/速度等，只有可支持时才给数值）\n4. 异常事件和缺陷证据链\n5. 焊接质量分级及置信度\n6. 数据缺失、冲突和传感器质量问题\n7. 建议的复核/NDT/工艺措施\n不得把视觉猜测写成确定测量值。"""
    if warnings:
        prompt += "\n系统警告：" + "；".join(warnings)
    try:
        output = ai_service.generate_text(prompt, files=ai_files, instructions="你是焊接过程多模态感知和质量评估专家。", user_id=user.id, reasoning_effort="high")
    except (AIUnavailableError, AIResponseError) as exc:
        raise _ai_error(exc)
    job = _record_job(db, user, domain="production", task_type="multimodal_quality", title="焊接多模态质量评估", input_data={"files": names, "task": task, "context": context, "warnings": warnings}, output_text=output, output_json={"warnings": warnings})
    return _job_to_dict(job)


@router.post("/telemetry/ingest")
def ingest_telemetry(
    payload: TelemetryBatchRequest,
    use_ai: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    result = _telemetry_features(payload)
    if use_ai and not has_permission(user.role, "ai.external"):
        raise HTTPException(status_code=403, detail="当前角色不可调用外部 AI")
    if use_ai:
        result["ai_interpretation"] = _maybe_augment(
            "结合焊接时序特征判断过程稳定性、潜在缺陷模式和需追加的传感器或验证试验。不得把统计异常直接等同于缺陷。",
            result,
            True,
        )
    job = _record_job(
        db, user, domain="production", task_type="telemetry_quality",
        title=f"实时过程评估：{payload.session_id}",
        input_data={"session_id": payload.session_id, "process": payload.process, "sample_count": len(payload.samples), "metadata": payload.metadata, "known_quality": payload.known_quality},
        output_json=result,
    )
    return {"job": _job_to_dict(job), **result}


@router.post("/welding/weldability")
def welding_weldability(payload: WeldingRequest, use_ai: bool = Query(default=False), db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = assess_weldability(payload.model_dump())
    if use_ai and not has_permission(user.role, "ai.external"):
        raise HTTPException(status_code=403, detail="当前角色不可调用外部 AI")
    result["ai_interpretation"] = _maybe_augment("评估该材料的焊接性、缺陷和接头性能。", result, use_ai, user.id)
    job = _record_job(db, user, domain="production", task_type="weldability", title=f"焊接性：{payload.material_name or payload.base_material or '材料'}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/welding/elements")
def welding_elements(payload: WeldingRequest, use_ai: bool = Query(default=False), db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = {"elements": analyze_elements(payload.composition), "note": "元素作用依赖基体、含量、热处理和相互作用，以下为通用焊接冶金提示。"}
    if use_ai and not has_permission(user.role, "ai.external"):
        raise HTTPException(status_code=403, detail="当前角色不可调用外部 AI")
    result["ai_interpretation"] = _maybe_augment("分析各合金元素的协同作用和焊接影响。", result, use_ai, user.id)
    job = _record_job(db, user, domain="production", task_type="alloy_elements", title=f"合金元素：{payload.material_name or '材料'}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/welding/process")
def welding_process(payload: WeldingRequest, use_ai: bool = Query(default=False), db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = process_plan(payload.model_dump())
    if use_ai and not has_permission(user.role, "ai.external"):
        raise HTTPException(status_code=403, detail="当前角色不可调用外部 AI")
    result["ai_interpretation"] = _maybe_augment("审查并补充初步焊接工艺窗口和性能预测。", result, use_ai, user.id)
    job = _record_job(db, user, domain="production", task_type="process_plan", title=f"焊接工艺：{payload.material_name or '材料'}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/welding/filler")
def welding_filler(payload: WeldingRequest, use_ai: bool = Query(default=False), db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = select_filler(payload.model_dump())
    if use_ai and not has_permission(user.role, "ai.external"):
        raise HTTPException(status_code=403, detail="当前角色不可调用外部 AI")
    result["ai_interpretation"] = _maybe_augment("根据母材、服役条件和工艺选择焊材，并说明选择边界。", result, use_ai, user.id)
    job = _record_job(db, user, domain="production", task_type="filler_selection", title=f"焊材选择：{payload.material_name or payload.base_material or '材料'}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/welding/defect")
def welding_defect(payload: WeldingRequest, use_ai: bool = Query(default=False), db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = analyze_defect(payload.model_dump())
    if use_ai and not has_permission(user.role, "ai.external"):
        raise HTTPException(status_code=403, detail="当前角色不可调用外部 AI")
    result["ai_interpretation"] = _maybe_augment("结合材料、厚度、结构和过程背景分析缺陷根因与解决方案。", result, use_ai, user.id)
    job = _record_job(db, user, domain="production", task_type="defect_analysis", title=f"缺陷分析：{payload.defect_type or '未知'}", input_data=payload.model_dump(), output_json=result)
    return {"job": _job_to_dict(job), **result}


@router.post("/simulations")
def create_simulation(payload: SimulationCreateRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = SimulationJob(user_id=user.id, name=payload.name, software=payload.software, status="prepared", parameters_json=json.dumps(payload.parameters, ensure_ascii=False), workdir="pending")
    db.add(job)
    db.flush()
    workdir = WORKSPACE_DIR / "simulations" / f"job_{job.id}"
    archive = create_simulation_package(workdir, payload.name, payload.software, payload.parameters)
    job.workdir = str(workdir)
    job.package_path = str(archive)
    db.commit()
    db.refresh(job)
    return _simulation_to_dict(job)


@router.get("/simulations")
def list_simulations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(SimulationJob).where(SimulationJob.user_id == user.id).order_by(SimulationJob.id.desc()).limit(50)
    jobs = db.scalars(stmt).all()
    for job in jobs:
        result = refresh_result(Path(job.workdir))
        if result and result.get("status") != job.status:
            job.status = result.get("status", job.status)
            job.result_json = json.dumps(result, ensure_ascii=False)
    db.commit()
    return [_simulation_to_dict(job) for job in jobs]


@router.post("/simulations/{job_id}/run")
def run_simulation(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("simulation.commercial"))):
    job = db.get(SimulationJob, job_id)
    if not job or (job.user_id != user.id and not has_permission(user.role, "task.other.view")):
        raise HTTPException(status_code=404, detail="simulation job not found")
    try:
        pid = launch_simulation(job.id, job.software, Path(job.workdir))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job.status = "running"
    job.runner_pid = pid
    db.commit()
    db.refresh(job)
    return _simulation_to_dict(job)


@router.get("/simulations/{job_id}")
def get_simulation(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(SimulationJob, job_id)
    if not job or (job.user_id != user.id and user.role not in {"admin", "system_admin"}):
        raise HTTPException(status_code=404, detail="simulation job not found")
    result = refresh_result(Path(job.workdir))
    if result:
        job.status = result.get("status", job.status)
        job.result_json = json.dumps(result, ensure_ascii=False)
        db.commit()
        db.refresh(job)
    return _simulation_to_dict(job)


@router.get("/simulations/{job_id}/download")
def download_simulation(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(SimulationJob, job_id)
    if not job or (job.user_id != user.id and user.role not in {"admin", "system_admin"}) or not job.package_path:
        raise HTTPException(status_code=404, detail="simulation package not found")
    path = Path(job.package_path).resolve()
    if not path.exists() or WORKSPACE_DIR not in path.parents:
        raise HTTPException(status_code=404, detail="simulation package file not found")
    return FileResponse(path, filename=path.name, media_type="application/zip")
