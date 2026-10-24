from __future__ import annotations

import itertools
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from .models import (
    Capability,
    KnowledgeNode,
    ProjectCapabilityRequirement,
    ProjectKnowledgeRequirement,
    ResearchProject,
    StudentEvidence,
    User,
    LearningResource,
)
from .research_profile_service import build_profile


def to_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


CAPABILITY_KEYWORDS = {
    "C-ML-RESEARCH": ["机器学习", "machine learning", "预测", "回归", "分类", "ai", "人工智能", "深度学习", "图神经网络", "gnn", "pytorch"],
    "C-PYTHON": ["python", "编程", "脚本", "计算"],
    "C-DATA": ["数据", "拟合", "误差", "统计", "dataset", "数据集"],
    "C-HEAT-THEORY": ["传热", "热物性", "热导", "热输运", "热管理", "芯片热", "thermal", "heat"],
    "C-NUM-MODEL": ["数值", "建模", "模拟", "simulation", "求解", "模型"],
    "C-COMSOL": ["comsol", "多物理场", "有限元"],
    "C-LITERATURE": ["文献", "综述", "证据", "调研", "literature"],
    "C-WELD-PROCESS": ["焊接", "气孔", "熔池", "welding"],
}

KNOWLEDGE_KEYWORDS = {
    "K-MAT-THERMO": ["材料热物性", "热物性", "导热系数", "比热"],
    "K-ML-BASE": ["机器学习", "machine learning", "预测", "ai", "人工智能"],
    "K-PROG-PY": ["python"],
    "K-DATA-ANALYSIS": ["数据", "拟合", "误差", "统计", "数据集"],
    "K-MICRO-HEAT": ["微纳", "微尺度", "纳米", "micro", "nano"],
    "K-PHONON": ["声子", "phonon"],
    "K-WELD-LASER": ["激光焊", "laser welding"],
    "K-WELD-DEFECT": ["焊接缺陷", "气孔", "porosity"],
    "K-STAT-PHYS": ["统计物理", "统计力学", "statistical physics"],
    "K-MD": ["分子动力学", "molecular dynamics", "lammps", "md模拟"],
    "K-DL": ["深度学习", "deep learning", "神经网络", "pytorch"],
    "K-GNN": ["图神经网络", "gnn", "graph neural", "图表示"],
    "K-CHIP-THERM": ["芯片热", "芯片热管理", "封装热", "电子散热", "chip thermal"],
}


def project_out(db: Session, project: ResearchProject) -> dict:
    cap_rows = db.execute(
        select(ProjectCapabilityRequirement, Capability)
        .join(Capability, Capability.id == ProjectCapabilityRequirement.capability_id)
        .where(ProjectCapabilityRequirement.project_id == project.id)
        .order_by(ProjectCapabilityRequirement.is_critical.desc(), ProjectCapabilityRequirement.weight.desc())
    ).all()
    knowledge_rows = db.execute(
        select(ProjectKnowledgeRequirement, KnowledgeNode)
        .join(KnowledgeNode, KnowledgeNode.id == ProjectKnowledgeRequirement.knowledge_node_id)
        .where(ProjectKnowledgeRequirement.project_id == project.id)
        .order_by(ProjectKnowledgeRequirement.is_critical.desc(), ProjectKnowledgeRequirement.weight.desc())
    ).all()
    try:
        metadata = json.loads(project.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "research_direction": project.research_direction,
        "status": project.status,
        "created_by": project.created_by,
        "metadata": metadata,
        "capability_requirements": [
            {
                "id": row.id,
                "capability_id": capability.id,
                "code": capability.code,
                "name_zh": capability.name_zh,
                "category": capability.category,
                "required_level": round(to_float(row.required_level), 1),
                "weight": round(to_float(row.weight), 2),
                "is_critical": bool(row.is_critical),
                "note": row.note,
            }
            for row, capability in cap_rows
        ],
        "knowledge_requirements": [
            {
                "id": row.id,
                "knowledge_node_id": node.id,
                "code": node.code,
                "name_zh": node.name_zh,
                "domain": node.domain,
                "required_level": round(to_float(row.required_level), 1),
                "weight": round(to_float(row.weight), 2),
                "is_critical": bool(row.is_critical),
                "note": row.note,
            }
            for row, node in knowledge_rows
        ],
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def infer_requirement_draft(db: Session, title: str, description: str | None = None) -> dict:
    text = f"{title} {description or ''}".lower()
    capabilities = {row.code: row for row in db.scalars(select(Capability).where(Capability.status == "active")).all()}
    nodes = {row.code: row for row in db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active")).all()}
    cap_hits: list[dict] = []
    for code, keywords in CAPABILITY_KEYWORDS.items():
        matched = [kw for kw in keywords if kw.lower() in text]
        if not matched or code not in capabilities:
            continue
        strength = min(1.0, 0.45 + 0.18 * len(matched))
        cap = capabilities[code]
        cap_hits.append({
            "capability_id": cap.id,
            "code": cap.code,
            "name_zh": cap.name_zh,
            "required_level": round(2.8 + 1.2 * strength, 1),
            "weight": round(0.7 + 0.5 * strength, 2),
            "is_critical": code in {"C-ML-RESEARCH", "C-HEAT-THEORY", "C-NUM-MODEL", "C-WELD-PROCESS"} and strength >= 0.6,
            "matched_keywords": matched,
        })
    knowledge_hits: list[dict] = []
    for code, keywords in KNOWLEDGE_KEYWORDS.items():
        matched = [kw for kw in keywords if kw.lower() in text]
        if not matched or code not in nodes:
            continue
        strength = min(1.0, 0.45 + 0.18 * len(matched))
        node = nodes[code]
        knowledge_hits.append({
            "knowledge_node_id": node.id,
            "code": node.code,
            "name_zh": node.name_zh,
            "required_level": round(2.6 + 1.2 * strength, 1),
            "weight": round(0.55 + 0.45 * strength, 2),
            "is_critical": code in {"K-ML-BASE", "K-MAT-THERMO", "K-MICRO-HEAT", "K-WELD-DEFECT", "K-GNN", "K-DL", "K-CHIP-THERM"} and strength >= 0.6,
            "matched_keywords": matched,
        })
    if not any(item["code"] == "C-LITERATURE" for item in cap_hits) and "C-LITERATURE" in capabilities:
        cap = capabilities["C-LITERATURE"]
        cap_hits.append({"capability_id": cap.id, "code": cap.code, "name_zh": cap.name_zh, "required_level": 2.5, "weight": 0.45, "is_critical": False, "matched_keywords": ["科研通用"]})
    if not cap_hits:
        for code in ("C-LITERATURE", "C-DATA"):
            cap = capabilities.get(code)
            if cap:
                cap_hits.append({"capability_id": cap.id, "code": cap.code, "name_zh": cap.name_zh, "required_level": 2.5, "weight": 0.6, "is_critical": False, "matched_keywords": ["通用科研能力"]})
    cap_hits.sort(key=lambda x: (x["is_critical"], x["weight"]), reverse=True)
    knowledge_hits.sort(key=lambda x: (x["is_critical"], x["weight"]), reverse=True)
    return {
        "title": title,
        "capability_requirements": cap_hits,
        "knowledge_requirements": knowledge_hits,
        "note": "V4.5 Stage 3 使用可解释关键词规则生成需求草案；老师确认后再写入正式项目要求，避免 AI 自动标签直接成为硬性筛选条件。",
    }


def _requirement_satisfaction(current_level: float, required_level: float) -> float:
    if required_level <= 0:
        return 100.0
    return round(min(1.0, max(0.0, current_level / required_level)) * 100.0, 1)


def _weighted_average(details: list[dict]) -> float:
    denom = sum(max(float(item["weight"]), 0.0) for item in details)
    if denom <= 0:
        return 0.0
    return sum(float(item["satisfaction"]) * float(item["weight"]) for item in details) / denom


def _candidate_from_profile(profile: dict, cap_requirements: list[dict], knowledge_requirements: list[dict]) -> dict:
    cap_map = {row["id"]: row for row in profile["capabilities"]}
    knowledge_map = {row["id"]: row for row in profile["knowledge"]}
    cap_details = []
    for req in cap_requirements:
        row = cap_map.get(req["capability_id"], {})
        current_level = to_float(row.get("score")) / 20.0
        satisfaction = _requirement_satisfaction(current_level, req["required_level"])
        cap_details.append({
            **req,
            "current_level": round(current_level, 2),
            "current_score": round(to_float(row.get("score")), 1),
            "satisfaction": satisfaction,
            "direct_evidence_score": round(to_float(row.get("direct_evidence_score")), 1),
            "knowledge_readiness_score": round(to_float(row.get("knowledge_readiness_score")), 1),
        })
    knowledge_details = []
    for req in knowledge_requirements:
        row = knowledge_map.get(req["knowledge_node_id"], {})
        current_level = to_float(row.get("score")) / 20.0
        satisfaction = _requirement_satisfaction(current_level, req["required_level"])
        knowledge_details.append({
            **req,
            "current_level": round(current_level, 2),
            "current_score": round(to_float(row.get("score")), 1),
            "satisfaction": satisfaction,
        })
    cap_fit = _weighted_average(cap_details) if cap_details else 0.0
    knowledge_fit = _weighted_average(knowledge_details) if knowledge_details else cap_fit
    raw_fit = 0.8 * cap_fit + 0.2 * knowledge_fit if knowledge_details else cap_fit
    critical = [x for x in cap_details + knowledge_details if x["is_critical"]]
    critical_deficit = _weighted_average([{**x, "satisfaction": max(0.0, 65.0 - x["satisfaction"])} for x in critical]) if critical else 0.0
    confidence = to_float(profile["summary"].get("evidence_confidence")) / 100.0
    confidence_factor = 0.90 + 0.10 * confidence
    total = max(0.0, raw_fit * confidence_factor - 0.18 * critical_deficit)
    advantages = [x for x in cap_details if x["satisfaction"] >= 90.0]
    gaps = sorted(
        [x for x in cap_details + knowledge_details if x["satisfaction"] < 82.0],
        key=lambda x: (100.0 - x["satisfaction"]) * x["weight"] * (1.25 if x["is_critical"] else 1.0),
        reverse=True,
    )
    profile_info = profile["profile"]
    return {
        "user_id": profile_info["user_id"],
        "display_name": profile_info["display_name"],
        "username": profile_info["username"],
        "research_direction": profile_info.get("research_direction"),
        "match_score": round(total, 1),
        "raw_fit": round(raw_fit, 1),
        "capability_fit": round(cap_fit, 1),
        "knowledge_fit": round(knowledge_fit, 1),
        "evidence_confidence": round(confidence * 100.0, 1),
        "critical_deficit": round(critical_deficit, 1),
        "capability_details": cap_details,
        "knowledge_details": knowledge_details,
        "advantages": advantages[:4],
        "gaps": gaps[:5],
        "summary": {
            "strength": "、".join(item["name_zh"] for item in advantages[:2]) or "当前没有达到 90% 的明确优势项",
            "gap": "、".join(item["name_zh"] for item in gaps[:2]) or "无明显关键能力缺口",
        },
    }


def build_project_matches(db: Session, project_id: int) -> dict:
    project = db.get(ResearchProject, project_id)
    if not project:
        raise ValueError("project not found")
    project_data = project_out(db, project)
    cap_requirements = project_data["capability_requirements"]
    knowledge_requirements = project_data["knowledge_requirements"]
    candidate_ids = db.scalars(
        select(distinct(StudentEvidence.user_id))
        .join(User, User.id == StudentEvidence.user_id)
        .where(User.is_active.is_(True), User.role.notin_(["admin", "system_admin"]))
    ).all()
    candidates = []
    for user_id in candidate_ids:
        profile = build_profile(db, int(user_id))
        candidates.append(_candidate_from_profile(profile, cap_requirements, knowledge_requirements))
    candidates.sort(key=lambda x: (x["match_score"], x["evidence_confidence"]), reverse=True)
    return {
        "stage": "V4.5 Stage 3",
        "project": project_data,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "scoring_model": {
            "fit": "能力要求按 80% 权重、明确知识要求按 20% 权重计算；若项目没有独立知识要求，则全部由能力要求决定。",
            "confidence": "最终分乘以 90%~100% 的证据可信度系数，避免大量未核验自报证据形成虚高排名。",
            "critical": "关键要求低于 65% 时会产生额外缺口惩罚；最终页面同时展示原始满足度和缺口，不只展示总分。",
        },
    }


def build_team_recommendations(db: Session, project_id: int, team_size: int = 3, limit: int = 5) -> dict:
    data = build_project_matches(db, project_id)
    candidates = data["candidates"][:12]
    team_size = max(2, min(4, int(team_size)))
    if len(candidates) < team_size:
        return {"stage": "V4.5 Stage 3", "project": data["project"], "team_size": team_size, "teams": []}
    project_caps = data["project"]["capability_requirements"]
    project_knowledge = data["project"]["knowledge_requirements"]
    teams = []
    for members in itertools.combinations(candidates, team_size):
        cap_coverage = []
        for req in project_caps:
            coverage_by_member = []
            for member in members:
                detail = next((x for x in member["capability_details"] if x["capability_id"] == req["capability_id"]), None)
                coverage_by_member.append((member, detail["satisfaction"] if detail else 0.0))
            best_member, best = max(coverage_by_member, key=lambda x: x[1])
            cap_coverage.append({**req, "satisfaction": best, "best_member_id": best_member["user_id"], "best_member_name": best_member["display_name"]})
        knowledge_coverage = []
        for req in project_knowledge:
            coverage_by_member = []
            for member in members:
                detail = next((x for x in member["knowledge_details"] if x["knowledge_node_id"] == req["knowledge_node_id"]), None)
                coverage_by_member.append((member, detail["satisfaction"] if detail else 0.0))
            best_member, best = max(coverage_by_member, key=lambda x: x[1])
            knowledge_coverage.append({**req, "satisfaction": best, "best_member_id": best_member["user_id"], "best_member_name": best_member["display_name"]})
        cap_fit = _weighted_average(cap_coverage) if cap_coverage else 0.0
        knowledge_fit = _weighted_average(knowledge_coverage) if knowledge_coverage else cap_fit
        coverage = 0.8 * cap_fit + 0.2 * knowledge_fit if knowledge_coverage else cap_fit
        best_individual = max(member["raw_fit"] for member in members)
        complementarity = max(0.0, coverage - best_individual)
        confidence = sum(member["evidence_confidence"] for member in members) / len(members)
        score = min(100.0, coverage * (0.94 + 0.06 * confidence / 100.0) + min(5.0, complementarity * 0.12))
        roles_by_user: dict[int, list[dict]] = defaultdict(list)
        for req in cap_coverage:
            roles_by_user[req["best_member_id"]].append({"name": req["name_zh"], "satisfaction": req["satisfaction"], "weight": req["weight"]})
        member_out = []
        for member in members:
            roles = sorted(roles_by_user.get(member["user_id"], []), key=lambda x: (x["weight"], x["satisfaction"]), reverse=True)[:3]
            member_out.append({
                "user_id": member["user_id"],
                "display_name": member["display_name"],
                "individual_match": member["match_score"],
                "suggested_responsibilities": [x["name"] for x in roles] or ["协同支持 / 补充验证"],
            })
        gaps = sorted([x for x in cap_coverage + knowledge_coverage if x["satisfaction"] < 85.0], key=lambda x: (100 - x["satisfaction"]) * x["weight"], reverse=True)
        teams.append({
            "team_score": round(score, 1),
            "coverage_score": round(coverage, 1),
            "complementarity_gain": round(complementarity, 1),
            "evidence_confidence": round(confidence, 1),
            "members": member_out,
            "coverage": cap_coverage,
            "remaining_gaps": gaps[:5],
        })
    teams.sort(key=lambda x: (x["team_score"], x["complementarity_gain"]), reverse=True)
    return {
        "stage": "V4.5 Stage 3",
        "project": data["project"],
        "team_size": team_size,
        "teams": teams[: max(1, min(limit, 10))],
        "note": "团队分数按每个项目要求由团队中最适合的成员承担来计算，并展示职责建议与剩余缺口；它不是简单把个人分数相加。",
    }


def seed_demo_project_matching(db: Session, hash_password_func) -> dict[str, int]:
    admin = db.scalar(select(User).where(User.username == "admin"))
    if not admin:
        return {"users": 0, "evidence": 0, "projects": 0}

    user_seed = [
        ("student_ml", "林同学", "材料机器学习与科研数据建模"),
        ("student_sim", "周同学", "微纳热输运与数值模拟"),
        ("student_data", "王同学", "实验数据分析与焊接缺陷机理"),
    ]
    users: dict[str, User] = {}
    created_users = 0
    for username, display_name, direction in user_seed:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            user = User(username=username, password_hash=hash_password_func("123456"), role="learning_user", display_name=display_name, research_direction=direction)
            db.add(user); db.flush(); created_users += 1
        users[username] = user

    resources = {row.code: row for row in db.scalars(select(LearningResource)).all()}
    evidence_seed = [
        ("student_ml", "R-COURSE-ML", "course_grade", "机器学习基础课程成绩", 94, 1.0, None, 4.7, None, date(2026, 1, 18)),
        ("student_ml", "R-TASK-ML-THERMO", "project_participation", "材料热物性机器学习预测项目", None, 1.0, 0.90, 4.8, 4.8, date(2026, 7, 20)),
        ("student_ml", "R-COURSE-NUM", "course_grade", "数值分析课程成绩", 86, 1.0, None, 4.1, None, date(2025, 6, 20)),
        ("student_sim", "R-COURSE-HEAT", "course_grade", "传热学课程成绩", 93, 1.0, None, 4.6, None, date(2025, 1, 18)),
        ("student_sim", "R-COURSE-NUM", "course_grade", "数值分析课程成绩", 95, 1.0, None, 4.7, None, date(2025, 6, 20)),
        ("student_sim", "R-BOOK-MICRO", "book_reading", "微纳传热专业书系统阅读", None, 0.92, None, 4.6, None, date(2026, 2, 10)),
        ("student_sim", "R-TASK-MICRO", "project_participation", "微纳热输运数值模拟主任务", None, 1.0, 0.92, 4.8, 4.9, date(2026, 7, 5)),
        ("student_data", "R-COURSE-ML", "course_grade", "机器学习基础课程成绩", 86, 1.0, None, 4.0, None, date(2026, 1, 18)),
        ("student_data", "R-TASK-WELD", "project_participation", "激光焊接缺陷数据与证据分析", None, 1.0, 0.88, 4.7, 4.6, date(2026, 7, 10)),
    ]
    created_evidence = 0
    for username, resource_code, evidence_type, title, grade, completion, independence, quality, mentor, occurred_on in evidence_seed:
        user = users.get(username)
        resource = resources.get(resource_code)
        if not user or not resource:
            continue
        exists = db.scalar(select(StudentEvidence).where(StudentEvidence.user_id == user.id, StudentEvidence.resource_id == resource.id, StudentEvidence.title == title))
        if exists:
            continue
        db.add(StudentEvidence(
            user_id=user.id,
            resource_id=resource.id,
            evidence_type=evidence_type,
            title=title,
            grade_percent=grade,
            completion_ratio=completion,
            independence_ratio=independence,
            quality_rating=quality,
            mentor_rating=mentor,
            verification_status="verified",
            verified_by=admin.id,
            verification_note="V4.5 演示数据：已由导师核验。",
            occurred_on=occurred_on,
            notes="用于第三阶段项目人才匹配与团队互补演示。",
        ))
        created_evidence += 1
    db.flush()

    project = db.scalar(select(ResearchProject).where(ResearchProject.title == "基于机器学习的材料热物性预测"))
    created_projects = 0
    if not project:
        project = ResearchProject(
            title="基于机器学习的材料热物性预测",
            description="整理材料导热系数等热物性数据，使用 Python 建立机器学习预测模型，完成交叉验证、误差分析，并结合传热机理解释模型结果。",
            research_direction="材料热物性 × 人工智能",
            status="active",
            created_by=admin.id,
            metadata_json=json.dumps({"seed": "v4.5-stage3", "project_type": "research"}, ensure_ascii=False),
        )
        db.add(project); db.flush(); created_projects = 1

    caps = {row.code: row for row in db.scalars(select(Capability)).all()}
    nodes = {row.code: row for row in db.scalars(select(KnowledgeNode)).all()}
    cap_requirements = [
        ("C-ML-RESEARCH", 4.0, 1.25, True, "核心建模能力"),
        ("C-PYTHON", 3.5, 1.00, True, "需独立完成数据与模型代码"),
        ("C-DATA", 3.5, 1.00, True, "负责数据清洗、验证与误差分析"),
        ("C-HEAT-THEORY", 3.0, 0.85, False, "需要正确解释热物性与传热含义"),
        ("C-LITERATURE", 2.5, 0.50, False, "完成数据来源和相关方法调研"),
    ]
    for code, level, weight, critical, note in cap_requirements:
        cap = caps.get(code)
        if not cap:
            continue
        exists = db.scalar(select(ProjectCapabilityRequirement).where(ProjectCapabilityRequirement.project_id == project.id, ProjectCapabilityRequirement.capability_id == cap.id))
        if not exists:
            db.add(ProjectCapabilityRequirement(project_id=project.id, capability_id=cap.id, required_level=level, weight=weight, is_critical=critical, note=note))
    knowledge_requirements = [
        ("K-ML-BASE", 4.0, 1.0, True, "模型训练与验证基础"),
        ("K-MAT-THERMO", 3.0, 0.8, True, "理解预测对象的物理含义"),
        ("K-PROG-PY", 3.0, 0.7, False, "科研计算工具基础"),
    ]
    for code, level, weight, critical, note in knowledge_requirements:
        node = nodes.get(code)
        if not node:
            continue
        exists = db.scalar(select(ProjectKnowledgeRequirement).where(ProjectKnowledgeRequirement.project_id == project.id, ProjectKnowledgeRequirement.knowledge_node_id == node.id))
        if not exists:
            db.add(ProjectKnowledgeRequirement(project_id=project.id, knowledge_node_id=node.id, required_level=level, weight=weight, is_critical=critical, note=note))
    db.commit()
    return {"users": created_users, "evidence": created_evidence, "projects": created_projects, "project_id": project.id}
