"""Add directory-preserving HTML learning page bundles."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_html_learning_bundles"
down_revision = "v4_7_html_learning_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("html_learning_assets", sa.Column("is_bundle", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("html_learning_assets", sa.Column("bundle_name", sa.String(length=255), nullable=True))
    op.add_column("html_learning_assets", sa.Column("bundle_root", sa.Text(), nullable=True))
    op.create_index("ix_html_learning_assets_bundle_name", "html_learning_assets", ["bundle_name"])


def downgrade() -> None:
    op.drop_index("ix_html_learning_assets_bundle_name", table_name="html_learning_assets")
    op.drop_column("html_learning_assets", "bundle_root")
    op.drop_column("html_learning_assets", "bundle_name")
    op.drop_column("html_learning_assets", "is_bundle")
