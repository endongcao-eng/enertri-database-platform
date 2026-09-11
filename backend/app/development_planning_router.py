from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .development_planning_service import analyze_development_goal, goal_out
from .models import DevelopmentGoal, User
from .project_matching_service import infer_requirement_draft
from .security import current_user

router = APIRouter(prefix="/api/development-planning", tags=["development-planning"])
ADMIN_ROLES = {"admin", "system_admin"}


class GoalPayload(BaseModel):
    goal_type: Literal["student_growth", "teacher_research_direction"]
    title: str = Field(min_length=2, max_length=512)
    description: str | None = None
    target_project_id: int | None = None
    user_id: int | None = None


class PreviewPayload(GoalPayload):
    pass


def _meta(request: Request) -> dict[str, str | None]:
    return {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def _target_user(actor: User, requested_user_id: int | None, db: Session) -> User:
    if requested_user_id is None or requested_user_id == actor.id:
        return actor
    if actor.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="只能规划自己的成长目标")
    user = db.get(User, requested_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return user


def _check_goal_access(actor: User, goal: DevelopmentGoal) -> None:
    if actor.id != goal.user_id and actor.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="无权查看其他用户的发展规划")


@router.get("/goals")
def list_goals(user_id: int | None = Query(default=None), db: Session = Depends(get_db), actor: User = Depends(current_user)):
    target = _target_user(actor, user_id, db)
    rows = db.scalars(select(DevelopmentGoal).where(DevelopmentGoal.user_id == target.id, DevelopmentGoal.status == "active").order_by(DevelopmentGoal.updated_at.desc(), DevelopmentGoal.id.desc())).all()
    return [goal_out(row, target) for row in rows]


@router.post("/preview")
def preview_goal(payload: PreviewPayload, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    target = _target_user(actor, payload.user_id, db)
    if payload.goal_type == "teacher_research_direction" and actor.role not in ADMIN_ROLES and target.role not in {"researcher"}:
        raise HTTPException(status_code=403, detail="教师科研方向规划仅研究者/教师或管理员可用")
    try:
        return analyze_development_goal(
            db, target.id, title=payload.title, description=payload.description,
            target_project_id=payload.target_project_id, goal_type=payload.goal_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/goals")
def create_goal(payload: GoalPayload, request: Request, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    target = _target_user(actor, payload.user_id, db)
    if payload.goal_type == "teacher_research_direction" and actor.role not in ADMIN_ROLES and target.role not in {"researcher"}:
        raise HTTPException(status_code=403, detail="教师科研方向规划仅研究者/教师或管理员可用")
    requirements = infer_requirement_draft(db, payload.title, payload.description) if not payload.target_project_id else {}
    row = DevelopmentGoal(
        user_id=target.id, goal_type=payload.goal_type, title=payload.title, description=payload.description,
        target_project_id=payload.target_project_id,
        requirements_json=json.dumps(requirements, ensure_ascii=False) if requirements else None,
        status="active", created_by=actor.id,
    )
    db.add(row); db.commit(); db.refresh(row)
    write_audit(db, action="development.goal.created", resource_type="development_goal", resource_id=row.id, actor=actor, details={"goal_type": row.goal_type, "title": row.title, "user_id": target.id}, **_meta(request))
    return goal_out(row, target)


@router.get("/goals/{goal_id}/analysis")
def analyze_goal(goal_id: int, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    row = db.get(DevelopmentGoal, goal_id)
    if not row:
        raise HTTPException(status_code=404, detail="goal not found")
    _check_goal_access(actor, row)
    try:
        return analyze_development_goal(db, row.user_id, goal=row)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/goals/{goal_id}")
def archive_goal(goal_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    row = db.get(DevelopmentGoal, goal_id)
    if not row:
        raise HTTPException(status_code=404, detail="goal not found")
    _check_goal_access(actor, row)
    row.status = "archived"; db.commit()
    write_audit(db, action="development.goal.archived", resource_type="development_goal", resource_id=row.id, actor=actor, details={"title": row.title}, **_meta(request))
    return {"archived": goal_id}
