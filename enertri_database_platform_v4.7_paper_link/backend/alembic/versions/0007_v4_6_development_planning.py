"""V4.6 stage 4 development planning and research-direction gap analysis.

Revision ID: v4_6_development_planning
Revises: v4_5_project_talent_matching
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_6_development_planning"
down_revision = "v4_5_project_talent_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("target_project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="SET NULL")),
        sa.Column("requirements_json", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("goal_type IN ('student_growth','teacher_research_direction')", name="ck_development_goals_type"),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_development_goals_status"),
    )
    op.create_index("ix_development_goals_user_id", "development_goals", ["user_id"])
    op.create_index("ix_development_goals_goal_type", "development_goals", ["goal_type"])
    op.create_index("ix_development_goals_target_project_id", "development_goals", ["target_project_id"])
    op.create_index("ix_development_goals_status", "development_goals", ["status"])
    op.create_index("ix_development_goals_created_by", "development_goals", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_development_goals_created_by", table_name="development_goals")
    op.drop_index("ix_development_goals_status", table_name="development_goals")
    op.drop_index("ix_development_goals_target_project_id", table_name="development_goals")
    op.drop_index("ix_development_goals_goal_type", table_name="development_goals")
    op.drop_index("ix_development_goals_user_id", table_name="development_goals")
    op.drop_table("development_goals")
