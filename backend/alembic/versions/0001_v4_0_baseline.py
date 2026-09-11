"""V4.0 schema baseline.

Revision ID: v4_0_baseline
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_0_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="student"),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("research_direction", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('student','admin')", name="ck_users_role"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name_zh", sa.String(120), nullable=False),
        sa.Column("name_en", sa.String(120)),
        sa.Column("name_ru", sa.String(120)),
        sa.Column("description_zh", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "contributors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("research_direction", sa.String(255)),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "research_direction", name="uq_contributor_name_direction"),
    )
    op.create_table("keywords", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("keyword", sa.String(120), nullable=False, unique=True))
    op.create_table(
        "terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("zh", sa.String(255), nullable=False),
        sa.Column("en", sa.String(255), nullable=False),
        sa.Column("ru", sa.String(255)),
        sa.Column("definition_zh_academic", sa.Text(), nullable=False),
        sa.Column("definition_zh_popular", sa.Text()),
        sa.Column("definition_en", sa.Text()),
        sa.Column("application_scenario", sa.Text()),
        sa.Column("formula_model", sa.Text()),
        sa.Column("has_video", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("review_comment", sa.Text()),
        sa.Column("contributor_id", sa.Integer(), sa.ForeignKey("contributors.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("review_status IN ('draft','submitted','approved')", name="ck_terms_review_status"),
        sa.UniqueConstraint("zh", "en", name="uq_terms_zh_en"),
    )
    for name, cols in [("ix_terms_category_id", ["category_id"]), ("ix_terms_zh", ["zh"]), ("ix_terms_en", ["en"]), ("ix_terms_review_status", ["review_status"])]:
        op.create_index(name, "terms", cols)
    op.create_table(
        "term_keywords",
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("keyword_id", sa.Integer(), sa.ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "term_relations",
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("related_term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("relation_type", sa.String(50), nullable=False, server_default="related"),
    )
    op.create_table(
        "term_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("citation", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_type", sa.String(20), nullable=False, server_default="video"),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("thumbnail_label", sa.String(60)),
        sa.Column("thumbnail_hint", sa.Text()),
        sa.Column("thumbnail_style", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("media_type IN ('video','image','other')", name="ck_media_type"),
    )
    op.create_table(
        "user_term_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term_id", sa.Integer(), sa.ForeignKey("terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("learned_at", sa.DateTime(timezone=True)),
        sa.Column("quiz_best_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "term_id", name="uq_user_term_progress"),
    )
    op.create_index("ix_user_term_progress_user_id", "user_term_progress", ["user_id"])
    op.create_index("ix_user_term_progress_term_id", "user_term_progress", ["term_id"])
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False, server_default="入门"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("cover_label", sa.String(60)),
        sa.Column("related_keywords", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','approved')", name="ck_articles_status"),
    )
    op.create_index("ix_articles_title", "articles", ["title"])
    op.create_index("ix_articles_status", "articles", ["status"])
    op.create_table(
        "assistant_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(30), nullable=False),
        sa.Column("task_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("input_json", sa.Text()),
        sa.Column("output_text", sa.Text()),
        sa.Column("output_json", sa.Text()),
        sa.Column("artifact_path", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_assistant_jobs_status"),
    )
    for col in ["user_id", "domain", "task_type", "status"]:
        op.create_index(f"ix_assistant_jobs_{col}", "assistant_jobs", [col])
    op.create_table(
        "simulation_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("software", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="prepared"),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("workdir", sa.Text(), nullable=False),
        sa.Column("package_path", sa.Text()),
        sa.Column("result_json", sa.Text()),
        sa.Column("runner_pid", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('prepared','queued','running','completed','failed')", name="ck_simulation_jobs_status"),
    )
    for col in ["user_id", "software", "status"]:
        op.create_index(f"ix_simulation_jobs_{col}", "simulation_jobs", [col])


def downgrade() -> None:
    for table in ["simulation_jobs", "assistant_jobs", "articles", "user_term_progress", "media_assets", "term_references", "term_relations", "term_keywords", "terms", "keywords", "contributors", "categories", "users"]:
        op.drop_table(table)
