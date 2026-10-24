#!/usr/bin/env python
from __future__ import annotations

from pathlib import Path
import sys

# Allow direct execution via `python scripts/bootstrap.py` in Docker and local shells.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audit import write_audit
from app.database import SessionLocal
from app.file_service import cleanup_expired_files
from app.migration_bootstrap import upgrade_database
from app.security import hash_password
from app.task_queue import recover_expired_tasks
from app.utils import seed_defaults
from app.capability_standard_service import seed_capability_standards
from app.research_profile_service import seed_demo_research_profiles
from app.project_matching_service import seed_demo_project_matching
from app.development_planning_service import seed_demo_development_planning
from app.development_execution_service import seed_demo_closed_loop


def main() -> None:
    from app.production import is_production, validate_production
    validate_production()
    migration = upgrade_database("head")
    if is_production():
        import os
        from sqlalchemy import select
        from app.models import User
        with SessionLocal() as db:
            username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
            if not db.scalar(select(User).where(User.username == username)):
                password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
                if not 16 <= len(password.encode()) <= 72 or password.lower().startswith(("change", "example", "replace")):
                    raise RuntimeError("Set a unique BOOTSTRAP_ADMIN_PASSWORD of at least 16 characters")
                db.add(User(username=username, password_hash=hash_password(password), role="system_admin", display_name="平台管理员", must_change_password=True))
                db.commit()
            write_audit(db, action="database.migration.completed", resource_type="database", resource_id=migration["current_revision"], details={"mode": "production_no_demo_seed"})
        print({"ok": True, "revision": migration["current_revision"], "demo_seeded": False})
        return
    with SessionLocal() as db:
        seed_defaults(db, hash_password)
        standard_seed = seed_capability_standards(db)
        profile_seed = seed_demo_research_profiles(db)
        matching_seed = seed_demo_project_matching(db, hash_password)
        planning_seed = seed_demo_development_planning(db)
        closed_loop_seed = seed_demo_closed_loop(db)
        interrupted = recover_expired_tasks()
        cleaned = cleanup_expired_files(db)
        write_audit(
            db,
            action="database.migration.completed",
            resource_type="database",
            resource_id=migration["current_revision"],
            details={**migration, "capability_standard_seed": standard_seed, "research_profile_seed": profile_seed, "project_matching_seed": matching_seed, "development_planning_seed": planning_seed, "closed_loop_seed": closed_loop_seed, "expired_task_leases_recovered": interrupted, "expired_files_cleaned": cleaned},
        )
    print({"ok": True, **migration, "capability_standard_seed": standard_seed, "research_profile_seed": profile_seed, "project_matching_seed": matching_seed, "development_planning_seed": planning_seed, "closed_loop_seed": closed_loop_seed, "expired_task_leases_recovered": interrupted, "expired_files_cleaned": cleaned})


if __name__ == "__main__":
    main()
