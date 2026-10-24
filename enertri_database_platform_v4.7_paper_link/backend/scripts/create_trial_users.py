"""Import pre-assigned personal accounts from stdin CSV. No plaintext output.
Required columns: username,display_name,password; optional role (default learning_user).
Entire batch is atomic; existing accounts are rejected rather than overwritten.
"""
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User
from app.security import hash_password
from app.audit import write_audit


def main():
    rows = list(csv.DictReader(sys.stdin))
    if not rows or len(rows) > 150:
        raise SystemExit("Supply between 1 and 150 accounts")
    names = set()
    with SessionLocal.begin() as db:
        for row in rows:
            name = row.get("username", "").strip()
            display = row.get("display_name", "").strip()
            password = row.get("password", "")
            role = row.get("role") or "learning_user"
            if not name or len(name)>80 or not display or len(display)>120 or not 16 <= len(password.encode()) <= 72:
                raise SystemExit("Invalid username, display name or password length (16–72 UTF-8 bytes)")
            if role not in {"learning_user", "researcher", "production_engineer", "review_expert"}:
                raise SystemExit("Bulk import cannot grant administrator roles")
            if name in names or db.scalar(select(User.id).where(User.username == name)):
                raise SystemExit("Duplicate/existing account: batch aborted")
            names.add(name)
            db.add(User(username=name, display_name=display, password_hash=hash_password(password), role=role, must_change_password=True))
    with SessionLocal() as db:
        write_audit(db, action="trial.accounts.imported", resource_type="user", resource_id="batch", details={"count": len(rows)})
    print(f"Created {len(rows)} personal accounts; passwords omitted")


if __name__ == "__main__":
    main()
