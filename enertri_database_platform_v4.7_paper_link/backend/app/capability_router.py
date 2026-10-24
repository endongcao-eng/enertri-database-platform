from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .audit import write_audit
from .capability_standard_service import to_float
from .database import get_db
from .models import (
    Capability,
    CapabilityKnowledgeLink,
    KnowledgeNode,
    KnowledgeRelation,
    LearningResource,
    ResourceCapabilityLink,
    ResourceKnowledgeLink,
    Term,
    User,
)
from .security import admin_user, current_user

router = APIRouter(prefix="/api/capability-standards", tags=["research-capability-standards"])


class KnowledgeNodePayload(BaseModel):
    code: str = Field(min_length=2, max_length=100)
    name_zh: str = Field(min_length=1, max_length=255)
    name_en: str | None = None
    domain: str = "general"
    node_type: Literal["concept", "theory", "method", "tool", "practice"] = "concept"
    description: str | None = None
    linked_term_id: int | None = None
    level_scale: int = Field(default=5, ge=1, le=10)
    status: Literal["active", "draft", "archived"] = "active"


class CapabilityPayload(BaseModel):
    code: str = Field(min_length=2, max_length=100)
    name_zh: str = Field(min_length=1, max_length=255)
    name_en: str | None = None
    category: Literal["theory", "methodology", "computation", "experiment", "research", "communication", "project"]
    description: str | None = None
    level_scale: int = Field(default=5, ge=1, le=10)
    rubric: dict[str, str] = Field(default_factory=dict)
    status: Literal["active", "draft", "archived"] = "active"


class ResourcePayload(BaseModel):
    code: str = Field(min_length=2, max_length=120)
    resource_type: Literal["course", "book", "project_task"]
    title: str = Field(min_length=1, max_length=512)
    subtitle: str | None = None
    discipline: str | None = None
    provider: str | None = None
    description: str | None = None
    metadata: dict = Field(default_factory=dict)
    status: Literal["active", "draft", "archived"] = "active"


class KnowledgeRelationPayload(BaseModel):
    source_node_id: int
    target_node_id: int
    relation_type: Literal["prerequisite", "part_of", "related", "enables"]
    weight: float = Field(default=1.0, ge=0, le=2)
    rationale: str | None = None


class CapabilityKnowledgePayload(BaseModel):
    capability_id: int
    knowledge_node_id: int
    relation_type: Literal["requires", "supports"] = "requires"
    required_level: float = Field(default=1.0, ge=0, le=10)
    weight: float = Field(default=1.0, ge=0, le=2)
    rationale: str | None = None


class ResourceKnowledgePayload(BaseModel):
    resource_id: int
    knowledge_node_id: int
    coverage_level: float = Field(default=1.0, ge=0, le=10)
    weight: float = Field(default=1.0, ge=0, le=2)
    evidence_strength: float = Field(default=0.5, ge=0, le=1)
    note: str | None = None


class ResourceCapabilityPayload(BaseModel):
    resource_id: int
    capability_id: int
    contribution_level: float = Field(default=1.0, ge=0, le=10)
    weight: float = Field(default=1.0, ge=0, le=2)
    evidence_strength: float = Field(default=0.5, ge=0, le=1)
    note: str | None = None


class SimulationPayload(BaseModel):
    resource_ids: list[int] = Field(min_length=1, max_length=50)


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _knowledge_out(row: KnowledgeNode, term: Term | None = None) -> dict:
    return {
        "id": row.id, "code": row.code, "name_zh": row.name_zh, "name_en": row.name_en,
        "domain": row.domain, "node_type": row.node_type, "description": row.description,
        "linked_term_id": row.linked_term_id,
        "linked_term": {"id": term.id, "zh": term.zh, "en": term.en} if term else None,
        "level_scale": row.level_scale, "status": row.status,
    }


def _capability_out(row: Capability) -> dict:
    try: rubric = json.loads(row.rubric_json or "{}")
    except json.JSONDecodeError: rubric = {}
    return {
        "id": row.id, "code": row.code, "name_zh": row.name_zh, "name_en": row.name_en,
        "category": row.category, "description": row.description, "level_scale": row.level_scale,
        "rubric": rubric, "status": row.status,
    }


def _resource_out(db: Session, row: LearningResource, include_links: bool = True) -> dict:
    try: metadata = json.loads(row.metadata_json or "{}")
    except json.JSONDecodeError: metadata = {}
    result = {
        "id": row.id, "code": row.code, "resource_type": row.resource_type, "title": row.title,
        "subtitle": row.subtitle, "discipline": row.discipline, "provider": row.provider,
        "description": row.description, "metadata": metadata, "status": row.status,
    }
    if include_links:
        knowledge_links = db.execute(
            select(ResourceKnowledgeLink, KnowledgeNode)
            .join(KnowledgeNode, KnowledgeNode.id == ResourceKnowledgeLink.knowledge_node_id)
            .where(ResourceKnowledgeLink.resource_id == row.id)
            .order_by(ResourceKnowledgeLink.coverage_level.desc())
        ).all()
        capability_links = db.execute(
            select(ResourceCapabilityLink, Capability)
            .join(Capability, Capability.id == ResourceCapabilityLink.capability_id)
            .where(ResourceCapabilityLink.resource_id == row.id)
            .order_by(ResourceCapabilityLink.contribution_level.desc())
        ).all()
        result["knowledge_links"] = [{
            "knowledge_node_id": node.id, "code": node.code, "name_zh": node.name_zh,
            "coverage_level": to_float(link.coverage_level), "weight": to_float(link.weight),
            "evidence_strength": to_float(link.evidence_strength), "note": link.note,
        } for link, node in knowledge_links]
        result["capability_links"] = [{
            "capability_id": cap.id, "code": cap.code, "name_zh": cap.name_zh, "category": cap.category,
            "contribution_level": to_float(link.contribution_level), "weight": to_float(link.weight),
            "evidence_strength": to_float(link.evidence_strength), "note": link.note,
        } for link, cap in capability_links]
    return result


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(current_user)):
    node_count = db.scalar(select(func.count(KnowledgeNode.id))) or 0
    cap_count = db.scalar(select(func.count(Capability.id))) or 0
    resource_count = db.scalar(select(func.count(LearningResource.id))) or 0
    link_count = (
        (db.scalar(select(func.count(ResourceKnowledgeLink.id))) or 0)
        + (db.scalar(select(func.count(ResourceCapabilityLink.id))) or 0)
        + (db.scalar(select(func.count(CapabilityKnowledgeLink.id))) or 0)
        + (db.scalar(select(func.count(KnowledgeRelation.id))) or 0)
    )
    linked_terms = db.scalar(select(func.count(KnowledgeNode.id)).where(KnowledgeNode.linked_term_id.is_not(None))) or 0
    type_rows = db.execute(select(LearningResource.resource_type, func.count(LearningResource.id)).group_by(LearningResource.resource_type)).all()
    domain_rows = db.execute(select(KnowledgeNode.domain, func.count(KnowledgeNode.id)).group_by(KnowledgeNode.domain).order_by(func.count(KnowledgeNode.id).desc())).all()
    return {
        "stage": "V4.3 Stage 1",
        "name": "科研知识与能力标准库",
        "knowledge_nodes": node_count,
        "capabilities": cap_count,
        "resources": resource_count,
        "mapping_links": link_count,
        "linked_terms": linked_terms,
        "resource_types": {name: count for name, count in type_rows},
        "domains": [{"name": name, "count": count} for name, count in domain_rows],
        "pipeline": ["课程 / 专业书 / 项目任务", "标准知识点", "科研能力", "后续个人证据画像与匹配"],
    }


@router.get("/knowledge-nodes")
def list_knowledge_nodes(
    q: str | None = None,
    domain: str | None = None,
    status: str = "active",
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = select(KnowledgeNode).order_by(KnowledgeNode.domain, KnowledgeNode.id)
    if status != "all": stmt = stmt.where(KnowledgeNode.status == status)
    if domain: stmt = stmt.where(KnowledgeNode.domain == domain)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(KnowledgeNode.name_zh.like(like), KnowledgeNode.name_en.like(like), KnowledgeNode.code.like(like), KnowledgeNode.description.like(like)))
    rows = db.scalars(stmt).all()
    term_ids = {row.linked_term_id for row in rows if row.linked_term_id}
    terms = {t.id: t for t in db.scalars(select(Term).where(Term.id.in_(term_ids))).all()} if term_ids else {}
    return [_knowledge_out(row, terms.get(row.linked_term_id)) for row in rows]


@router.get("/capabilities")
def list_capabilities(category: str | None = None, status: str = "active", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Capability).order_by(Capability.category, Capability.id)
    if status != "all": stmt = stmt.where(Capability.status == status)
    if category: stmt = stmt.where(Capability.category == category)
    return [_capability_out(row) for row in db.scalars(stmt).all()]


@router.get("/resources")
def list_resources(resource_type: str | None = None, status: str = "active", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(LearningResource).order_by(LearningResource.resource_type, LearningResource.id)
    if status != "all": stmt = stmt.where(LearningResource.status == status)
    if resource_type: stmt = stmt.where(LearningResource.resource_type == resource_type)
    return [_resource_out(db, row) for row in db.scalars(stmt).all()]


@router.get("/resources/{resource_id}")
def resource_detail(resource_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    row = db.get(LearningResource, resource_id)
    if not row: raise HTTPException(status_code=404, detail="resource not found")
    return _resource_out(db, row)


@router.get("/graph")
def standards_graph(db: Session = Depends(get_db), _: User = Depends(current_user)):
    nodes = db.scalars(select(KnowledgeNode).where(KnowledgeNode.status == "active").order_by(KnowledgeNode.id)).all()
    caps = db.scalars(select(Capability).where(Capability.status == "active").order_by(Capability.id)).all()
    relations = db.scalars(select(KnowledgeRelation).order_by(KnowledgeRelation.id)).all()
    cap_links = db.scalars(select(CapabilityKnowledgeLink).order_by(CapabilityKnowledgeLink.id)).all()
    return {
        "knowledge_nodes": [_knowledge_out(row) for row in nodes],
        "capabilities": [_capability_out(row) for row in caps],
        "knowledge_relations": [{
            "id": row.id, "source_node_id": row.source_node_id, "target_node_id": row.target_node_id,
            "relation_type": row.relation_type, "weight": to_float(row.weight), "rationale": row.rationale,
        } for row in relations],
        "capability_knowledge_links": [{
            "id": row.id, "capability_id": row.capability_id, "knowledge_node_id": row.knowledge_node_id,
            "relation_type": row.relation_type, "required_level": to_float(row.required_level),
            "weight": to_float(row.weight), "rationale": row.rationale,
        } for row in cap_links],
    }


def _combined_score(contributions: list[float]) -> float:
    # Independent-evidence combination. More evidence increases confidence without simple score inflation.
    remaining = 1.0
    for contribution in contributions:
        remaining *= 1.0 - max(0.0, min(0.98, contribution))
    return round((1.0 - remaining) * 100, 1)


@router.post("/simulate")
def simulate_mapping(payload: SimulationPayload, db: Session = Depends(get_db), _: User = Depends(current_user)):
    resources = db.scalars(select(LearningResource).where(LearningResource.id.in_(payload.resource_ids))).all()
    if not resources: raise HTTPException(status_code=404, detail="没有找到可演算的课程/书籍/项目任务")
    resource_ids = [row.id for row in resources]
    resource_map = {row.id: row for row in resources}

    knowledge_rows = db.execute(
        select(ResourceKnowledgeLink, KnowledgeNode)
        .join(KnowledgeNode, KnowledgeNode.id == ResourceKnowledgeLink.knowledge_node_id)
        .where(ResourceKnowledgeLink.resource_id.in_(resource_ids))
    ).all()
    capability_rows = db.execute(
        select(ResourceCapabilityLink, Capability)
        .join(Capability, Capability.id == ResourceCapabilityLink.capability_id)
        .where(ResourceCapabilityLink.resource_id.in_(resource_ids))
    ).all()

    knowledge_contrib: dict[int, list[float]] = defaultdict(list)
    knowledge_trace: dict[int, list[dict]] = defaultdict(list)
    knowledge_obj: dict[int, KnowledgeNode] = {}
    for link, node in knowledge_rows:
        normalized = min(1.0, to_float(link.coverage_level) / max(1, node.level_scale))
        contribution = normalized * min(1.0, to_float(link.weight)) * min(1.0, to_float(link.evidence_strength))
        knowledge_contrib[node.id].append(contribution)
        knowledge_obj[node.id] = node
        res = resource_map[link.resource_id]
        knowledge_trace[node.id].append({
            "resource_id": res.id, "resource_type": res.resource_type, "title": res.title,
            "coverage_level": to_float(link.coverage_level), "evidence_strength": to_float(link.evidence_strength),
            "mapping_contribution": round(contribution * 100, 1),
        })

    cap_contrib: dict[int, list[float]] = defaultdict(list)
    cap_trace: dict[int, list[dict]] = defaultdict(list)
    cap_obj: dict[int, Capability] = {}
    for link, cap in capability_rows:
        normalized = min(1.0, to_float(link.contribution_level) / max(1, cap.level_scale))
        contribution = normalized * min(1.0, to_float(link.weight)) * min(1.0, to_float(link.evidence_strength))
        cap_contrib[cap.id].append(contribution)
        cap_obj[cap.id] = cap
        res = resource_map[link.resource_id]
        cap_trace[cap.id].append({
            "resource_id": res.id, "resource_type": res.resource_type, "title": res.title,
            "contribution_level": to_float(link.contribution_level), "evidence_strength": to_float(link.evidence_strength),
            "mapping_contribution": round(contribution * 100, 1),
        })

    knowledge = [{
        "knowledge_node_id": node_id, "code": knowledge_obj[node_id].code,
        "name_zh": knowledge_obj[node_id].name_zh, "domain": knowledge_obj[node_id].domain,
        "mapping_score": _combined_score(values), "trace": sorted(knowledge_trace[node_id], key=lambda x: x["mapping_contribution"], reverse=True),
    } for node_id, values in knowledge_contrib.items()]
    capabilities = [{
        "capability_id": cap_id, "code": cap_obj[cap_id].code,
        "name_zh": cap_obj[cap_id].name_zh, "category": cap_obj[cap_id].category,
        "mapping_score": _combined_score(values), "trace": sorted(cap_trace[cap_id], key=lambda x: x["mapping_contribution"], reverse=True),
    } for cap_id, values in cap_contrib.items()]
    knowledge.sort(key=lambda x: x["mapping_score"], reverse=True)
    capabilities.sort(key=lambda x: x["mapping_score"], reverse=True)
    type_count = Counter(row.resource_type for row in resources)
    return {
        "resource_ids": resource_ids,
        "resources": [{"id": row.id, "type": row.resource_type, "title": row.title} for row in resources],
        "resource_type_count": dict(type_count),
        "knowledge": knowledge,
        "capabilities": capabilities,
        "note": "这里的分数是标准映射强度，不是学生能力分。第二阶段会叠加成绩、项目独立度、导师评价等个人证据。",
    }


@router.post("/knowledge-nodes")
def create_knowledge_node(payload: KnowledgeNodePayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if db.scalar(select(KnowledgeNode).where(KnowledgeNode.code == payload.code)):
        raise HTTPException(status_code=409, detail="知识点 code 已存在")
    if payload.linked_term_id and not db.get(Term, payload.linked_term_id):
        raise HTTPException(status_code=404, detail="linked term not found")
    row = KnowledgeNode(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    write_audit(db, action="capability_standard.knowledge_node.created", resource_type="knowledge_node", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return _knowledge_out(row, db.get(Term, row.linked_term_id) if row.linked_term_id else None)


@router.post("/capabilities")
def create_capability(payload: CapabilityPayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if db.scalar(select(Capability).where(Capability.code == payload.code)):
        raise HTTPException(status_code=409, detail="能力 code 已存在")
    data = payload.model_dump(exclude={"rubric"})
    row = Capability(**data, rubric_json=json.dumps(payload.rubric, ensure_ascii=False))
    db.add(row); db.commit(); db.refresh(row)
    write_audit(db, action="capability_standard.capability.created", resource_type="capability", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return _capability_out(row)


@router.post("/resources")
def create_resource(payload: ResourcePayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if db.scalar(select(LearningResource).where(LearningResource.code == payload.code)):
        raise HTTPException(status_code=409, detail="资源 code 已存在")
    data = payload.model_dump(exclude={"metadata"})
    row = LearningResource(**data, metadata_json=json.dumps(payload.metadata, ensure_ascii=False))
    db.add(row); db.commit(); db.refresh(row)
    write_audit(db, action="capability_standard.resource.created", resource_type="learning_resource", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return _resource_out(db, row)


@router.post("/knowledge-relations")
def create_knowledge_relation(payload: KnowledgeRelationPayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if payload.source_node_id == payload.target_node_id: raise HTTPException(status_code=400, detail="知识点不能与自身建立关系")
    if not db.get(KnowledgeNode, payload.source_node_id) or not db.get(KnowledgeNode, payload.target_node_id): raise HTTPException(status_code=404, detail="knowledge node not found")
    exists = db.scalar(select(KnowledgeRelation).where(KnowledgeRelation.source_node_id == payload.source_node_id, KnowledgeRelation.target_node_id == payload.target_node_id, KnowledgeRelation.relation_type == payload.relation_type))
    if exists: raise HTTPException(status_code=409, detail="关系已存在")
    row = KnowledgeRelation(**payload.model_dump()); db.add(row); db.commit(); db.refresh(row)
    write_audit(db, action="capability_standard.knowledge_relation.created", resource_type="knowledge_relation", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return {"id": row.id, **payload.model_dump()}


@router.post("/capability-knowledge-links")
def create_capability_knowledge_link(payload: CapabilityKnowledgePayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if not db.get(Capability, payload.capability_id) or not db.get(KnowledgeNode, payload.knowledge_node_id): raise HTTPException(status_code=404, detail="capability or knowledge node not found")
    row = CapabilityKnowledgeLink(**payload.model_dump()); db.add(row)
    try: db.commit()
    except Exception: db.rollback(); raise HTTPException(status_code=409, detail="映射已存在")
    db.refresh(row)
    write_audit(db, action="capability_standard.capability_knowledge.created", resource_type="capability_knowledge_link", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return {"id": row.id, **payload.model_dump()}


@router.post("/resource-knowledge-links")
def create_resource_knowledge_link(payload: ResourceKnowledgePayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if not db.get(LearningResource, payload.resource_id) or not db.get(KnowledgeNode, payload.knowledge_node_id): raise HTTPException(status_code=404, detail="resource or knowledge node not found")
    row = ResourceKnowledgeLink(**payload.model_dump()); db.add(row)
    try: db.commit()
    except Exception: db.rollback(); raise HTTPException(status_code=409, detail="映射已存在")
    db.refresh(row)
    write_audit(db, action="capability_standard.resource_knowledge.created", resource_type="resource_knowledge_link", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return {"id": row.id, **payload.model_dump()}


@router.post("/resource-capability-links")
def create_resource_capability_link(payload: ResourceCapabilityPayload, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if not db.get(LearningResource, payload.resource_id) or not db.get(Capability, payload.capability_id): raise HTTPException(status_code=404, detail="resource or capability not found")
    row = ResourceCapabilityLink(**payload.model_dump()); db.add(row)
    try: db.commit()
    except Exception: db.rollback(); raise HTTPException(status_code=409, detail="映射已存在")
    db.refresh(row)
    write_audit(db, action="capability_standard.resource_capability.created", resource_type="resource_capability_link", resource_id=row.id, actor=user, details=payload.model_dump(), **_meta(request))
    return {"id": row.id, **payload.model_dump()}
