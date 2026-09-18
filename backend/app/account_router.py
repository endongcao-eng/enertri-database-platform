import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import User
from .security import current_user, verify_password, hash_password
from .controls import rate_limit, lock_controls
from .audit import write_audit
router=APIRouter(prefix="/api/auth",tags=["account"])

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1,max_length=256)
    new_password: str = Field(min_length=16,max_length=72)


class RegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=16, max_length=72)
    password_confirm: str = Field(min_length=16, max_length=72)


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
def register_account(payload: RegistrationRequest, request: Request, db: Session = Depends(get_db)):
    """Create a self-service learning account; elevated roles remain admin-managed."""
    rate_limit(
        ["register:ip:" + (request.client.host if request.client else "unknown")],
        [int(os.getenv("REGISTER_IP_LIMIT", "5"))],
        int(os.getenv("REGISTER_WINDOW_SECONDS", "900")),
    )
    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码不能超过 72 个 UTF-8 字节")
    if not re.search(r"\S", payload.display_name):
        raise HTTPException(status_code=400, detail="显示名称不能为空")
    lock_controls(db)
    user = User(username=payload.username.strip(), display_name=payload.display_name.strip(), role="learning_user", password_hash=hash_password(payload.password), is_active=True)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在，请使用其他用户名")
    write_audit(db, action="auth.account.registered", resource_type="user", resource_id=user.id, actor_user_id=user.id, details={"role": user.role}, commit=False)
    db.commit()
    db.refresh(user)
    return {"ok": True, "user": {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}, "message": "账号创建成功，请登录"}

@router.post("/password")
def change_password(payload:PasswordChange,db:Session=Depends(get_db),actor:User=Depends(current_user)):
    rate_limit([f"change-password:{actor.id}"],[5],900)
    lock_controls(db)
    user=db.scalar(select(User).where(User.id==actor.id).with_for_update().execution_options(populate_existing=True))
    if not verify_password(payload.current_password,user.password_hash):
        raise HTTPException(400,"当前密码不正确")
    if len(payload.new_password.encode())>72 or payload.new_password==payload.current_password:
        raise HTTPException(400,"新密码必须与原密码不同，且不超过72个UTF-8字节")
    user.password_hash=hash_password(payload.new_password)
    user.token_version+=1
    user.must_change_password=False
    write_audit(db,action="auth.password.changed",resource_type="user",resource_id=user.id,actor=user,commit=False)
    db.commit()
    return {"ok":True,"reauthenticate":True}

@router.post("/logout")
def logout(db:Session=Depends(get_db),actor:User=Depends(current_user)):
    db.execute(update(User).where(User.id==actor.id).values(token_version=User.token_version+1))
    db.commit()
    return {"ok":True,"all_sessions_revoked":True}
