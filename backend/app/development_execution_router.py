from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .audit import write_audit
from .database import get_db
from .development_execution_service import generate_roadmap, integrated_recommendations, roadmap_out, update_plan_item
from .models import DevelopmentGoal, DevelopmentPlanItem, User
from .security import current_user

router = APIRouter(prefix="/api/development-execution", tags=["development-execution"])
ADMIN_ROLES = {"admin", "system_admin"}


class ItemUpdate(BaseModel):
    status: str | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    completion_note: str | None = None


def _check(actor: User, goal: DevelopmentGoal):
    if actor.id != goal.user_id and actor.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="无权操作其他用户的成长路线")


@router.get("/goals/{goal_id}/recommendations")
def recommendations(goal_id: int, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    goal = db.get(DevelopmentGoal, goal_id)
    if not goal: raise HTTPException(status_code=404, detail="goal not found")
    _check(actor, goal)
    return integrated_recommendations(db, goal)


@router.post("/goals/{goal_id}/roadmap/generate")
def generate(goal_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    goal = db.get(DevelopmentGoal, goal_id)
    if not goal: raise HTTPException(status_code=404, detail="goal not found")
    _check(actor, goal)
    data = generate_roadmap(db, goal, actor.id)
    write_audit(db, action="development.roadmap.generated", resource_type="development_goal", resource_id=goal.id, actor=actor, details={"item_count": data["summary"]["total"]}, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    return data


@router.get("/goals/{goal_id}/roadmap")
def roadmap(goal_id: int, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    goal = db.get(DevelopmentGoal, goal_id)
    if not goal: raise HTTPException(status_code=404, detail="goal not found")
    _check(actor, goal)
    return roadmap_out(db, goal)


@router.patch("/items/{item_id}")
def patch_item(item_id: int, payload: ItemUpdate, request: Request, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    row = db.get(DevelopmentPlanItem, item_id)
    if not row: raise HTTPException(status_code=404, detail="plan item not found")
    goal = db.get(DevelopmentGoal, row.goal_id)
    _check(actor, goal)
    if payload.status is not None and payload.status not in {"planned", "in_progress", "completed", "skipped"}:
        raise HTTPException(status_code=400, detail="invalid status")
    data, evidence_id = update_plan_item(db, row, status=payload.status, progress_percent=payload.progress_percent, completion_note=payload.completion_note)
    write_audit(db, action="development.roadmap.item.updated", resource_type="development_plan_item", resource_id=row.id, actor=actor, details={"status": data["status"], "progress_percent": data["progress_percent"], "generated_evidence_id": evidence_id}, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))
    return {"item": data, "generated_pending_evidence_id": evidence_id, "message": "标准学习资源完成后仅生成待核验证据，不直接修改能力分。"}
