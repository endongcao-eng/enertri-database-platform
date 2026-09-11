"""Operator-only password reset. Run interactively on the server; never prints secrets."""
import argparse, getpass, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User
from app.security import hash_password
from app.audit import write_audit
p=argparse.ArgumentParser();p.add_argument("username");args=p.parse_args()
password=getpass.getpass("New temporary password: ")
confirm=getpass.getpass("Confirm temporary password: ")
if password!=confirm or not 16<=len(password.encode())<=72: raise SystemExit("Password mismatch or invalid UTF-8 length")
with SessionLocal.begin() as db:
    user=db.scalar(select(User).where(User.username==args.username).with_for_update())
    if not user: raise SystemExit("Account not found")
    user.password_hash=hash_password(password);user.token_version+=1;user.must_change_password=True
    write_audit(db,action="auth.operator.reset",resource_type="user",resource_id=user.id,details={"forced_change":True},commit=False)
print("Password reset; all sessions revoked; next login must change password")
