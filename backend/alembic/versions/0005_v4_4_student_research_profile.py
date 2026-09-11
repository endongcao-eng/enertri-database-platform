"""V4.4 stage 2 evidence-backed student research profile.

Revision ID: v4_4_student_research_profile
Revises: v4_3_capability_standard_library
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_4_student_research_profile"
down_revision = "v4_3_capability_standard_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("grade_percent", sa.Numeric(5, 2)),
        sa.Column("completion_ratio", sa.Numeric(6, 4), nullable=False, server_default="1"),
        sa.Column("independence_ratio", sa.Numeric(6, 4)),
        sa.Column("quality_rating", sa.Numeric(4, 2)),
        sa.Column("mentor_rating", sa.Numeric(4, 2)),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="self_reported"),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("verification_note", sa.Text()),
        sa.Column("occurred_on", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("evidence_type IN ('course_grade','book_reading','project_participation')", name="ck_student_evidence_type"),
        sa.CheckConstraint("verification_status IN ('self_reported','pending','verified','rejected')", name="ck_student_evidence_verification"),
        sa.CheckConstraint("grade_percent IS NULL OR (grade_percent >= 0 AND grade_percent <= 100)", name="ck_student_evidence_grade"),
        sa.CheckConstraint("completion_ratio >= 0 AND completion_ratio <= 1", name="ck_student_evidence_completion"),
        sa.CheckConstraint("independence_ratio IS NULL OR (independence_ratio >= 0 AND independence_ratio <= 1)", name="ck_student_evidence_independence"),
        sa.CheckConstraint("quality_rating IS NULL OR (quality_rating >= 0 AND quality_rating <= 5)", name="ck_student_evidence_quality"),
        sa.CheckConstraint("mentor_rating IS NULL OR (mentor_rating >= 0 AND mentor_rating <= 5)", name="ck_student_evidence_mentor"),
    )
    op.create_index("ix_student_evidence_user_id", "student_evidence", ["user_id"])
    op.create_index("ix_student_evidence_resource_id", "student_evidence", ["resource_id"])
    op.create_index("ix_student_evidence_evidence_type", "student_evidence", ["evidence_type"])
    op.create_index("ix_student_evidence_verification_status", "student_evidence", ["verification_status"])
    op.create_index("ix_student_evidence_verified_by", "student_evidence", ["verified_by"])


def downgrade() -> None:
    op.drop_index("ix_student_evidence_verified_by", table_name="student_evidence")
    op.drop_index("ix_student_evidence_verification_status", table_name="student_evidence")
    op.drop_index("ix_student_evidence_evidence_type", table_name="student_evidence")
    op.drop_index("ix_student_evidence_resource_id", table_name="student_evidence")
    op.drop_index("ix_student_evidence_user_id", table_name="student_evidence")
    op.drop_table("student_evidence")
