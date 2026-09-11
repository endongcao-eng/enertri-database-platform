from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from .database import SessionLocal, engine
from .models import TaskEvent, WorkspaceTask

LEASE_SECONDS = max(30, int(os.getenv("TASK_LEASE_SECONDS", "90")))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_task(worker_id: str) -> dict[str, Any] | None:
    """Atomically claim one queued task. PostgreSQL uses SKIP LOCKED for multi-worker safety."""
    with SessionLocal() as db:
        with db.begin():
            from .controls import lock_controls
            lock_controls(db)
            global_limit=int(os.getenv("TASK_GLOBAL_RUNNING_LIMIT", "2"))
            user_limit=int(os.getenv("TASK_USER_RUNNING_LIMIT", "1"))
            running_count=db.scalar(select(func.count()).select_from(WorkspaceTask).where(WorkspaceTask.status=="running"))
            if running_count>=global_limit: return None
            busy=select(WorkspaceTask.user_id).where(WorkspaceTask.status=="running").group_by(WorkspaceTask.user_id).having(func.count()>=user_limit)
            stmt = select(WorkspaceTask).where(WorkspaceTask.status == "queued", WorkspaceTask.user_id.not_in(busy)).order_by(WorkspaceTask.id).limit(1)
            if engine.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)
            else:
                stmt = stmt.with_for_update()
            task = db.scalar(stmt)
            if not task:
                return None
            now = utcnow()
            task.status = "running"
            task.worker_id = worker_id
            task.attempt_count = int(task.attempt_count or 0) + 1
            task.last_claimed_at = now
            task.heartbeat_at = now
            task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
            task.started_at = task.started_at or now
            task.progress = max(3, int(task.progress or 0))
            task.current_step = "Worker 已抢占"
            db.add(TaskEvent(
                task_id=task.id, event_type="status", step="Worker 已抢占", progress=task.progress,
                message=f"任务由独立 Worker {worker_id} 原子抢占（第 {task.attempt_count} 次尝试）",
            ))
            task_id = task.id
            timeout = int(task.timeout_seconds or 1800)
        return {"id": task_id, "timeout_seconds": timeout}


def heartbeat_task(task_id: int, worker_id: str) -> bool:
    with SessionLocal() as db:
        task = db.get(WorkspaceTask, task_id)
        if not task or task.status != "running" or task.worker_id != worker_id:
            return False
        now = utcnow()
        task.heartbeat_at = now
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        db.commit()
        return True


def task_state(task_id: int, worker_id: str | None = None) -> str | None:
    with SessionLocal() as db:
        task = db.get(WorkspaceTask, task_id)
        if not task:
            return None
        if worker_id and task.worker_id not in {None, worker_id}:
            return "lost_lease"
        return task.status


def fail_claimed_task(task_id: int, worker_id: str, message: str, step: str = "Worker 执行失败") -> bool:
    with SessionLocal() as db:
        task = db.get(WorkspaceTask, task_id)
        if not task or task.status != "running" or task.worker_id != worker_id:
            return False
        task.status = "failed"
        task.current_step = step
        task.error_message = message
        task.finished_at = utcnow()
        task.heartbeat_at = utcnow()
        task.lease_expires_at = None
        db.add(TaskEvent(task_id=task.id, event_type="error", level="error", step=step, progress=task.progress, message=message))
        db.commit()
        return True


def recover_expired_tasks() -> int:
    """Only running tasks whose lease has actually expired are considered interrupted."""
    now = utcnow()
    with SessionLocal() as db:
        tasks = db.scalars(
            select(WorkspaceTask).where(
                WorkspaceTask.status == "running",
                WorkspaceTask.lease_expires_at.is_not(None),
                WorkspaceTask.lease_expires_at < now,
            )
        ).all()
        for task in tasks:
            previous_worker = task.worker_id
            task.status = "failed"
            task.current_step = "Worker 租约过期"
            task.error_message = f"任务 Worker 租约已过期（worker={previous_worker or 'unknown'}）；任务已判定为中断，可重新执行。"
            task.finished_at = now
            task.worker_id = None
            task.lease_expires_at = None
            db.add(TaskEvent(
                task_id=task.id, event_type="error", level="warning", step="Worker 租约过期",
                progress=task.progress, message=task.error_message,
            ))
        db.commit()
        return len(tasks)


def queue_stats() -> dict[str, int]:
    with SessionLocal() as db:
        rows = db.execute(select(WorkspaceTask.status, func.count(WorkspaceTask.id)).group_by(WorkspaceTask.status)).all()
        return {str(status): int(count) for status, count in rows}
