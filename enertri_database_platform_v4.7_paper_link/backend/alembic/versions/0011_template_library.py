"""Template library with role-controlled upload and authenticated download."""
from alembic import op
import sqlalchemy as sa

revision = "v4_7_template_library"
down_revision = "v4_7_trial_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("category IN ('pdf','ppt','excel','word')", name="ck_template_files_category"),
        sa.UniqueConstraint("file_id", name="uq_template_files_file_id"),
    )
    op.create_index("ix_template_files_file_id", "template_files", ["file_id"], unique=True)
    op.create_index("ix_template_files_category", "template_files", ["category"])
    op.create_index("ix_template_files_title", "template_files", ["title"])
    op.create_index("ix_template_files_uploader_id", "template_files", ["uploader_id"])


def downgrade():
    op.drop_index("ix_template_files_uploader_id", table_name="template_files")
    op.drop_index("ix_template_files_title", table_name="template_files")
    op.drop_index("ix_template_files_category", table_name="template_files")
    op.drop_index("ix_template_files_file_id", table_name="template_files")
    op.drop_table("template_files")
