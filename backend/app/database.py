from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()


def normalize_database_url(raw_url: str) -> str:
    """Accept Railway's standard postgres URL while keeping psycopg explicit."""
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url or "sqlite:///./enertri.db"


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./enertri.db"))
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "./media")).resolve()
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
(MEDIA_DIR / "videos").mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = Path(os.getenv("ARTIFACT_DIR", str(MEDIA_DIR / "artifacts"))).resolve()
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", str(MEDIA_DIR / "workspace"))).resolve()
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
