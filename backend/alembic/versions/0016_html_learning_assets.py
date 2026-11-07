"""Add persistent HTML learning resources linked to terminology."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_html_learning_assets"
down_revision = "v4_7_nested_term_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("terms", sa.Column("definition_ru", sa.Text(), nullable=True))
    op.add_column("terms", sa.Column("html_video_available", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("terms", sa.Column("html_article_available", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "html_learning_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("asset_kind", sa.String(length=20), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False, server_default="text/html"),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("asset_kind IN ('video','article')", name="ck_html_learning_assets_kind"),
        sa.UniqueConstraint("original_name", name="uq_html_learning_assets_original_name"),
    )
    op.create_index("ix_html_learning_assets_term_id", "html_learning_assets", ["term_id"])
    op.create_index("ix_html_learning_assets_original_name", "html_learning_assets", ["original_name"])
    op.create_index("ix_html_learning_assets_asset_kind", "html_learning_assets", ["asset_kind"])
    op.create_index("ix_html_learning_assets_uploader_id", "html_learning_assets", ["uploader_id"])


def downgrade() -> None:
    op.drop_index("ix_html_learning_assets_uploader_id", table_name="html_learning_assets")
    op.drop_index("ix_html_learning_assets_asset_kind", table_name="html_learning_assets")
    op.drop_index("ix_html_learning_assets_original_name", table_name="html_learning_assets")
    op.drop_index("ix_html_learning_assets_term_id", table_name="html_learning_assets")
    op.drop_table("html_learning_assets")
    op.drop_column("terms", "html_article_available")
    op.drop_column("terms", "html_video_available")
    op.drop_column("terms", "definition_ru")
