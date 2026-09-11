from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from .models import (
    Capability,
    DevelopmentGoal,
    KnowledgeNode,
    KnowledgeRelation,
    LearningResource,
    ResourceCapabilityLink,
    ResourceKnowledgeLink,
    ResearchProject,
    StudentEvidence,
    User,
)
from .project_matching_service import _candidate_from_profile, infer_requirement_draft, project_out
from .research_profile_service import build_profile


def to_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _loads(value: str | None) -> dict:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def goal_out(row: DevelopmentGoal, user: User | None = None) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_name": user.display_name if user else None,
        "goal_type": row.goal_type,
        "title": row.title,
        "description": row.description,
        "target_project_id": row.target_project_id,
        "requirements": _loads(row.requirements_json),
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _requirements_for_goal(db: Session, goal: DevelopmentGoal | None = None, *, title: str | None = None, description: str | None = None, target_project_id: int | None = None) -> dict:
    project_id = target_project_id if target_project_id is not None else (goal.target_project_id if goal else None)
    if project_id:
        project = db.get(ResearchProject, project_id)
        if not project:
            raise ValueError("target project not found")
        data = project_out(db, project)
        return {
            "source": "project_requirement_model",
            "title": data["title"],
            "description": data.get("description"),
            "capability_requirements": data["capability_requirements"],
            "knowledge_requirements": data["knowledge_requirements"],
            "note": "目标要求直接来自 V4.5 已确认项目需求模型。",
        }

    if goal:
        stored = _loads(goal.requirements_json)
        if stored.get("capability_requirements") or stored.get("knowledge_requirements"):
            return {"source": "saved_goal_requirement_model", **stored}
        title = goal.title
        description = goal.description
    draft = infer_requirement_draft(db, title or "科研发展目标", description)
    return {"source": "explainable_goal_draft", **draft}


def _gap_bundle(profile: dict, requirements: dict) -> tuple[dict, list[dict], list[dict]]:
    candidate = _candidate_from_profile(
        profile,
        requirements.get("capability_requirements", []),
        requirements.get("knowledge_requirements", []),
    )
    cap_gaps = []
    for row in candidate["capability_details"]:
        if row["satisfaction"] >= 95:
            continue
        severity = (100.0 - row["satisfaction"]) * to_float(row.get("weight"), 1.0) * (1.3 if row.get("is_critical") else 1.0)
        cap_gaps.append({**row, "gap_type": "capability", "severity": round(severity, 1)})
    knowledge_gaps = []
    for row in candidate["knowledge_details"]:
        if row["satisfaction"] >= 95:
            continue
        severity = (100.0 - row["satisfaction"]) * to_float(row.get("weight"), 1.0) * (1.3 if row.get("is_critical") else 1.0)
        knowledge_gaps.append({**row, "gap_type": "knowledge", "severity": round(severity, 1)})
    cap_gaps.sort(key=lambda x: x["severity"], reverse=True)
    knowledge_gaps.sort(key=lambda x: x["severity"], reverse=True)
    return candidate, cap_gaps, knowledge_gaps


def _resource_recommendations(db: Session, profile: dict, cap_gaps: list[dict], knowledge_gaps: list[dict]) -> list[dict]:
    evidenced = {row["resource_id"] for row in profile.get("evidence", [])}
    resources = db.scalars(select(LearningResource).where(LearningResource.status == "active").order_by(LearningResource.id)).all()
    cap_links: dict[int, list[ResourceCapabilityLink]] = defaultdict(list)
    for row in db.scalars(select(ResourceCapabilityLink)).all():
        cap_links[row.resource_id].append(row)
    knowledge_links: dict[int, list[ResourceKnowledgeLink]] = defaultdict(list)
    for row in db.scalars(select(ResourceKnowledgeLink)).all():
        knowledge_links[row.resource_id].append(row)

    cap_gap_map = {row["capability_id"]: row for row in cap_gaps}
    knowledge_gap_map = {row["knowledge_node_id"]: row for row in knowledge_gaps}
    current_knowledge = {row["id"]: row["score"] for row in profile.get("knowledge", [])}

    prerequisite_rows = db.execute(
        select(KnowledgeRelation, KnowledgeNode, KnowledgeNode)
        .join(KnowledgeNode, KnowledgeNode.id == KnowledgeRelation.source_node_id)
    ).all() if False else []
    # Explicit query kept simple for SQLite portability.
    prereq_by_target: dict[int, list[tuple[KnowledgeRelation, KnowledgeNode]]] = defaultdict(list)
    prereq_links = db.scalars(select(KnowledgeRelation).where(KnowledgeRelation.relation_type == "prerequisite")).all()
    node_map = {row.id: row for row in db.scalars(select(KnowledgeNode)).all()}
    for relation in prereq_links:
        source = node_map.get(relation.source_node_id)
        if source:
            prereq_by_target[relation.target_node_id].append((relation, source))

    denominator = sum(row["severity"] for row in cap_gaps) + 0.75 * sum(row["severity"] for row in knowledge_gaps)
    denominator = max(denominator, 1.0)
    out = []
    for resource in resources:
        if resource.id in evidenced:
            continue
        closure = []
        raw_gain = 0.0
        for link in cap_links.get(resource.id, []):
            gap = cap_gap_map.get(link.capability_id)
            if not gap:
                continue
            required = max(to_float(gap.get("required_level"), 1.0), 0.1)
            coverage = min(1.0, to_float(link.contribution_level) / required)
            strength = min(1.0, to_float(link.evidence_strength, 0.5))
            gain = gap["severity"] * coverage * strength
            raw_gain += gain
            closure.append({
                "type": "capability", "id": gap["capability_id"], "name_zh": gap["name_zh"],
                "current_satisfaction": gap["satisfaction"], "standard_level": round(to_float(link.contribution_level), 1),
                "potential_gap_closure": round(min(100.0 - gap["satisfaction"], coverage * strength * 100.0), 1),
            })
        covered_node_ids = []
        for link in knowledge_links.get(resource.id, []):
            gap = knowledge_gap_map.get(link.knowledge_node_id)
            if not gap:
                continue
            required = max(to_float(gap.get("required_level"), 1.0), 0.1)
            coverage = min(1.0, to_float(link.coverage_level) / required)
            strength = min(1.0, to_float(link.evidence_strength, 0.5))
            gain = 0.75 * gap["severity"] * coverage * strength
            raw_gain += gain
            covered_node_ids.append(link.knowledge_node_id)
            closure.append({
                "type": "knowledge", "id": gap["knowledge_node_id"], "name_zh": gap["name_zh"],
                "current_satisfaction": gap["satisfaction"], "standard_level": round(to_float(link.coverage_level), 1),
                "potential_gap_closure": round(min(100.0 - gap["satisfaction"], coverage * strength * 100.0), 1),
            })
        if raw_gain <= 0:
            continue
        unmet_prerequisites = []
        for node_id in covered_node_ids:
            for relation, source in prereq_by_target.get(node_id, []):
                current = to_float(current_knowledge.get(source.id))
                if current < 42:
                    unmet_prerequisites.append({
                        "knowledge_node_id": source.id,
                        "name_zh": source.name_zh,
                        "current_score": round(current, 1),
                        "relation_weight": round(to_float(relation.weight, 1.0), 2),
                    })
        unique_prereq = {row["knowledge_node_id"]: row for row in unmet_prerequisites}
        readiness_factor = 1.0 if not unique_prereq else max(0.62, 1.0 - 0.08 * len(unique_prereq))
        critical_capability_closure = any(
            item["type"] == "capability" and cap_gap_map.get(item["id"], {}).get("is_critical")
            for item in closure
        )
        # Project tasks should primarily convert a target capability into evidence. If a task only
        # touches a generic knowledge gap, keep it below courses/books that directly address the goal.
        task_relevance_factor = 1.0 if resource.resource_type != "project_task" or critical_capability_closure else 0.32
        priority = min(100.0, raw_gain / denominator * 300.0 * readiness_factor * task_relevance_factor)
        phase = "基础补齐" if resource.resource_type == "course" else ("系统深化" if resource.resource_type == "book" else "科研实践")
        if resource.resource_type == "course" and any(row.get("current_satisfaction", 100) < 55 for row in closure):
            phase = "基础补齐"
        out.append({
            "resource_id": resource.id,
            "code": resource.code,
            "resource_type": resource.resource_type,
            "title": resource.title,
            "subtitle": resource.subtitle,
            "discipline": resource.discipline,
            "provider": resource.provider,
            "description": resource.description,
            "priority_score": round(priority, 1),
            "phase": phase,
            "gap_closure": sorted(closure, key=lambda x: x["potential_gap_closure"], reverse=True)[:5],
            "unmet_prerequisites": list(unique_prereq.values()),
            "why": "；".join(f"补齐{x['name_zh']}（当前满足 {x['current_satisfaction']}%）" for x in sorted(closure, key=lambda y: y["potential_gap_closure"], reverse=True)[:3]),
        })
    phase_order = {"基础补齐": 0, "系统深化": 1, "科研实践": 2}
    out.sort(key=lambda x: (-x["priority_score"], phase_order.get(x["phase"], 9)))
    return out


def _learning_path(recommendations: list[dict]) -> list[dict]:
    courses = [x for x in recommendations if x["resource_type"] == "course"]
    books = [x for x in recommendations if x["resource_type"] == "book"]
    tasks = [x for x in recommendations if x["resource_type"] == "project_task"]
    steps = []
    selected_ids = set()
    for phase_no, (label, pool, limit) in enumerate((("基础补齐", courses, 3), ("系统深化", books, 2), ("科研实践", tasks, 2)), start=1):
        chosen = []
        for row in pool:
            if row["resource_id"] in selected_ids:
                continue
            chosen.append(row)
            selected_ids.add(row["resource_id"])
            if len(chosen) >= limit:
                break
        if chosen:
            steps.append({
                "phase": phase_no,
                "name": label,
                "goal": "优先补齐关键知识和方法先修" if label == "基础补齐" else ("建立更系统的专业知识网络" if label == "系统深化" else "用真实科研任务把知识转成可验证能力"),
                "resources": chosen,
            })
    return steps


def _literature_queries(requirements: dict, cap_gaps: list[dict], knowledge_gaps: list[dict]) -> list[dict]:
    title = requirements.get("title") or "目标科研方向"
    top_nodes = [row["name_zh"] for row in knowledge_gaps[:4]]
    top_caps = [row["name_zh"] for row in cap_gaps[:3]]
    candidates = []
    if top_nodes:
        candidates.append((f"{' '.join(top_nodes[:2])} 综述 review", "先用综述建立目标知识框架和常用方法谱系"))
        candidates.append((f"{title} {' '.join(top_nodes[:3])} 最新进展", "用于锁定与目标方向最相关的近期研究路线"))
    if top_caps:
        candidates.append((f"{title} {' '.join(top_caps[:2])} methodology benchmark", "重点寻找方法、验证和基准比较论文"))
    candidates.append((f"{title} research gap review", "用于识别研究空白和可形成课题的问题"))
    seen = set(); out = []
    for query, purpose in candidates:
        if query in seen:
            continue
        seen.add(query)
        out.append({"query": query, "purpose": purpose})
    return out[:4]


def _collaborators(db: Session, target_user_id: int, requirements: dict, cap_gaps: list[dict], knowledge_gaps: list[dict]) -> list[dict]:
    candidate_ids = db.scalars(
        select(distinct(StudentEvidence.user_id))
        .join(User, User.id == StudentEvidence.user_id)
        .where(User.is_active.is_(True), User.id != target_user_id, User.role.notin_(["admin", "system_admin"]))
    ).all()
    target_cap = {row["capability_id"]: row for row in cap_gaps}
    target_knowledge = {row["knowledge_node_id"]: row for row in knowledge_gaps}
    out = []
    for user_id in candidate_ids:
        profile = build_profile(db, int(user_id))
        fit = _candidate_from_profile(profile, requirements.get("capability_requirements", []), requirements.get("knowledge_requirements", []))
        weighted_sum = 0.0; denom = 0.0; covers = []
        for row in fit["capability_details"]:
            gap = target_cap.get(row["capability_id"])
            if not gap:
                continue
            weight = max(1.0, gap["severity"])
            weighted_sum += row["satisfaction"] * weight; denom += weight
            if row["satisfaction"] >= 75:
                covers.append({"name_zh": row["name_zh"], "satisfaction": row["satisfaction"], "type": "capability"})
        for row in fit["knowledge_details"]:
            gap = target_knowledge.get(row["knowledge_node_id"])
            if not gap:
                continue
            weight = max(1.0, gap["severity"] * 0.75)
            weighted_sum += row["satisfaction"] * weight; denom += weight
            if row["satisfaction"] >= 75:
                covers.append({"name_zh": row["name_zh"], "satisfaction": row["satisfaction"], "type": "knowledge"})
        complementarity = weighted_sum / denom if denom else fit["match_score"]
        out.append({
            "user_id": fit["user_id"], "display_name": fit["display_name"], "research_direction": fit["research_direction"],
            "target_match_score": fit["match_score"], "complementarity_score": round(complementarity, 1),
            "evidence_confidence": fit["evidence_confidence"],
            "covers_my_gaps": sorted(covers, key=lambda x: x["satisfaction"], reverse=True)[:4],
        })
    out.sort(key=lambda x: (x["complementarity_score"], x["target_match_score"], x["evidence_confidence"]), reverse=True)
    return out[:5]


def analyze_development_goal(db: Session, user_id: int, *, goal: DevelopmentGoal | None = None, title: str | None = None, description: str | None = None, target_project_id: int | None = None, goal_type: str | None = None) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("user not found")
    requirements = _requirements_for_goal(db, goal, title=title, description=description, target_project_id=target_project_id)
    profile = build_profile(db, user_id)
    fit, cap_gaps, knowledge_gaps = _gap_bundle(profile, requirements)
    recommendations = _resource_recommendations(db, profile, cap_gaps, knowledge_gaps)
    path = _learning_path(recommendations)
    critical_gaps = [x for x in cap_gaps + knowledge_gaps if x.get("is_critical") and x["satisfaction"] < 80]
    resolved_goal_type = goal_type or (goal.goal_type if goal else ("teacher_research_direction" if user.role in {"admin", "system_admin", "researcher"} else "student_growth"))
    result = {
        "stage": "V4.6 Stage 4",
        "goal": goal_out(goal, user) if goal else {
            "id": None, "user_id": user.id, "user_name": user.display_name, "goal_type": resolved_goal_type,
            "title": title or requirements.get("title"), "description": description, "target_project_id": target_project_id,
        },
        "profile_summary": profile["summary"],
        "target_requirements": requirements,
        "target_fit": {
            "match_score": fit["match_score"], "raw_fit": fit["raw_fit"], "capability_fit": fit["capability_fit"],
            "knowledge_fit": fit["knowledge_fit"], "evidence_confidence": fit["evidence_confidence"],
            "critical_gap_count": len(critical_gaps),
        },
        "capability_gaps": cap_gaps,
        "knowledge_gaps": knowledge_gaps,
        "recommendations": recommendations[:10],
        "course_recommendations": [x for x in recommendations if x["resource_type"] == "course"][:5],
        "book_recommendations": [x for x in recommendations if x["resource_type"] == "book"][:4],
        "practice_recommendations": [x for x in recommendations if x["resource_type"] == "project_task"][:4],
        "learning_path": path,
        "literature_queries": _literature_queries(requirements, cap_gaps, knowledge_gaps),
        "scoring_model": {
            "gap": "目标要求等级与当前证据画像等级比较；关键项缺口按 1.3 倍优先级处理。",
            "resource_priority": "资源对关键知识/能力缺口的标准覆盖 × 标准证据强度 × 当前缺口严重度，并受先修知识准备度修正。",
            "sequence": "课程优先补基础，专业书用于系统深化，项目任务用于把知识转化为可核验科研能力；存在薄弱先修时会显式提示。",
        },
    }
    if resolved_goal_type == "teacher_research_direction":
        result["collaborator_recommendations"] = _collaborators(db, user_id, requirements, cap_gaps, knowledge_gaps)
    return result


def seed_demo_development_planning(db: Session) -> dict[str, int]:
    admin = db.scalar(select(User).where(User.username == "admin"))
    student = db.scalar(select(User).where(User.username == "student"))
    if not admin or not student:
        return {"goals": 0, "teacher_evidence": 0}
    resources = {row.code: row for row in db.scalars(select(LearningResource)).all()}
    teacher_seeds = [
        ("R-COURSE-HEAT", "course_grade", "教师既有传热理论课程背景", 96, 1.0, None, 4.8, None, date(2019, 6, 20)),
        ("R-COURSE-NUM", "course_grade", "教师既有数值分析课程背景", 94, 1.0, None, 4.7, None, date(2019, 6, 20)),
        ("R-BOOK-MICRO", "book_reading", "教师微纳尺度传热专业书系统研读", None, 1.0, None, 4.8, None, date(2024, 5, 12)),
        ("R-TASK-MICRO", "project_participation", "教师微纳热输运数值研究项目", None, 1.0, 0.98, 4.9, 4.9, date(2026, 4, 8)),
    ]
    created_evidence = 0
    for code, evidence_type, title, grade, completion, independence, quality, mentor, occurred_on in teacher_seeds:
        resource = resources.get(code)
        if not resource:
            continue
        exists = db.scalar(select(StudentEvidence).where(StudentEvidence.user_id == admin.id, StudentEvidence.resource_id == resource.id, StudentEvidence.title == title))
        if exists:
            continue
        db.add(StudentEvidence(
            user_id=admin.id, resource_id=resource.id, evidence_type=evidence_type, title=title,
            grade_percent=grade, completion_ratio=completion, independence_ratio=independence,
            quality_rating=quality, mentor_rating=mentor, verification_status="verified", verified_by=admin.id,
            verification_note="V4.6 教师科研方向规划演示：既有知识/科研证据已核验。", occurred_on=occurred_on,
            notes="用于教师新方向知识差距分析演示。",
        ))
        created_evidence += 1
    db.flush()

    seed_goals = [
        (student.id, "student_growth", "芯片热管理与微纳热输运成长目标", "希望后续参与芯片热管理、微纳尺度传热与数值模拟方向项目，强化材料热物性、芯片热设计和科研计算能力。"),
        (admin.id, "teacher_research_direction", "图神经网络驱动的微纳材料热输运研究", "计划把 GNN 图神经网络、深度学习与微纳尺度传热、声子输运、材料热物性结合，使用 Python 建立可解释预测模型，并形成新的课题方向。"),
    ]
    created_goals = 0
    for user_id, goal_type, title, description in seed_goals:
        exists = db.scalar(select(DevelopmentGoal).where(DevelopmentGoal.user_id == user_id, DevelopmentGoal.title == title))
        if exists:
            continue
        requirements = infer_requirement_draft(db, title, description)
        db.add(DevelopmentGoal(
            user_id=user_id, goal_type=goal_type, title=title, description=description,
            requirements_json=json.dumps(requirements, ensure_ascii=False), status="active", created_by=admin.id,
        ))
        created_goals += 1
    db.commit()
    return {"goals": created_goals, "teacher_evidence": created_evidence, "teacher_user_id": admin.id, "student_user_id": student.id}
