#!/usr/bin/env python
from __future__ import annotations
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal
from app.capability_standard_service import seed_capability_standards

if __name__ == '__main__':
    with SessionLocal() as db:
        print({"ok": True, **seed_capability_standards(db)})
