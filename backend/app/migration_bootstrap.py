from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from .database import DATABASE_URL, engine

BASELINE_REVISION = "v4_0_baseline"
HEAD_REVISION = "v4_7_template_library"

# V4.2 refuses to infer a baseline from table names alone. These fields are stable V4.0 fingerprints.
V4_BASELINE_COLUMNS: dict[str, dict[str, str]] = {
    "users": {"id": "int", "username": "char", "password_hash": "text", "role": "char", "display_name": "char", "created_at": "date"},
    "categories": {"id": "int", "code": "char", "name_zh": "char", "sort_order": "int"},
    "terms": {"id": "int", "zh": "char", "en": "char", "definition_zh_academic": "text", "review_status": "char", "created_at": "date"},
    "assistant_jobs": {"id": "int", "user_id": "int", "domain": "char", "task_type": "char", "status": "char", "input_json": "text"},
    "simulation_jobs": {"id": "int", "user_id": "int", "name": "char", "software": "char", "status": "char", "parameters_json": "text", "workdir": "text"},
}
V4_BASELINE_CONSTRAINTS = {
    "users": {"ck_users_role"},
    "terms": {"ck_terms_review_status", "uq_terms_zh_en"},
    "assistant_jobs": {"ck_assistant_jobs_status"},
    "simulation_jobs": {"ck_simulation_jobs_status"},
}
V4_BASELINE_INDEXES = {
    "users": {"ix_users_username"},
    "terms": {"ix_terms_zh", "ix_terms_en", "ix_terms_review_status"},
    "assistant_jobs": {"ix_assistant_jobs_user_id", "ix_assistant_jobs_status"},
    "simulation_jobs": {"ix_simulation_jobs_user_id", "ix_simulation_jobs_status"},
}
V4_FORBIDDEN_NEWER_FIELDS = {"users": {"is_active"}, "simulation_jobs": {"workspace_task_id", "software_version"}}


def alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    # Use the normalized URL so Railway's postgres:// / postgresql:// value
    # selects the installed psycopg 3 driver during Alembic migrations.
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def current_revision() -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def _type_family(type_obj: Any) -> str:
    value = str(type_obj).lower()
    if "int" in value:
        return "int"
    if any(token in value for token in ("char", "varchar", "string")):
        return "char"
    if "text" in value:
        return "text"
    if any(token in value for token in ("date", "time")):
        return "date"
    if "bool" in value:
        return "bool"
    return value


def baseline_structure_report() -> dict[str, Any]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    report: dict[str, Any] = {"matches": True, "missing_tables": [], "column_differences": {}, "missing_constraints": {}, "missing_indexes": {}, "newer_schema_signals": {}}
    for table, expected_cols in V4_BASELINE_COLUMNS.items():
        if table not in tables:
            report["missing_tables"].append(table)
            report["matches"] = False
            continue
        actual_cols = {col["name"]: _type_family(col["type"]) for col in inspector.get_columns(table)}
        diffs: list[str] = []
        for name, family in expected_cols.items():
            if name not in actual_cols:
                diffs.append(f"missing:{name}")
            elif actual_cols[name] != family:
                diffs.append(f"type:{name} expected={family} actual={actual_cols[name]}")
        if diffs:
            report["column_differences"][table] = diffs
            report["matches"] = False
        forbidden = V4_FORBIDDEN_NEWER_FIELDS.get(table, set()) & set(actual_cols)
        if forbidden:
            report["newer_schema_signals"][table] = sorted(forbidden)
            report["matches"] = False

        constraint_names = {
            item.get("name") for item in inspector.get_check_constraints(table) if item.get("name")
        } | {
            item.get("name") for item in inspector.get_unique_constraints(table) if item.get("name")
        }
        missing_constraints = V4_BASELINE_CONSTRAINTS.get(table, set()) - constraint_names
        if missing_constraints:
            report["missing_constraints"][table] = sorted(missing_constraints)
            report["matches"] = False

        index_names = {item.get("name") for item in inspector.get_indexes(table) if item.get("name")}
        missing_indexes = V4_BASELINE_INDEXES.get(table, set()) - index_names
        if missing_indexes:
            report["missing_indexes"][table] = sorted(missing_indexes)
            report["matches"] = False
    return report


def _require_production_confirmation() -> None:
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    if environment in {"production", "prod"} and os.getenv("V4_BASELINE_CONFIRM", "") != "I_HAVE_VERIFIED_V4_0_BACKUP":
        raise RuntimeError(
            "生产环境旧库自动基线已禁用。请先备份并人工核验结构，然后显式设置 "
            "V4_BASELINE_CONFIRM=I_HAVE_VERIFIED_V4_0_BACKUP。"
        )


def upgrade_database(revision: str = "head") -> dict[str, str | bool | None | dict]:
    tables = set(inspect(engine).get_table_names())
    config = alembic_config()
    stamped = False
    structure_report: dict[str, Any] | None = None
    if tables and "alembic_version" not in tables:
        structure_report = baseline_structure_report()
        if not structure_report["matches"]:
            raise RuntimeError(
                "检测到未受 Alembic 管理的非空数据库，但结构并非严格 V4.0 基线；系统拒绝自动 stamp。结构差异："
                + json.dumps(structure_report, ensure_ascii=False, default=str)
            )
        _require_production_confirmation()
        command.stamp(config, BASELINE_REVISION)
        stamped = True
    command.upgrade(config, revision)
    return {
        "ok": True,
        "action": "upgrade",
        "baseline_stamped": stamped,
        "baseline_structure_report": structure_report,
        "requested_revision": revision,
        "current_revision": current_revision(),
    }


def downgrade_database(revision: str = "-1") -> dict[str, str | bool | None]:
    command.downgrade(alembic_config(), revision)
    return {
        "ok": True,
        "action": "downgrade",
        "requested_revision": revision,
        "current_revision": current_revision(),
    }
