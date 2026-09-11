"""V4.1 engineering foundation.

Revision ID: v4_1_foundation
Revises: v4_0_baseline
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_1_foundation"
down_revision = "v4_0_baseline"
branch_labels = None
depends_on = None

TASK_STATUS = "status IN ('queued','running','succeeded','failed','cancelled')"
USER_ROLE = "role IN ('learning_user','researcher','production_engineer','review_expert','admin','system_admin')"


def _constraint_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item.get("name") for item in inspector.get_check_constraints(table) if item.get("name")}


def upgrade() -> None:
    # Existing V4.0 users are upgraded before the stricter V4.1 role constraint is installed.
    user_checks = _constraint_names("users")
    with op.batch_alter_table("users", recreate="auto") as batch:
        if "ck_users_role" in user_checks:
            batch.drop_constraint("ck_users_role", type_="check")
        batch.alter_column("role", existing_type=sa.String(20), type_=sa.String(32), existing_nullable=False, server_default="learning_user")
        batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE users SET role='learning_user' WHERE role='student'")
    with op.batch_alter_table("users", recreate="auto") as batch:
        batch.create_check_constraint("ck_users_role", USER_ROLE)
        batch.create_index("ix_users_role", ["role"], unique=False)

    op.create_table(
        "workspace_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_code", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_step", sa.String(255)),
        sa.Column("input_json", sa.Text()),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("model_name", sa.String(120)),
        sa.Column("model_version", sa.String(120)),
        sa.Column("software_name", sa.String(120)),
        sa.Column("software_version", sa.String(120)),
        sa.Column("retry_of_id", sa.Integer(), sa.ForeignKey("workspace_tasks.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(TASK_STATUS, name="ck_workspace_tasks_status"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_workspace_tasks_progress"),
        sa.UniqueConstraint("task_code"),
    )
    for col in ["task_code", "task_type", "user_id", "status", "retry_of_id"]:
        op.create_index(f"ix_workspace_tasks_{col}", "workspace_tasks", [col])

    op.create_table(
        "workspace_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("storage_name", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(80), nullable=False),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("workspace_tasks.id", ondelete="SET NULL")),
        sa.Column("confidentiality", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("parse_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("external_ai_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("duplicate_of_id", sa.Integer(), sa.ForeignKey("workspace_files.id", ondelete="SET NULL")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("confidentiality IN ('public','internal','confidential','restricted')", name="ck_workspace_files_confidentiality"),
        sa.CheckConstraint("parse_status IN ('pending','parsing','parsed','failed','not_applicable')", name="ck_workspace_files_parse_status"),
        sa.UniqueConstraint("storage_name"),
        sa.UniqueConstraint("uploader_id", "sha256", "deleted_at", name="uq_workspace_file_active_hash"),
    )
    for col in ["sha256", "uploader_id", "task_id", "confidentiality", "parse_status", "expires_at"]:
        op.create_index(f"ix_workspace_files_{col}", "workspace_files", [col])

    op.create_table(
        "task_files",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("workspace_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("workspace_files.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_role", sa.String(20), nullable=False, server_default="input"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("file_role IN ('input','output','log','intermediate')", name="ck_task_files_role"),
    )
    op.create_table(
        "task_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("workspace_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False, server_default="progress"),
        sa.Column("level", sa.String(20), nullable=False, server_default="info"),
        sa.Column("step", sa.String(255)),
        sa.Column("progress", sa.Integer()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for col in ["task_id", "event_type", "created_at"]:
        op.create_index(f"ix_task_events_{col}", "task_events", [col])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(120)),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="success"),
        sa.Column("detail_json", sa.Text()),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for col in ["actor_user_id", "action", "resource_type", "resource_id", "outcome", "created_at"]:
        op.create_index(f"ix_audit_logs_{col}", "audit_logs", [col])

    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("workspace_tasks.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("external", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_usage_records_task_id", "ai_usage_records", ["task_id"])
    op.create_index("ix_ai_usage_records_user_id", "ai_usage_records", ["user_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("workspace_files.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False, server_default="upload"),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for col in ["file_id", "owner_user_id", "status"]:
        op.create_index(f"ix_knowledge_documents_{col}", "knowledge_documents", [col])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_model", sa.String(120)),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_index"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    sim_checks = _constraint_names("simulation_jobs")
    with op.batch_alter_table("simulation_jobs", recreate="auto") as batch:
        if "ck_simulation_jobs_status" in sim_checks:
            batch.drop_constraint("ck_simulation_jobs_status", type_="check")
        batch.add_column(sa.Column("workspace_task_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("software_version", sa.String(120), nullable=True))
        batch.create_foreign_key("fk_simulation_jobs_workspace_task", "workspace_tasks", ["workspace_task_id"], ["id"], ondelete="SET NULL")
        batch.create_check_constraint("ck_simulation_jobs_status", "status IN ('prepared','queued','running','completed','failed','cancelled')")
        batch.create_index("ix_simulation_jobs_workspace_task_id", ["workspace_task_id"], unique=False)

    op.create_table(
        "simulation_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("simulation_job_id", sa.Integer(), sa.ForeignKey("simulation_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("workspace_tasks.id", ondelete="SET NULL")),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("workspace_files.id", ondelete="SET NULL")),
        sa.Column("artifact_type", sa.String(80), nullable=False),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for col in ["simulation_job_id", "task_id", "file_id"]:
        op.create_index(f"ix_simulation_artifacts_{col}", "simulation_artifacts", [col])


def downgrade() -> None:
    op.drop_table("simulation_artifacts")
    sim_checks = _constraint_names("simulation_jobs")
    with op.batch_alter_table("simulation_jobs", recreate="auto") as batch:
        if "ix_simulation_jobs_workspace_task_id" in {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("simulation_jobs")}:
            batch.drop_index("ix_simulation_jobs_workspace_task_id")
        if "fk_simulation_jobs_workspace_task" in {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("simulation_jobs")}:
            batch.drop_constraint("fk_simulation_jobs_workspace_task", type_="foreignkey")
        if "ck_simulation_jobs_status" in sim_checks:
            batch.drop_constraint("ck_simulation_jobs_status", type_="check")
        batch.drop_column("software_version")
        batch.drop_column("workspace_task_id")
    op.execute("UPDATE simulation_jobs SET status='failed' WHERE status='cancelled'")
    with op.batch_alter_table("simulation_jobs", recreate="auto") as batch:
        batch.create_check_constraint("ck_simulation_jobs_status", "status IN ('prepared','queued','running','completed','failed')")

    for table in ["knowledge_chunks", "knowledge_documents", "ai_usage_records", "audit_logs", "task_events", "task_files", "workspace_files", "workspace_tasks"]:
        op.drop_table(table)

    with op.batch_alter_table("users", recreate="auto") as batch:
        batch.drop_index("ix_users_role")
        batch.drop_constraint("ck_users_role", type_="check")
        batch.drop_column("is_active")
        batch.alter_column("role", existing_type=sa.String(32), type_=sa.String(20), existing_nullable=False, server_default="student")
    op.execute("UPDATE users SET role='admin' WHERE role='system_admin'")
    op.execute("UPDATE users SET role='student' WHERE role <> 'admin'")
    with op.batch_alter_table("users", recreate="auto") as batch:
        batch.create_check_constraint("ck_users_role", "role IN ('student','admin')")
