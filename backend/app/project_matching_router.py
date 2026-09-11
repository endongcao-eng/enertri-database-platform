from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .models import Capability, KnowledgeNode, ProjectCapabilityRequirement, ProjectKnowledgeRequirement, ResearchProject, User
from .project_matching_service import build_project_matches, build_team_recommendations, infer_requirement_draft, project_out
from .security import admin_user, current_user

router = APIRouter(prefix="/api/project-matching", tags=["project-matching"])


class CapabilityRequirementPayload(BaseModel):
    capability_id: int
    required_level: float = Field(default=3.0, ge=0, le=5)
    weight: float = Field(default=1.0, gt=0, le=10)
    is_critical: bool = False
    note: str | None = None


class KnowledgeRequirementPayload(BaseModel):
    knowledge_node_id: int
    required_level: float = Field(default=3.0, ge=0, le=5)
    weight: float = Field(default=1.0, gt=0, le=10)
    is_critical: bool = False
    note: str | None = None


class ProjectPayload(BaseModel):
    title: str = Field(min_length=2, max_length=512)
    description: str | None = None
    research_direction: str | None = Field(default=None, max_length=255)
    status: Literal["draft", "active", "archived"] = "draft"
    capability_requirements: list[CapabilityRequirementPayload] = Field(default_factory=list)
    knowledge_requirements: list[KnowledgeRequirementPayload] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class RequirementDraftPayload(BaseModel):
    title: str = Field(min_length=2, max_length=512)
    description: str | None = None


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _replace_requirements(db: Session, project: ResearchProject, caps: list[CapabilityRequirementPayload], nodes: list[KnowledgeRequirementPayload]) -> None:
    db.query(ProjectCapabilityRequirement).filter(ProjectCapabilityRequirement.project_id == project.id).delete(synchronize_session=False)
    db.query(ProjectKnowledgeRequirement).filter(ProjectKnowledgeRequirement.project_id == project.id).delete(synchronize_session=False)
    for req in caps:
        capability = db.get(Capability, req.capability_id)
        if not capability or capability.status != "active":
            raise HTTPException(status_code=400, detail=f"capability {req.capability_id} not found or inactive")
        db.add(ProjectCapabilityRequirement(project_id=project.id, **req.model_dump()))
    for req in nodes:
        node = db.get(KnowledgeNode, req.knowledge_node_id)
        if not node or node.status != "active":
            raise HTTPException(status_code=400, detail=f"knowledge node {req.knowledge_node_id} not found or inactive")
        db.add(ProjectKnowledgeRequirement(project_id=project.id, **req.model_dump()))


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.scalars(select(ResearchProject).order_by(ResearchProject.status.asc(), ResearchProject.updated_at.desc(), ResearchProject.id.desc())).all()
    return [project_out(db, row) for row in rows]


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    project = db.get(ResearchProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project_out(db, project)


@router.post("/draft-requirements")
def draft_requirements(payload: RequirementDraftPayload, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    return infer_requirement_draft(db, payload.title, payload.description)


@router.post("/projects")
def create_project(payload: ProjectPayload, request: Request, db: Session = Depends(get_db), actor: User = Depends(admin_user)):
    project = ResearchProject(
        title=payload.title,
        description=payload.description,
        research_direction=payload.research_direction,
        status=payload.status,
        created_by=actor.id,
        metadata_json=json.dumps(payload.metadata, ensure_ascii=False),
    )
    db.add(project); db.flush()
    _replace_requirements(db, project, payload.capability_requirements, payload.knowledge_requirements)
    db.commit(); db.refresh(project)
    write_audit(db, action="project_matching.project.created", resource_type="research_project", resource_id=project.id, actor=actor, details={"title": project.title, "capability_requirements": len(payload.capability_requirements), "knowledge_requirements": len(payload.knowledge_requirements)}, **_meta(request))
    return project_out(db, project)


@router.put("/projects/{project_id}")
def update_project(project_id: int, payload: ProjectPayload, request: Request, db: Session = Depends(get_db), actor: User = Depends(admin_user)):
    project = db.get(ResearchProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    project.title = payload.title
    project.description = payload.description
    project.research_direction = payload.research_direction
    project.status = payload.status
    project.metadata_json = json.dumps(payload.metadata, ensure_ascii=False)
    _replace_requirements(db, project, payload.capability_requirements, payload.knowledge_requirements)
    db.commit(); db.refresh(project)
    write_audit(db, action="project_matching.project.updated", resource_type="research_project", resource_id=project.id, actor=actor, details={"title": project.title}, **_meta(request))
    return project_out(db, project)


@router.get("/projects/{project_id}/matches")
def project_matches(project_id: int, db: Session = Depends(get_db), _: User = Depends(admin_user)):
    try:
        return build_project_matches(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/teams")
def project_teams(project_id: int, team_size: int = Query(default=3, ge=2, le=4), limit: int = Query(default=5, ge=1, le=10), db: Session = Depends(get_db), _: User = Depends(admin_user)):
    try:
        return build_team_recommendations(db, project_id, team_size=team_size, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
