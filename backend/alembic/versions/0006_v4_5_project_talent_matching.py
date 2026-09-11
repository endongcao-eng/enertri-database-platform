"""V4.5 stage 3 project requirement and talent matching foundation.

Revision ID: v4_5_project_talent_matching
Revises: v4_4_student_research_profile
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_5_project_talent_matching"
down_revision = "v4_4_student_research_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("research_direction", sa.String(255)),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','active','archived')", name="ck_research_projects_status"),
    )
    op.create_index("ix_research_projects_status", "research_projects", ["status"])
    op.create_index("ix_research_projects_created_by", "research_projects", ["created_by"])

    op.create_table(
        "project_capability_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_id", sa.Integer(), sa.ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("required_level", sa.Numeric(4, 2), nullable=False, server_default="3"),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1"),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("project_id", "capability_id", name="uq_project_capability_requirement"),
        sa.CheckConstraint("required_level >= 0 AND required_level <= 5", name="ck_project_capability_required_level"),
        sa.CheckConstraint("weight > 0", name="ck_project_capability_weight"),
    )
    op.create_index("ix_project_capability_requirements_project_id", "project_capability_requirements", ["project_id"])
    op.create_index("ix_project_capability_requirements_capability_id", "project_capability_requirements", ["capability_id"])

    op.create_table(
        "project_knowledge_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_node_id", sa.Integer(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("required_level", sa.Numeric(4, 2), nullable=False, server_default="3"),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1"),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("project_id", "knowledge_node_id", name="uq_project_knowledge_requirement"),
        sa.CheckConstraint("required_level >= 0 AND required_level <= 5", name="ck_project_knowledge_required_level"),
        sa.CheckConstraint("weight > 0", name="ck_project_knowledge_weight"),
    )
    op.create_index("ix_project_knowledge_requirements_project_id", "project_knowledge_requirements", ["project_id"])
    op.create_index("ix_project_knowledge_requirements_knowledge_node_id", "project_knowledge_requirements", ["knowledge_node_id"])


def downgrade() -> None:
    op.drop_index("ix_project_knowledge_requirements_knowledge_node_id", table_name="project_knowledge_requirements")
    op.drop_index("ix_project_knowledge_requirements_project_id", table_name="project_knowledge_requirements")
    op.drop_table("project_knowledge_requirements")
    op.drop_index("ix_project_capability_requirements_capability_id", table_name="project_capability_requirements")
    op.drop_index("ix_project_capability_requirements_project_id", table_name="project_capability_requirements")
    op.drop_table("project_capability_requirements")
    op.drop_index("ix_research_projects_created_by", table_name="research_projects")
    op.drop_index("ix_research_projects_status", table_name="research_projects")
    op.drop_table("research_projects")
