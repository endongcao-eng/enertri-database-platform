"""Add a schema-compatible read-through mirror for the Space Energy catalog."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_space_energy_literature"
down_revision = "v4_7_template_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_energy_literatures",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
    )
    op.create_index("ix_space_energy_literatures_doi", "space_energy_literatures", ["doi"])
    op.create_index("ix_space_energy_literatures_year", "space_energy_literatures", ["year"])
    op.create_index("ix_space_energy_literatures_source", "space_energy_literatures", ["source"])


def downgrade() -> None:
    op.drop_index("ix_space_energy_literatures_source", table_name="space_energy_literatures")
    op.drop_index("ix_space_energy_literatures_year", table_name="space_energy_literatures")
    op.drop_index("ix_space_energy_literatures_doi", table_name="space_energy_literatures")
    op.drop_table("space_energy_literatures")
