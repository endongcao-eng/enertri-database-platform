"""Shared database controls. No per-process limit state or provider retries."""
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from fastapi import HTTPException
from sqlalchemy import select, update, delete, func
from .database import SessionLocal
from .models import SafetyLock, RateBucket, AIBudgetReservation, WorkspaceTask, User
from .permissions import has_permission


def lock_controls(db):
    # A real write serializes SQLite too. PostgreSQL takes a row lock until commit.
    result=db.execute(update(SafetyLock).where(SafetyLock.id==1).values(value=0))
    if result.rowcount!=1:
        raise RuntimeError("Safety controls migration missing")


def rate_limit(keys, maximum, seconds):
    now=int(time.time()); window=now//seconds; denied=False
    with SessionLocal.begin() as db:
        lock_controls(db)
        db.execute(delete(RateBucket).where(RateBucket.expires_at<=now))
        for key,limit in zip(keys,maximum):
            digest=hashlib.sha256(f"{key}:{window}".encode()).hexdigest()
            row=db.get(RateBucket,digest)
            if row is None:
                row=RateBucket(key=digest,count=0,expires_at=(window+1)*seconds);db.add(row)
            if row.count>=limit: denied=True
            row.count=min(row.count+1,limit+1)
    if denied:
        raise HTTPException(429,"尝试过于频繁，请稍后再试",headers={"Retry-After":str(seconds-now%seconds)})


def task_admission(db,user_id):
    from .production import is_production
    lock_controls(db)
    active=("queued","running")
    own=db.scalar(select(func.count()).select_from(WorkspaceTask).where(WorkspaceTask.user_id==user_id,WorkspaceTask.status.in_(active)))
    total=db.scalar(select(func.count()).select_from(WorkspaceTask).where(WorkspaceTask.status.in_(active)))
    default=3 if is_production() else 1000
    if own>=int(os.getenv("TASK_USER_ACTIVE_LIMIT",str(default))) or total>=int(os.getenv("TASK_GLOBAL_ACTIVE_LIMIT","100" if is_production() else "10000")):
        db.rollback();raise HTTPException(429,"任务队列额度已用完，请等待现有任务完成",headers={"Retry-After":"30"})
    midnight=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    daily=db.scalar(select(func.count()).select_from(WorkspaceTask).where(WorkspaceTask.user_id==user_id,WorkspaceTask.created_at>=midnight))
    if daily>=int(os.getenv("TASK_USER_DAILY_LIMIT","20" if is_production() else "10000")):
        db.rollback();raise HTTPException(429,"今日任务次数已用完，UTC 零点恢复")


def usd_micros(name,default):
    value=Decimal(os.getenv(name,default))
    if not value.is_finite() or value<=0: raise ValueError(f"Invalid {name}")
    return int((value*1000000).to_integral_value(rounding=ROUND_CEILING))


def reserve_ai(user_id):
    day=datetime.now(timezone.utc).date().isoformat();now=int(time.time())
    amount=usd_micros("AI_REQUEST_RESERVATION_USD","0.10")
    with SessionLocal.begin() as db:
        lock_controls(db)
        user=db.get(User,user_id) if user_id is not None else None
        if not user or not user.is_active or user.must_change_password or not has_permission(user.role,"ai.external"):
            raise HTTPException(403,"当前账号不能调用外部 AI")
        for uid,limit_name,default,calls_name,calls_default in [(user_id,"AI_USER_DAILY_USD","1","AI_USER_DAILY_CALLS","20"),(None,"AI_GLOBAL_DAILY_USD","10","AI_GLOBAL_DAILY_CALLS","200")]:
            query=select(func.coalesce(func.sum(AIBudgetReservation.reserved_usd_micros),0),func.count()).where(AIBudgetReservation.day==day)
            running=select(func.count()).select_from(AIBudgetReservation).where(AIBudgetReservation.status=="reserved",AIBudgetReservation.expires_at>now)
            if uid is not None:
                query=query.where(AIBudgetReservation.user_id==uid);running=running.where(AIBudgetReservation.user_id==uid)
            used,count=db.execute(query).one()
            slots=int(os.getenv("AI_USER_CONCURRENCY" if uid is not None else "AI_GLOBAL_CONCURRENCY","1" if uid is not None else "2"))
            if used+amount>usd_micros(limit_name,default) or count>=int(os.getenv(calls_name,calls_default)) or db.scalar(running)>=slots:
                raise HTTPException(429,"AI 预算、次数或并发额度已用完，请稍后重试")
        rid=str(uuid.uuid4())
        db.add(AIBudgetReservation(id=rid,user_id=user_id,day=day,reserved_usd_micros=amount,status="reserved",expires_at=now+int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS","180"))+300))
    return rid


def finish_ai(rid,usage=None,failed=False):
    # Never refund on uncertain network outcome. Reservations are a conservative ledger,
    # not the provider invoice. Crash reservations still count against the daily budget.
    with SessionLocal.begin() as db:
        db.execute(update(AIBudgetReservation).where(AIBudgetReservation.id==rid).values(status="failed" if failed else "completed",usage_json=json.dumps(usage or {})))
