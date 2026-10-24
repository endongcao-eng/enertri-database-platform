"""V4.2 literature and paper knowledge system.

Revision ID: v4_2_knowledge_system
Revises: v4_1_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "v4_2_knowledge_system"
down_revision = "v4_1_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_tasks", recreate="auto") as batch:
        batch.add_column(sa.Column("worker_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="1800"))
        batch.create_index("ix_workspace_tasks_worker_id", ["worker_id"], unique=False)
        batch.create_index("ix_workspace_tasks_heartbeat_at", ["heartbeat_at"], unique=False)
        batch.create_index("ix_workspace_tasks_lease_expires_at", ["lease_expires_at"], unique=False)

    with op.batch_alter_table("workspace_files", recreate="auto") as batch:
        batch.add_column(sa.Column("detected_mime_type", sa.String(255), nullable=True))
        batch.add_column(sa.Column("validation_json", sa.Text(), nullable=True))

    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doi", sa.String(255), nullable=True),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("normalized_title", sa.String(1024), nullable=False),
        sa.Column("authors_json", sa.Text()),
        sa.Column("institutions_json", sa.Text()),
        sa.Column("abstract", sa.Text()),
        sa.Column("keywords_json", sa.Text()),
        sa.Column("journal", sa.String(512)),
        sa.Column("year", sa.Integer()),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_access", sa.Boolean()),
        sa.Column("primary_source", sa.String(80), nullable=False),
        sa.Column("landing_page_url", sa.Text()),
        sa.Column("fulltext_url", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("doi", name="uq_publications_doi"),
    )
    for name, cols in [
        ("ix_publications_doi", ["doi"]),
        ("ix_publications_normalized_title", ["normalized_title"]),
        ("ix_publications_journal", ["journal"]),
        ("ix_publications_year", ["year"]),
    ]:
        op.create_index(name, "publications", cols)

    op.create_table(
        "publication_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("publication_id", sa.Integer(), sa.ForeignKey("publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_name", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(512), nullable=False),
        sa.Column("raw_json", sa.Text()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_name", "source_record_id", name="uq_publication_source_record"),
    )
    op.create_index("ix_publication_sources_publication_id", "publication_sources", ["publication_id"])
    op.create_index("ix_publication_sources_source_name", "publication_sources", ["source_name"])

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scope_type", sa.String(32), nullable=False, server_default="personal"),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("description", sa.Text()),
        sa.Column("allow_team_search", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_ai", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_export", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retain_original", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("scope_type IN ('personal','group','project','enterprise','public_terms')", name="ck_knowledge_bases_scope"),
    )
    op.create_index("ix_knowledge_bases_scope_type", "knowledge_bases", ["scope_type"])
    op.create_index("ix_knowledge_bases_owner_user_id", "knowledge_bases", ["owner_user_id"])

    with op.batch_alter_table("knowledge_documents", recreate="auto") as batch:
        batch.add_column(sa.Column("publication_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("knowledge_base_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("structure_json", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_knowledge_documents_publication", "publications", ["publication_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_knowledge_documents_knowledge_base", "knowledge_bases", ["knowledge_base_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_knowledge_documents_publication_id", ["publication_id"], unique=False)
        batch.create_index("ix_knowledge_documents_knowledge_base_id", ["knowledge_base_id"], unique=False)

    op.create_table(
        "knowledge_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("extraction_method", sa.String(32), nullable=False, server_default="text"),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.Text()),
        sa.UniqueConstraint("document_id", "page_number", name="uq_knowledge_page_number"),
    )
    op.create_index("ix_knowledge_pages_document_id", "knowledge_pages", ["document_id"])

    op.create_table(
        "knowledge_tables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_number", sa.String(80), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_tables_document_id", "knowledge_tables", ["document_id"])
    op.create_index("ix_knowledge_tables_page_number", "knowledge_tables", ["page_number"])

    op.create_table(
        "knowledge_figures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("figure_number", sa.String(80), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("image_path", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_figures_document_id", "knowledge_figures", ["document_id"])
    op.create_index("ix_knowledge_figures_page_number", "knowledge_figures", ["page_number"])

    with op.batch_alter_table("knowledge_chunks", recreate="auto") as batch:
        batch.add_column(sa.Column("page_start", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("page_end", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("section", sa.String(255), nullable=True))
        batch.add_column(sa.Column("embedding_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_chunks", recreate="auto") as batch:
        batch.drop_column("embedding_json")
        batch.drop_column("section")
        batch.drop_column("page_end")
        batch.drop_column("page_start")
    op.drop_table("knowledge_figures")
    op.drop_table("knowledge_tables")
    op.drop_table("knowledge_pages")
    with op.batch_alter_table("knowledge_documents", recreate="auto") as batch:
        batch.drop_index("ix_knowledge_documents_knowledge_base_id")
        batch.drop_index("ix_knowledge_documents_publication_id")
        batch.drop_constraint("fk_knowledge_documents_knowledge_base", type_="foreignkey")
        batch.drop_constraint("fk_knowledge_documents_publication", type_="foreignkey")
        batch.drop_column("structure_json")
        batch.drop_column("page_count")
        batch.drop_column("knowledge_base_id")
        batch.drop_column("publication_id")
    op.drop_table("knowledge_bases")
    op.drop_table("publication_sources")
    op.drop_table("publications")
    with op.batch_alter_table("workspace_files", recreate="auto") as batch:
        batch.drop_column("validation_json")
        batch.drop_column("detected_mime_type")
    with op.batch_alter_table("workspace_tasks", recreate="auto") as batch:
        batch.drop_index("ix_workspace_tasks_lease_expires_at")
        batch.drop_index("ix_workspace_tasks_heartbeat_at")
        batch.drop_index("ix_workspace_tasks_worker_id")
        batch.drop_column("timeout_seconds")
        batch.drop_column("last_claimed_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("heartbeat_at")
        batch.drop_column("attempt_count")
        batch.drop_column("worker_id")
