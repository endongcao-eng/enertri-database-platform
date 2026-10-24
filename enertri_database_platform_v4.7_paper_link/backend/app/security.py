from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

import jwt
from jwt import InvalidTokenError as JWTError

try:  # Production image installs passlib+bcrypt.
    from passlib.context import CryptContext
except ImportError:
    CryptContext = None

from .database import get_db
from .models import User
from .permissions import ROLE_PERMISSIONS, has_permission

from .production import validate_production
validate_production()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") if CryptContext else None
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    if pwd_context:
        return pwd_context.hash(password)
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return "pbkdf2_sha256$180000$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(derived).decode())


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt64, digest64 = password_hash.split("$", 3)
            derived = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt64), int(rounds))
            return hmac.compare_digest(derived, base64.b64decode(digest64))
        except Exception:
            return False
    if pwd_context:
        if len(password.encode()) > 72: return False
        try: return pwd_context.verify(password, password_hash)
        except (ValueError, TypeError): return False
    return False


def create_access_token(subject: str, role: str, expires_delta: Optional[timedelta] = None, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return jwt.encode({"sub": subject, "role": role, "exp": expire, "ver": token_version}, SECRET_KEY, algorithm=ALGORITHM)


def _resolve_user(token: str | None, db: Session, *, required: bool) -> User | None:
    if not token:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise JWTError("missing subject")
    except JWTError:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效")
        return None
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active or payload.get("ver", 0) != user.token_version:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
        return None
    return user


def optional_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User | None:
    user = _resolve_user(token, db, required=False)
    return None if user and user.must_change_password else user


def current_user(request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    user = _resolve_user(token, db, required=True)
    assert user is not None
    if user.must_change_password and request.url.path not in {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}:
        raise HTTPException(403, detail="PASSWORD_CHANGE_REQUIRED")
    return user


def require_permission(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"当前角色缺少权限：{permission}")
        return user
    return dependency


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "system_admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def user_permissions(user: User) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(user.role, set()))
