from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .development_planning_service import analyze_development_goal
from .models import (
    DevelopmentGoal,
    DevelopmentPlanItem,
    DevelopmentSnapshot,
    LearningResource,
    ResourceKnowledgeLink,
    ResourceCapabilityLink,
    KnowledgeNode,
    Capability,
    Publication,
    ResearchProject,
    StudentEvidence,
    User,
)


def _f(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _loads(value):
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def plan_item_out(row: DevelopmentPlanItem) -> dict:
    return {
        "id": row.id,
        "goal_id": row.goal_id,
        "user_id": row.user_id,
        "item_type": row.item_type,
        "source_resource_id": row.source_resource_id,
        "source_publication_id": row.source_publication_id,
        "source_project_id": row.source_project_id,
        "title": row.title,
        "phase": row.phase,
        "priority_score": round(_f(row.priority_score), 1),
        "status": row.status,
        "progress_percent": row.progress_percent,
        "rationale": row.rationale,
        "gap_targets": _loads(row.gap_targets_json).get("targets", []),
        "completion_note": row.completion_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def snapshot_out(row: DevelopmentSnapshot) -> dict:
    return {
        "id": row.id,
        "goal_id": row.goal_id,
        "snapshot_type": row.snapshot_type,
        "match_score": round(_f(row.match_score), 1),
        "capability_fit": round(_f(row.capability_fit), 1),
        "knowledge_fit": round(_f(row.knowledge_fit), 1),
        "evidence_confidence": round(_f(row.evidence_confidence), 1),
        "critical_gap_count": row.critical_gap_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _target_tokens(analysis: dict) -> list[str]:
    tokens = []
    for value in [analysis.get("goal", {}).get("title"), analysis.get("goal", {}).get("description")]:
        if value:
            tokens.extend(str(value).replace("+", " ").replace("/", " ").split())
    for row in analysis.get("knowledge_gaps", [])[:6]:
        tokens.extend([row.get("name_zh"), row.get("code")])
    for row in analysis.get("capability_gaps", [])[:5]:
        tokens.extend([row.get("name_zh"), row.get("code")])
    return [str(x).lower() for x in tokens if x and len(str(x)) >= 2]


def _text_relevance(text: str, tokens: list[str]) -> float:
    hay = (text or "").lower()
    if not hay or not tokens:
        return 0.0
    hits = sum(1 for token in set(tokens) if token in hay)
    return min(100.0, hits / max(3, min(10, len(set(tokens)))) * 100.0)


def integrated_recommendations(db: Session, goal: DevelopmentGoal) -> dict:
    analysis = analyze_development_goal(db, goal.user_id, goal=goal)
    tokens = _target_tokens(analysis)
    out = []

    standard_rows = []
    seen_resources = set()
    for pool in (analysis.get("course_recommendations", []), analysis.get("book_recommendations", []), analysis.get("practice_recommendations", []), analysis.get("recommendations", [])):
        for row in pool:
            if row["resource_id"] in seen_resources:
                continue
            seen_resources.add(row["resource_id"]); standard_rows.append(row)
    for row in standard_rows:
        out.append({
            "kind": row["resource_type"],
            "source_resource_id": row["resource_id"],
            "source_publication_id": None,
            "source_project_id": None,
            "title": row["title"],
            "phase": row["phase"],
            "priority_score": row["priority_score"],
            "rationale": row.get("why") or row.get("description") or "由当前关键知识/能力缺口推导。",
            "gap_targets": row.get("gap_closure", []),
        })

    pubs = db.scalars(select(Publication).order_by(Publication.year.desc().nullslast(), Publication.id.desc())).all()
    pub_rows = []
    for pub in pubs:
        score = _text_relevance(" ".join([pub.title or "", pub.abstract or "", pub.keywords_json or ""]), tokens)
        if score <= 0:
            continue
        meta = _loads(pub.metadata_json)
        pub_rows.append({
            "kind": "publication", "source_resource_id": None, "source_publication_id": pub.id, "source_project_id": None,
            "title": pub.title, "phase": "文献桥接", "priority_score": round(48 + 0.45 * score, 1),
            "rationale": "命中当前目标方向与知识缺口关键词；用于在进入课程/项目之前建立研究路线与方法认知。" + ("（内部演示文献记录）" if meta.get("demo_stage5") else ""),
            "gap_targets": [{"type": "literature", "name_zh": "目标方向文献认知", "potential_gap_closure": round(score, 1)}],
        })
    out.extend(sorted(pub_rows, key=lambda x: x["priority_score"], reverse=True)[:4])

    projects = db.scalars(select(ResearchProject).where(ResearchProject.status == "active").order_by(ResearchProject.id)).all()
    project_rows = []
    for project in projects:
        score = _text_relevance(" ".join([project.title or "", project.description or "", project.research_direction or ""]), tokens)
        if score <= 0:
            continue
        project_rows.append({
            "kind": "research_project", "source_resource_id": None, "source_publication_id": None, "source_project_id": project.id,
            "title": project.title, "phase": "科研转化", "priority_score": round(55 + 0.4 * score, 1),
            "rationale": "项目方向与当前成长目标和关键缺口重合，可作为把知识转成科研证据的真实载体。",
            "gap_targets": [{"type": "project", "name_zh": project.research_direction or "科研项目", "potential_gap_closure": round(score, 1)}],
        })
    out.extend(sorted(project_rows, key=lambda x: x["priority_score"], reverse=True)[:3])
    out.sort(key=lambda x: x["priority_score"], reverse=True)
    return {"analysis": analysis, "recommendations": out[:14]}


def _snapshot(db: Session, goal: DevelopmentGoal, snapshot_type: str) -> DevelopmentSnapshot:
    analysis = analyze_development_goal(db, goal.user_id, goal=goal)
    fit = analysis["target_fit"]
    row = DevelopmentSnapshot(
        goal_id=goal.id, user_id=goal.user_id, snapshot_type=snapshot_type,
        match_score=fit.get("match_score", 0), capability_fit=fit.get("capability_fit", 0),
        knowledge_fit=fit.get("knowledge_fit", 0), evidence_confidence=fit.get("evidence_confidence", 0),
        critical_gap_count=fit.get("critical_gap_count", 0),
        snapshot_json=json.dumps({"profile_summary": analysis.get("profile_summary"), "top_capability_gaps": analysis.get("capability_gaps", [])[:5], "top_knowledge_gaps": analysis.get("knowledge_gaps", [])[:5]}, ensure_ascii=False),
    )
    db.add(row); db.flush()
    return row


def generate_roadmap(db: Session, goal: DevelopmentGoal, created_by: int) -> dict:
    bundle = integrated_recommendations(db, goal)
    if not db.scalar(select(DevelopmentSnapshot).where(DevelopmentSnapshot.goal_id == goal.id)):
        _snapshot(db, goal, "baseline")

    existing = db.scalars(select(DevelopmentPlanItem).where(DevelopmentPlanItem.goal_id == goal.id)).all()
    keys = {(r.item_type, r.source_resource_id, r.source_publication_id, r.source_project_id) for r in existing}
    chosen = []
    limits = {"course": 3, "book": 2, "project_task": 2, "publication": 2, "research_project": 2}
    counts = {k: 0 for k in limits}
    for rec in bundle["recommendations"]:
        kind = rec["kind"]
        if kind not in limits or counts[kind] >= limits[kind]:
            continue
        key = (kind, rec.get("source_resource_id"), rec.get("source_publication_id"), rec.get("source_project_id"))
        if key in keys:
            continue
        row = DevelopmentPlanItem(
            goal_id=goal.id, user_id=goal.user_id, item_type=kind,
            source_resource_id=rec.get("source_resource_id"), source_publication_id=rec.get("source_publication_id"), source_project_id=rec.get("source_project_id"),
            title=rec["title"], phase=rec.get("phase") or "planned", priority_score=rec.get("priority_score") or 0,
            status="planned", progress_percent=0, rationale=rec.get("rationale"),
            gap_targets_json=json.dumps({"targets": rec.get("gap_targets", [])}, ensure_ascii=False), created_by=created_by,
        )
        db.add(row); db.flush(); keys.add(key); counts[kind] += 1; chosen.append(row)
    db.commit()
    return roadmap_out(db, goal)


def roadmap_out(db: Session, goal: DevelopmentGoal) -> dict:
    items = db.scalars(select(DevelopmentPlanItem).where(DevelopmentPlanItem.goal_id == goal.id).order_by(DevelopmentPlanItem.status, DevelopmentPlanItem.priority_score.desc(), DevelopmentPlanItem.id)).all()
    snapshots = db.scalars(select(DevelopmentSnapshot).where(DevelopmentSnapshot.goal_id == goal.id).order_by(DevelopmentSnapshot.id)).all()
    analysis = analyze_development_goal(db, goal.user_id, goal=goal)
    completed = [x for x in items if x.status == "completed"]
    in_progress = [x for x in items if x.status == "in_progress"]
    baseline = snapshots[0] if snapshots else None
    current = snapshots[-1] if snapshots else None
    return {
        "stage": "V4.7 Stage 5",
        "goal": {"id": goal.id, "user_id": goal.user_id, "goal_type": goal.goal_type, "title": goal.title, "description": goal.description},
        "current_fit": analysis["target_fit"],
        "items": [plan_item_out(x) for x in items],
        "summary": {
            "total": len(items), "completed": len(completed), "in_progress": len(in_progress),
            "progress_percent": round(sum(x.progress_percent for x in items) / max(1, len(items)), 1),
            "baseline_match_score": round(_f(baseline.match_score), 1) if baseline else analysis["target_fit"]["match_score"],
            "latest_snapshot_score": round(_f(current.match_score), 1) if current else analysis["target_fit"]["match_score"],
            "pending_evidence_count": db.scalar(select(StudentEvidence).where(StudentEvidence.user_id == goal.user_id, StudentEvidence.verification_status == "pending").count()) if False else len(db.scalars(select(StudentEvidence).where(StudentEvidence.user_id == goal.user_id, StudentEvidence.verification_status == "pending")).all()),
        },
        "snapshots": [snapshot_out(x) for x in snapshots],
        "closed_loop": "路线图完成项不会直接写能力分；完成后生成低可信的待核验证据，可形成临时画像变化；教师核验后才升级为高可信证据，并重新计算目标匹配。",
    }


def update_plan_item(db: Session, row: DevelopmentPlanItem, *, status: str | None = None, progress_percent: int | None = None, completion_note: str | None = None) -> tuple[dict, int | None]:
    if status is not None:
        row.status = status
    if progress_percent is not None:
        row.progress_percent = max(0, min(100, int(progress_percent)))
        if row.progress_percent > 0 and row.status == "planned": row.status = "in_progress"
    if row.status == "completed": row.progress_percent = 100
    if completion_note is not None:
        row.completion_note = completion_note
    evidence_id = None
    if row.status == "completed" and row.source_resource_id:
        existing = None
        for ev in db.scalars(select(StudentEvidence).where(StudentEvidence.user_id == row.user_id, StudentEvidence.resource_id == row.source_resource_id)).all():
            if _loads(ev.metadata_json).get("development_plan_item_id") == row.id:
                existing = ev; break
        if not existing:
            resource = db.get(LearningResource, row.source_resource_id)
            if resource:
                evidence_type = {"course": "course_grade", "book": "book_reading", "project_task": "project_participation"}.get(resource.resource_type)
                if evidence_type:
                    ev = StudentEvidence(
                        user_id=row.user_id, resource_id=resource.id, evidence_type=evidence_type,
                        title=f"成长路线完成：{resource.title}", completion_ratio=1.0,
                        independence_ratio=0.8 if resource.resource_type == "project_task" else None,
                        verification_status="pending", occurred_on=date.today(),
                        notes="由 V4.7 动态成长路线完成动作自动生成；需教师核验后成为高可信能力证据。",
                        metadata_json=json.dumps({"development_plan_item_id": row.id, "source": "v4.7_dynamic_roadmap"}, ensure_ascii=False),
                    )
                    db.add(ev); db.flush(); evidence_id = ev.id
    goal = db.get(DevelopmentGoal, row.goal_id)
    if row.status == "completed" and goal:
        _snapshot(db, goal, "completion")
    db.commit(); db.refresh(row)
    return plan_item_out(row), evidence_id


def seed_demo_closed_loop(db: Session) -> dict:
    # V4.7 adds one book resource so student roadmaps can demonstrate a complete
    # course -> book -> literature -> project/practice sequence for chip thermal management.
    book_created = 0
    chip_book = db.scalar(select(LearningResource).where(LearningResource.code == "R-BOOK-CHIP"))
    if not chip_book:
        chip_book = LearningResource(
            code="R-BOOK-CHIP", resource_type="book", title="电子设备热管理基础与工程方法",
            subtitle="芯片与封装热设计专业书路线", discipline="电子热科学", provider="专业书",
            description="系统梳理芯片热点、封装热阻、界面热传导、材料热物性与工程热设计方法。", status="active",
            metadata_json=json.dumps({"demo_stage5": True}, ensure_ascii=False),
        )
        db.add(chip_book); db.flush(); book_created = 1
        nodes = {x.code: x for x in db.scalars(select(KnowledgeNode)).all()}
        caps = {x.code: x for x in db.scalars(select(Capability)).all()}
        for code, level, weight, strength in [("K-CHIP-THERM",4.2,1.0,0.52),("K-MAT-THERMO",3.2,0.7,0.46),("K-HEAT-CONDUCTION",3.5,0.7,0.48)]:
            node = nodes.get(code)
            if node: db.add(ResourceKnowledgeLink(resource_id=chip_book.id, knowledge_node_id=node.id, coverage_level=level, weight=weight, evidence_strength=strength, note="V4.7 芯片热管理专业书标准映射"))
        cap = caps.get("C-HEAT-THEORY")
        if cap: db.add(ResourceCapabilityLink(resource_id=chip_book.id, capability_id=cap.id, contribution_level=3.2, weight=0.7, evidence_strength=0.46, note="V4.7 专业书用于系统深化，不等同科研实践证据"))
        db.flush()

    demo_pubs = [
        ("stage5-demo-gnn-review", "内部演示文献：图神经网络与材料性质预测方法综述", "图神经网络 GNN 深度学习 材料热物性 机器学习", 2026),
        ("stage5-demo-micro-ml", "内部演示文献：微纳尺度热输运的数据驱动建模路线", "微纳尺度传热 声子输运 Python 机器学习 热物性", 2026),
        ("stage5-demo-chip", "内部演示文献：芯片热管理多物理场建模知识框架", "芯片热管理 传热 数值模拟 材料热物性", 2026),
    ]
    pub_created = 0
    for doi, title, keywords, year in demo_pubs:
        if db.scalar(select(Publication).where(Publication.doi == doi)):
            continue
        db.add(Publication(doi=doi, title=title, normalized_title=title.lower(), abstract=keywords, keywords_json=json.dumps(keywords.split(), ensure_ascii=False), year=year, primary_source="demo_catalog", metadata_json=json.dumps({"demo_stage5": True}, ensure_ascii=False)))
        pub_created += 1

    admin = db.scalar(select(User).where(User.username == "admin"))
    project_created = 0
    seeds = [
        ("芯片热管理多物理场建模实践", "芯片热管理、微纳传热、材料热物性与数值模拟综合实践", "芯片热管理"),
        ("GNN 微纳材料热输运验证项目", "将图神经网络、深度学习与材料热物性和微纳尺度传热结合", "AI + 微纳热输运"),
    ]
    for title, desc, direction in seeds:
        if db.scalar(select(ResearchProject).where(ResearchProject.title == title)):
            continue
        db.add(ResearchProject(title=title, description=desc, research_direction=direction, status="active", created_by=admin.id if admin else None, metadata_json=json.dumps({"demo_stage5": True}, ensure_ascii=False)))
        project_created += 1
    db.commit()

    generated = 0
    for goal in db.scalars(select(DevelopmentGoal).where(DevelopmentGoal.status == "active").order_by(DevelopmentGoal.id)).all():
        if not db.scalar(select(DevelopmentPlanItem).where(DevelopmentPlanItem.goal_id == goal.id)):
            generate_roadmap(db, goal, admin.id if admin else goal.user_id)
            generated += 1
    return {"demo_book_resources": book_created, "demo_publications": pub_created, "demo_projects": project_created, "roadmaps_generated": generated}
