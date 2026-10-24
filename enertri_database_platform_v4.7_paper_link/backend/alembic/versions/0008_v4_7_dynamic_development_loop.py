"""V4.7 stage 5 integrated roadmap and dynamic evidence closed loop.

Revision ID: v4_7_dynamic_development_loop
Revises: v4_6_development_planning
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_7_dynamic_development_loop"
down_revision = "v4_6_development_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_plan_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("development_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("source_resource_id", sa.Integer(), sa.ForeignKey("learning_resources.id", ondelete="SET NULL")),
        sa.Column("source_publication_id", sa.Integer(), sa.ForeignKey("publications.id", ondelete="SET NULL")),
        sa.Column("source_project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("priority_score", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="planned"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text()),
        sa.Column("gap_targets_json", sa.Text()),
        sa.Column("completion_note", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("item_type IN ('course','book','project_task','publication','research_project')", name="ck_development_plan_items_type"),
        sa.CheckConstraint("status IN ('planned','in_progress','completed','skipped')", name="ck_development_plan_items_status"),
        sa.CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="ck_development_plan_items_progress"),
        sa.UniqueConstraint("goal_id", "item_type", "source_resource_id", "source_publication_id", "source_project_id", name="uq_development_plan_source"),
    )
    op.create_index("ix_development_plan_items_goal_id", "development_plan_items", ["goal_id"])
    op.create_index("ix_development_plan_items_user_id", "development_plan_items", ["user_id"])
    op.create_index("ix_development_plan_items_status", "development_plan_items", ["status"])

    op.create_table(
        "development_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("development_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_type", sa.String(24), nullable=False, server_default="recalculated"),
        sa.Column("match_score", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("capability_fit", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("knowledge_fit", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("evidence_confidence", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("critical_gap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("snapshot_type IN ('baseline','recalculated','completion')", name="ck_development_snapshots_type"),
    )
    op.create_index("ix_development_snapshots_goal_id", "development_snapshots", ["goal_id"])
    op.create_index("ix_development_snapshots_user_id", "development_snapshots", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_development_snapshots_user_id", table_name="development_snapshots")
    op.drop_index("ix_development_snapshots_goal_id", table_name="development_snapshots")
    op.drop_table("development_snapshots")
    op.drop_index("ix_development_plan_items_status", table_name="development_plan_items")
    op.drop_index("ix_development_plan_items_user_id", table_name="development_plan_items")
    op.drop_index("ix_development_plan_items_goal_id", table_name="development_plan_items")
    op.drop_table("development_plan_items")
