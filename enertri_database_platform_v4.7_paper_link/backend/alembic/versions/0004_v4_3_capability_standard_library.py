"""V4.3 stage 1 research capability standard library.

Revision ID: v4_3_capability_standard_library
Revises: v4_2_knowledge_system
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_3_capability_standard_library"
down_revision = "v4_2_knowledge_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name_zh", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("domain", sa.String(120), nullable=False, server_default="general"),
        sa.Column("node_type", sa.String(40), nullable=False, server_default="concept"),
        sa.Column("description", sa.Text()),
        sa.Column("linked_term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="SET NULL")),
        sa.Column("level_scale", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_knowledge_nodes_code"),
        sa.CheckConstraint("node_type IN ('concept','theory','method','tool','practice')", name="ck_knowledge_nodes_type"),
        sa.CheckConstraint("status IN ('active','draft','archived')", name="ck_knowledge_nodes_status"),
        sa.CheckConstraint("level_scale BETWEEN 1 AND 10", name="ck_knowledge_nodes_level_scale"),
    )
    op.create_index("ix_knowledge_nodes_code", "knowledge_nodes", ["code"])
    op.create_index("ix_knowledge_nodes_domain", "knowledge_nodes", ["domain"])
    op.create_index("ix_knowledge_nodes_linked_term_id", "knowledge_nodes", ["linked_term_id"])

    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_node_id", sa.Integer(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.Integer(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(40), nullable=False, server_default="related"),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1.0"),
        sa.Column("rationale", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_knowledge_relation"),
        sa.CheckConstraint("relation_type IN ('prerequisite','part_of','related','enables')", name="ck_knowledge_relation_type"),
    )
    op.create_index("ix_knowledge_relations_source", "knowledge_relations", ["source_node_id"])
    op.create_index("ix_knowledge_relations_target", "knowledge_relations", ["target_node_id"])

    op.create_table(
        "capabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name_zh", sa.String(255), nullable=False),
        sa.Column("name_en", sa.String(255)),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("level_scale", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("rubric_json", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_capabilities_code"),
        sa.CheckConstraint("category IN ('theory','methodology','computation','experiment','research','communication','project')", name="ck_capabilities_category"),
        sa.CheckConstraint("status IN ('active','draft','archived')", name="ck_capabilities_status"),
        sa.CheckConstraint("level_scale BETWEEN 1 AND 10", name="ck_capabilities_level_scale"),
    )
    op.create_index("ix_capabilities_code", "capabilities", ["code"])
    op.create_index("ix_capabilities_category", "capabilities", ["category"])

    op.create_table(
        "capability_knowledge_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capability_id", sa.Integer(), sa.ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_node_id", sa.Integer(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False, server_default="requires"),
        sa.Column("required_level", sa.Numeric(4, 2), nullable=False, server_default="1.0"),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1.0"),
        sa.Column("rationale", sa.Text()),
        sa.UniqueConstraint("capability_id", "knowledge_node_id", "relation_type", name="uq_capability_knowledge_link"),
        sa.CheckConstraint("relation_type IN ('requires','supports')", name="ck_capability_knowledge_relation_type"),
    )
    op.create_index("ix_capability_knowledge_capability", "capability_knowledge_links", ["capability_id"])
    op.create_index("ix_capability_knowledge_node", "capability_knowledge_links", ["knowledge_node_id"])

    op.create_table(
        "learning_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("subtitle", sa.String(512)),
        sa.Column("discipline", sa.String(160)),
        sa.Column("provider", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_learning_resources_code"),
        sa.CheckConstraint("resource_type IN ('course','book','project_task')", name="ck_learning_resources_type"),
        sa.CheckConstraint("status IN ('active','draft','archived')", name="ck_learning_resources_status"),
    )
    op.create_index("ix_learning_resources_code", "learning_resources", ["code"])
    op.create_index("ix_learning_resources_type", "learning_resources", ["resource_type"])
    op.create_index("ix_learning_resources_discipline", "learning_resources", ["discipline"])

    op.create_table(
        "resource_knowledge_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_node_id", sa.Integer(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coverage_level", sa.Numeric(4, 2), nullable=False, server_default="1.0"),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1.0"),
        sa.Column("evidence_strength", sa.Numeric(6, 3), nullable=False, server_default="0.5"),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("resource_id", "knowledge_node_id", name="uq_resource_knowledge_link"),
    )
    op.create_index("ix_resource_knowledge_resource", "resource_knowledge_links", ["resource_id"])
    op.create_index("ix_resource_knowledge_node", "resource_knowledge_links", ["knowledge_node_id"])

    op.create_table(
        "resource_capability_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_id", sa.Integer(), sa.ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contribution_level", sa.Numeric(4, 2), nullable=False, server_default="1.0"),
        sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1.0"),
        sa.Column("evidence_strength", sa.Numeric(6, 3), nullable=False, server_default="0.5"),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("resource_id", "capability_id", name="uq_resource_capability_link"),
    )
    op.create_index("ix_resource_capability_resource", "resource_capability_links", ["resource_id"])
    op.create_index("ix_resource_capability_capability", "resource_capability_links", ["capability_id"])


def downgrade() -> None:
    op.drop_table("resource_capability_links")
    op.drop_table("resource_knowledge_links")
    op.drop_table("learning_resources")
    op.drop_table("capability_knowledge_links")
    op.drop_table("capabilities")
    op.drop_table("knowledge_relations")
    op.drop_table("knowledge_nodes")
