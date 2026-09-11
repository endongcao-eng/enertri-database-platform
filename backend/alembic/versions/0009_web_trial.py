"""Shared quiz state for multi-process web deployment."""
from alembic import op
import sqlalchemy as sa
revision = "v4_7_web_trial"
down_revision = "v4_7_dynamic_development_loop"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quiz_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False))
    op.create_index("ix_quiz_sessions_expires_at", "quiz_sessions", ["expires_at"])


def downgrade():
    op.drop_index("ix_quiz_sessions_expires_at", table_name="quiz_sessions")
    op.drop_table("quiz_sessions")
