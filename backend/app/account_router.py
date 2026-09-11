from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
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
