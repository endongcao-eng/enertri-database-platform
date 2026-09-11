from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Capability,
    CapabilityKnowledgeLink,
    KnowledgeNode,
    LearningResource,
    ResourceCapabilityLink,
    ResourceKnowledgeLink,
    StudentEvidence,
    User,
)

VERIFICATION_FACTORS = {
    "self_reported": 0.72,
    "pending": 0.80,
    "verified": 1.00,
    "rejected": 0.12,
}

EVIDENCE_TYPE_LABELS = {
    "course_grade": "课程成绩",
    "book_reading": "专业书阅读",
    "project_participation": "科研项目参与",
}


def to_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def combined_score(contributions: list[float]) -> float:
    remaining = 1.0
    for contribution in contributions:
        remaining *= 1.0 - clamp(contribution, 0.0, 0.96)
    return round((1.0 - remaining) * 100.0, 1)


def evidence_effectiveness(row: StudentEvidence) -> float:
    completion = clamp(to_float(row.completion_ratio, 1.0))
    quality = clamp(to_float(row.quality_rating, 3.0) / 5.0)
    if row.evidence_type == "course_grade":
        grade = clamp(to_float(row.grade_percent, 75.0) / 100.0)
        # A course provides knowledge evidence, but the score still depends on demonstrated mastery.
        return clamp((0.35 + 0.65 * grade) * (0.78 + 0.22 * completion))
    if row.evidence_type == "book_reading":
        # Reading alone is weaker than assessed/project evidence; depth/quality prevents “owned the book” inflation.
        return clamp(0.20 + 0.50 * completion + 0.30 * quality)
    independence = clamp(to_float(row.independence_ratio, 0.5))
    mentor = clamp(to_float(row.mentor_rating, 0.0) / 5.0)
    # Projects are strongest when the student independently delivers high-quality work confirmed by a mentor.
    return clamp(0.12 + 0.36 * independence + 0.25 * quality + 0.27 * mentor)


def verification_factor(row: StudentEvidence) -> float:
    # V4.7 route-completion records are provisional assertions until a teacher verifies them.
    # They may nudge the live profile so the user can see a provisional effect, but they must
    # not carry the same trust as a manually reviewed pending record or verified evidence.
    if row.verification_status in {"self_reported", "pending"}:
        try:
            meta = json.loads(row.metadata_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if meta.get("source") == "v4.7_dynamic_roadmap":
            return 0.35
    return VERIFICATION_FACTORS.get(row.verification_status, 0.65)


def _metadata(row: StudentEvidence) -> dict:
    try:
        return json.loads(row.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}


def evidence_out(row: StudentEvidence, resource: LearningResource | None = None, verifier: User | None = None) -> dict:
    effectiveness = evidence_effectiveness(row)
    verification = verification_factor(row)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "resource_id": row.resource_id,
        "resource_code": resource.code if resource else None,
        "resource_title": resource.title if resource else None,
        "resource_type": resource.resource_type if resource else None,
        "evidence_type": row.evidence_type,
        "evidence_type_label": EVIDENCE_TYPE_LABELS.get(row.evidence_type, row.evidence_type),
        "title": row.title,
        "grade_percent": to_float(row.grade_percent) if row.grade_percent is not None else None,
        "completion_ratio": to_float(row.completion_ratio, 1.0),
        "independence_ratio": to_float(row.independence_ratio) if row.independence_ratio is not None else None,
        "quality_rating": to_float(row.quality_rating) if row.quality_rating is not None else None,
        "mentor_rating": to_float(row.mentor_rating) if row.mentor_rating is not None else None,
        "verification_status": row.verification_status,
        "verification_factor": round(verification, 3),
        "effectiveness": round(effectiveness, 3),
        "personal_evidence_strength": round(effectiveness * verification, 3),
        "verified_by": row.verified_by,
        "verifier_name": verifier.display_name if verifier else None,
        "verification_note": row.verification_note,
        "occurred_on": row.occurred_on.isoformat() if row.occurred_on else None,
        "notes": row.notes,
        "metadata": _metadata(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _maturity(score: float) -> tuple[float, str]:
    level = round(score / 20.0, 1)
    if score >= 85:
        label = "复杂任务 / 可指导"
    elif score >= 70:
        label = "独立科研任务"
    elif score >= 50:
        label = "常规任务 / 少量指导"
    elif score >= 30:
        label = "基础掌握 / 需要指导"
    else:
        label = "接触或待补齐"
    return level, label


def build_profile(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("user not found")

    evidence_rows = db.scalars(
        select(StudentEvidence).where(StudentEvidence.user_id == user_id).order_by(StudentEvidence.occurred_on.desc(), StudentEvidence.id.desc())
    ).all()
    resource_ids = {row.resource_id for row in evidence_rows}
    resources = {row.id: row for row in db.scalars(select(LearningResource).where(LearningResource.id.in_(resource_ids))).all()} if resource_ids else {}
    verifier_ids = {row.verified_by for row in evidence_rows if row.verified_by}
    verifiers = {row.id: row for row in db.scalars(select(User).where(User.id.in_(verifier_ids))).all()} if verifier_ids else {}

    knowledge_links_by_resource: dict[int, list[tuple[ResourceKnowledgeLink, KnowledgeNode]]] = defaultdict(list)
    capability_links_by_resource: dict[int, list[tuple[ResourceCapabilityLink, Capability]]] = defaultdict(list)
    if resource_ids:
        for link, node in db.execute(
            select(ResourceKnowledgeLink, KnowledgeNode)
            .join(KnowledgeNode, KnowledgeNode.id == ResourceKnowledgeLink.knowledge_node_id)
            .where(ResourceKnowledgeLink.resource_id.in_(resource_ids))
        ).all():
            knowledge_links_by_resource[link.resource_id].append((link, node))
        for link, capability in db.execute(
            select(ResourceCapabilityLink, Capability)
            .join(Capability, Capability.id == ResourceCapabilityLink.capability_id)
            .where(ResourceCapabilityLink.resource_id.in_(resource_ids))
        ).all():
            capability_links_by_resource[link.resource_id].append((link, capability))

    knowledge_contribs: dict[int, list[float]] = defaultdict(list)
    knowledge_traces: dict[int, list[dict]] = defaultdict(list)
    direct_cap_contribs: dict[int, list[float]] = defaultdict(list)
    direct_cap_traces: dict[int, list[dict]] = defaultdict(list)

    for evidence in evidence_rows:
        resource = resources.get(evidence.resource_id)
        if not resource:
            continue
        eff = evidence_effectiveness(evidence)
        verify = verification_factor(evidence)
        personal_strength = eff * verify
        for link, node in knowledge_links_by_resource.get(resource.id, []):
            contribution = clamp((to_float(link.coverage_level) / 5.0) * to_float(link.weight, 1.0) * to_float(link.evidence_strength, 0.5) * personal_strength, 0.0, 0.96)
            knowledge_contribs[node.id].append(contribution)
            knowledge_traces[node.id].append({
                "evidence_id": evidence.id,
                "evidence_type": evidence.evidence_type,
                "verification_status": evidence.verification_status,
                "resource_id": resource.id,
                "resource_type": resource.resource_type,
                "resource_title": resource.title,
                "standard_level": round(to_float(link.coverage_level), 2),
                "personal_evidence_strength": round(personal_strength, 3),
                "contribution": round(contribution * 100, 1),
            })
        for link, capability in capability_links_by_resource.get(resource.id, []):
            contribution = clamp((to_float(link.contribution_level) / 5.0) * to_float(link.weight, 1.0) * to_float(link.evidence_strength, 0.5) * personal_strength, 0.0, 0.96)
            direct_cap_contribs[capability.id].append(contribution)
            direct_cap_traces[capability.id].append({
                "evidence_id": evidence.id,
                "evidence_type": evidence.evidence_type,
                "verification_status": evidence.verification_status,
                "resource_id": resource.id,
                "resource_type": resource.resource_type,
                "resource_title": resource.title,
                "standard_level": round(to_float(link.contribution_level), 2),
                "personal_evidence_strength": round(personal_strength, 3),
                "contribution": round(contribution * 100, 1),
            })

    all_nodes = db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active").order_by(KnowledgeNode.domain, KnowledgeNode.id)).all()
    knowledge_scores: dict[int, float] = {node.id: combined_score(knowledge_contribs.get(node.id, [])) for node in all_nodes}
    knowledge_items = []
    for node in all_nodes:
        score = knowledge_scores[node.id]
        level, maturity = _maturity(score)
        traces = sorted(knowledge_traces.get(node.id, []), key=lambda x: x["contribution"], reverse=True)
        knowledge_items.append({
            "id": node.id,
            "code": node.code,
            "name_zh": node.name_zh,
            "name_en": node.name_en,
            "domain": node.domain,
            "node_type": node.node_type,
            "score": score,
            "estimated_level": level,
            "maturity": maturity,
            "evidence_count": len(traces),
            "trace": traces,
        })

    all_capabilities = db.scalars(select(Capability).where(Capability.status == "active").order_by(Capability.category, Capability.id)).all()
    capability_requirement_rows = db.execute(
        select(CapabilityKnowledgeLink, KnowledgeNode)
        .join(KnowledgeNode, KnowledgeNode.id == CapabilityKnowledgeLink.knowledge_node_id)
        .order_by(CapabilityKnowledgeLink.capability_id, CapabilityKnowledgeLink.id)
    ).all()
    requirements_by_capability: dict[int, list[tuple[CapabilityKnowledgeLink, KnowledgeNode]]] = defaultdict(list)
    for link, node in capability_requirement_rows:
        requirements_by_capability[link.capability_id].append((link, node))

    capability_items = []
    for capability in all_capabilities:
        direct = combined_score(direct_cap_contribs.get(capability.id, []))
        requirements = requirements_by_capability.get(capability.id, [])
        readiness_numerator = 0.0
        readiness_denominator = 0.0
        requirement_details = []
        for link, node in requirements:
            node_score = knowledge_scores.get(node.id, 0.0)
            node_level = node_score / 20.0
            required_level = max(to_float(link.required_level, 1.0), 0.1)
            ratio = clamp(node_level / required_level)
            weight = max(to_float(link.weight, 1.0), 0.0)
            readiness_numerator += ratio * weight
            readiness_denominator += weight
            requirement_details.append({
                "knowledge_node_id": node.id,
                "name_zh": node.name_zh,
                "relation_type": link.relation_type,
                "required_level": round(required_level, 1),
                "current_level": round(node_level, 1),
                "readiness": round(ratio * 100, 1),
                "weight": round(weight, 2),
            })
        readiness = round((readiness_numerator / readiness_denominator * 100.0) if readiness_denominator else 0.0, 1)
        # Knowledge can support a capability, but it cannot fully replace direct task evidence.
        score = round((0.72 * direct + 0.28 * readiness) if direct > 0 else (0.45 * readiness), 1)
        level, maturity = _maturity(score)
        traces = sorted(direct_cap_traces.get(capability.id, []), key=lambda x: x["contribution"], reverse=True)
        capability_items.append({
            "id": capability.id,
            "code": capability.code,
            "name_zh": capability.name_zh,
            "name_en": capability.name_en,
            "category": capability.category,
            "description": capability.description,
            "score": score,
            "estimated_level": level,
            "maturity": maturity,
            "direct_evidence_score": direct,
            "knowledge_readiness_score": readiness,
            "evidence_count": len(traces),
            "trace": traces,
            "requirements": requirement_details,
        })

    capability_items.sort(key=lambda x: x["score"], reverse=True)
    knowledge_items.sort(key=lambda x: x["score"], reverse=True)

    evidenced_resource_ids = set(resource_ids)
    all_resource_knowledge = db.execute(
        select(ResourceKnowledgeLink, LearningResource)
        .join(LearningResource, LearningResource.id == ResourceKnowledgeLink.resource_id)
        .where(LearningResource.status == "active")
    ).all()
    recommendations_by_node: dict[int, list[dict]] = defaultdict(list)
    for link, resource in all_resource_knowledge:
        if resource.id in evidenced_resource_ids:
            continue
        recommendations_by_node[link.knowledge_node_id].append({
            "resource_id": resource.id,
            "resource_type": resource.resource_type,
            "title": resource.title,
            "coverage_level": round(to_float(link.coverage_level), 1),
        })

    gap_map: dict[int, dict] = {}
    for capability in capability_items:
        if capability["score"] < 20 and capability["direct_evidence_score"] <= 0:
            continue
        for requirement in capability["requirements"]:
            if requirement["relation_type"] != "requires" or requirement["readiness"] >= 72:
                continue
            node_id = requirement["knowledge_node_id"]
            node = next((n for n in all_nodes if n.id == node_id), None)
            if not node:
                continue
            severity = round((100 - requirement["readiness"]) * requirement["weight"], 1)
            item = gap_map.setdefault(node_id, {
                "knowledge_node_id": node_id,
                "name_zh": node.name_zh,
                "domain": node.domain,
                "current_score": knowledge_scores.get(node_id, 0.0),
                "severity": 0.0,
                "blocking_capabilities": [],
                "recommended_resources": sorted(recommendations_by_node.get(node_id, []), key=lambda x: x["coverage_level"], reverse=True)[:3],
            })
            item["severity"] = max(item["severity"], severity)
            if capability["name_zh"] not in item["blocking_capabilities"]:
                item["blocking_capabilities"].append(capability["name_zh"])
    gaps = sorted(gap_map.values(), key=lambda x: x["severity"], reverse=True)[:8]

    domains: dict[str, list[dict]] = defaultdict(list)
    for item in knowledge_items:
        domains[item["domain"]].append(item)
    knowledge_domains = []
    for domain, items in domains.items():
        active_scores = [x["score"] for x in items if x["score"] > 0]
        knowledge_domains.append({
            "domain": domain,
            "node_count": len(items),
            "evidenced_nodes": sum(1 for x in items if x["score"] > 0),
            "average_score": round(sum(active_scores) / len(active_scores), 1) if active_scores else 0.0,
            "nodes": sorted(items, key=lambda x: x["score"], reverse=True),
        })
    knowledge_domains.sort(key=lambda x: (x["average_score"], x["evidenced_nodes"]), reverse=True)

    evidence_output = [evidence_out(row, resources.get(row.resource_id), verifiers.get(row.verified_by)) for row in evidence_rows]
    verified_count = sum(1 for row in evidence_rows if row.verification_status == "verified")
    total_nodes = len(all_nodes)
    strong_nodes = sum(1 for item in knowledge_items if item["score"] >= 50)
    covered_nodes = sum(1 for item in knowledge_items if item["score"] >= 20)
    evidence_confidence = round(sum(item["personal_evidence_strength"] for item in evidence_output) / len(evidence_output) * 100, 1) if evidence_output else 0.0

    return {
        "stage": "V4.4 Stage 2",
        "profile": {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "research_direction": user.research_direction,
        },
        "summary": {
            "evidence_count": len(evidence_rows),
            "verified_evidence_count": verified_count,
            "evidence_confidence": evidence_confidence,
            "covered_knowledge_nodes": covered_nodes,
            "strong_knowledge_nodes": strong_nodes,
            "total_knowledge_nodes": total_nodes,
            "knowledge_coverage_percent": round(covered_nodes / total_nodes * 100.0, 1) if total_nodes else 0.0,
            "top_capability_score": capability_items[0]["score"] if capability_items else 0.0,
        },
        "top_strengths": [x for x in capability_items if x["score"] > 0][:5],
        "knowledge": knowledge_items,
        "knowledge_domains": knowledge_domains,
        "capabilities": capability_items,
        "gaps": gaps,
        "evidence": evidence_output,
        "scoring_model": {
            "principle": "不允许学生自报能力分；个人能力由标准映射与证据强度共同推断，并保留证据链。",
            "knowledge": "资源标准覆盖 × 标准证据强度 × 个人证据有效度 × 核验可信度；多条独立证据采用非线性合并。",
            "capability": "72% 直接任务/课程能力证据 + 28% 知识准备度；若缺少直接能力证据，知识准备度最多按 45% 折算。",
            "verification_factors": VERIFICATION_FACTORS,
        },
    }


def seed_demo_research_profiles(db: Session) -> dict[str, int]:
    student = db.scalar(select(User).where(User.username == "student"))
    admin = db.scalar(select(User).where(User.username == "admin"))
    if not student:
        return {"student_evidence": 0}
    resources = {r.code: r for r in db.scalars(select(LearningResource)).all()}
    seeds = [
        {
            "resource_code": "R-COURSE-HEAT", "evidence_type": "course_grade", "title": "《传热学》课程成绩与课程考核",
            "grade_percent": 88, "completion_ratio": 1.0, "quality_rating": 4.2, "verification_status": "verified", "verified_by": admin.id if admin else None,
            "verification_note": "课程成绩单已核验。", "occurred_on": date(2025, 1, 18), "notes": "完成导热、对流与综合换热课程考核。",
        },
        {
            "resource_code": "R-COURSE-NUM", "evidence_type": "course_grade", "title": "《数值分析与工程计算》课程成绩",
            "grade_percent": 91, "completion_ratio": 1.0, "quality_rating": 4.4, "verification_status": "verified", "verified_by": admin.id if admin else None,
            "verification_note": "课程成绩单已核验。", "occurred_on": date(2025, 6, 22), "notes": "完成差分离散与工程数值求解作业。",
        },
        {
            "resource_code": "R-BOOK-MICRO", "evidence_type": "book_reading", "title": "Micro/Nanoscale Heat Transfer 专业书阅读记录",
            "completion_ratio": 0.78, "quality_rating": 4.0, "verification_status": "pending", "occurred_on": date(2026, 3, 12),
            "notes": "已完成微纳尺度传热与声子输运核心章节，并保留读书笔记。", "metadata_json": json.dumps({"notes": True, "exercise_completion": 0.55}, ensure_ascii=False),
        },
        {
            "resource_code": "R-TASK-MICRO", "evidence_type": "project_participation", "title": "微纳热输运数值模拟项目任务",
            "completion_ratio": 1.0, "independence_ratio": 0.82, "quality_rating": 4.5, "mentor_rating": 4.6, "verification_status": "verified", "verified_by": admin.id if admin else None,
            "verification_note": "导师确认学生独立完成主要模型、Python 求解与数据分析。", "occurred_on": date(2026, 6, 30),
            "notes": "承担文献调研、模型建立、Python 求解程序、结果可视化与阶段报告。",
        },
        {
            "resource_code": "R-COURSE-ML", "evidence_type": "course_grade", "title": "《机器学习基础》课程学习记录",
            "grade_percent": 78, "completion_ratio": 1.0, "quality_rating": 3.6, "verification_status": "self_reported", "occurred_on": date(2026, 7, 12),
            "notes": "已完成监督学习、训练验证和基础数据处理内容，成绩待教务核验。",
        },
    ]
    created = 0
    for seed in seeds:
        resource = resources.get(seed.pop("resource_code"))
        if not resource:
            continue
        exists = db.scalar(select(StudentEvidence).where(StudentEvidence.user_id == student.id, StudentEvidence.resource_id == resource.id, StudentEvidence.title == seed["title"]))
        if exists:
            continue
        row = StudentEvidence(user_id=student.id, resource_id=resource.id, **seed)
        db.add(row)
        created += 1
    db.commit()
    return {"student_evidence": created, "student_id": student.id}
