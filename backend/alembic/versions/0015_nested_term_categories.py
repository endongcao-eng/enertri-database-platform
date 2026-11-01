"""Add parent-child hierarchy to terminology categories."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_nested_term_categories"
down_revision = "v4_7_literature_research_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_categories_parent_id_categories",
            "categories",
            ["parent_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_categories_parent_id", table_name="categories")
    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_constraint("fk_categories_parent_id_categories", type_="foreignkey")
        batch_op.drop_column("parent_id")
