"""Add table provenance, previews and correction metadata for research use."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_literature_research_value"
down_revision = "v4_7_operational_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_tables", sa.Column("bbox_json", sa.Text(), nullable=True))
    op.add_column("knowledge_tables", sa.Column("extraction_strategy", sa.String(length=80), nullable=False, server_default="unknown"))
    op.add_column("knowledge_tables", sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("knowledge_tables", sa.Column("preview_path", sa.Text(), nullable=True))
    op.add_column("knowledge_tables", sa.Column("correction_json", sa.Text(), nullable=True))
    op.create_index("ix_knowledge_tables_strategy", "knowledge_tables", ["extraction_strategy"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_tables_strategy", table_name="knowledge_tables")
    op.drop_column("knowledge_tables", "correction_json")
    op.drop_column("knowledge_tables", "preview_path")
    op.drop_column("knowledge_tables", "confidence")
    op.drop_column("knowledge_tables", "extraction_strategy")
    op.drop_column("knowledge_tables", "bbox_json")
