from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, User


def write_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    actor: User | None = None,
    actor_user_id: int | None = None,
    outcome: str = "success",
    details: Any = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=actor.id if actor else actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        detail_json=json.dumps(details, ensure_ascii=False, default=str) if details is not None else None,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    return log
