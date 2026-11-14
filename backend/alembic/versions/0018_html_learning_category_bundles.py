"""Associate directory-preserving HTML bundles with child categories."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_html_category_bundles"
down_revision = "v4_7_html_learning_bundles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "html_learning_assets",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_html_learning_assets_category_id",
        "html_learning_assets",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_html_learning_assets_category_id", "html_learning_assets", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_html_learning_assets_category_id", table_name="html_learning_assets")
    op.drop_constraint("fk_html_learning_assets_category_id", "html_learning_assets", type_="foreignkey")
    op.drop_column("html_learning_assets", "category_id")
