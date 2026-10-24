from __future__ import annotations

import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .models import LearningResource, StudentEvidence, User
from .research_profile_service import build_profile, evidence_out
from .security import admin_user, current_user

router = APIRouter(prefix="/api/research-profile", tags=["research-profile"])
ADMIN_ROLES = {"admin", "system_admin"}


class EvidencePayload(BaseModel):
    user_id: int | None = None
    resource_id: int
    evidence_type: Literal["course_grade", "book_reading", "project_participation"]
    title: str | None = Field(default=None, max_length=512)
    grade_percent: float | None = Field(default=None, ge=0, le=100)
    completion_ratio: float = Field(default=1.0, ge=0, le=1)
    independence_ratio: float | None = Field(default=None, ge=0, le=1)
    quality_rating: float | None = Field(default=None, ge=0, le=5)
    mentor_rating: float | None = Field(default=None, ge=0, le=5)
    verification_status: Literal["self_reported", "pending"] = "self_reported"
    occurred_on: date | None = None
    notes: str | None = None
    metadata: dict = Field(default_factory=dict)


class VerificationPayload(BaseModel):
    verification_status: Literal["pending", "verified", "rejected"]
    mentor_rating: float | None = Field(default=None, ge=0, le=5)
    quality_rating: float | None = Field(default=None, ge=0, le=5)
    verification_note: str | None = None


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _target_user(db: Session, actor: User, requested_user_id: int | None) -> User:
    target_id = requested_user_id or actor.id
    if target_id != actor.id and actor.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="只能查看自己的科研画像")
    target = db.get(User, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    return target


def _validate_resource_type(resource: LearningResource, evidence_type: str) -> None:
    expected = {"course_grade": "course", "book_reading": "book", "project_participation": "project_task"}[evidence_type]
    if resource.resource_type != expected:
        raise HTTPException(status_code=400, detail=f"{evidence_type} 必须绑定 {expected} 类型标准资源")


@router.get("/users")
def list_profile_users(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    rows = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name, User.id)).all()
    return [{"id": row.id, "username": row.username, "display_name": row.display_name, "role": row.role, "research_direction": row.research_direction} for row in rows]


@router.get("/profile")
def get_profile(user_id: int | None = None, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    target = _target_user(db, actor, user_id)
    try:
        return build_profile(db, target.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evidence")
def list_evidence(user_id: int | None = None, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    target = _target_user(db, actor, user_id)
    rows = db.scalars(select(StudentEvidence).where(StudentEvidence.user_id == target.id).order_by(StudentEvidence.id.desc())).all()
    resources = {row.id: row for row in db.scalars(select(LearningResource).where(LearningResource.id.in_({e.resource_id for e in rows}))).all()} if rows else {}
    verifier_ids = {e.verified_by for e in rows if e.verified_by}
    verifiers = {row.id: row for row in db.scalars(select(User).where(User.id.in_(verifier_ids))).all()} if verifier_ids else {}
    return [evidence_out(row, resources.get(row.resource_id), verifiers.get(row.verified_by)) for row in rows]


@router.post("/evidence")
def create_evidence(payload: EvidencePayload, request: Request, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    target = _target_user(db, actor, payload.user_id)
    resource = db.get(LearningResource, payload.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="learning resource not found")
    _validate_resource_type(resource, payload.evidence_type)
    data = payload.model_dump(exclude={"user_id", "resource_id", "metadata"})
    # Mentor scores are authoritative teacher evidence. Students may submit a project, but cannot self-award a mentor score.
    if actor.role not in ADMIN_ROLES:
        data["mentor_rating"] = None
    title = data.pop("title") or f"{resource.title} · 个人证据"
    row = StudentEvidence(
        user_id=target.id,
        resource_id=resource.id,
        title=title,
        metadata_json=json.dumps(payload.metadata, ensure_ascii=False),
        **data,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(db, action="research_profile.evidence.created", resource_type="student_evidence", resource_id=row.id, actor=actor, details={"target_user_id": target.id, "resource_id": resource.id, "evidence_type": row.evidence_type}, **_meta(request))
    return evidence_out(row, resource)


@router.patch("/evidence/{evidence_id}/verify")
def verify_evidence(evidence_id: int, payload: VerificationPayload, request: Request, db: Session = Depends(get_db), actor: User = Depends(admin_user)):
    row = db.get(StudentEvidence, evidence_id)
    if not row:
        raise HTTPException(status_code=404, detail="evidence not found")
    row.verification_status = payload.verification_status
    row.verified_by = actor.id if payload.verification_status in {"verified", "rejected"} else None
    row.verification_note = payload.verification_note
    if payload.mentor_rating is not None:
        row.mentor_rating = payload.mentor_rating
    if payload.quality_rating is not None:
        row.quality_rating = payload.quality_rating
    db.commit()
    db.refresh(row)
    resource = db.get(LearningResource, row.resource_id)
    write_audit(db, action="research_profile.evidence.verified", resource_type="student_evidence", resource_id=row.id, actor=actor, details=payload.model_dump(), **_meta(request))
    return evidence_out(row, resource, actor if row.verified_by else None)
