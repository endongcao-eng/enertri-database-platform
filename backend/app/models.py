from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .database import Base

USER_ROLES = (
    "learning_user",
    "researcher",
    "production_engineer",
    "review_expert",
    "admin",
    "system_admin",
)
TASK_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
CONFIDENTIALITY_LEVELS = ("public", "internal", "confidential", "restricted")
PARSE_STATUSES = ("pending", "parsing", "parsed", "failed", "not_applicable")

term_keywords = Table(
    "term_keywords",
    Base.metadata,
    Column("term_id", ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True),
    Column("keyword_id", ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="0")
    username = Column(String(80), nullable=False, unique=True, index=True)
    password_hash = Column(Text, nullable=False)
    role = Column(String(32), nullable=False, default="learning_user", index=True)
    display_name = Column(String(120), nullable=False)
    research_direction = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint(f"role IN {USER_ROLES}", name="ck_users_role"),)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)
    name_zh = Column(String(120), nullable=False)
    name_en = Column(String(120))
    name_ru = Column(String(120))
    description_zh = Column(Text)
    sort_order = Column(Integer, default=0, nullable=False)
    terms = relationship("Term", back_populates="category")


class Contributor(Base):
    __tablename__ = "contributors"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    research_direction = Column(String(255))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("name", "research_direction", name="uq_contributor_name_direction"),)


class Keyword(Base):
    __tablename__ = "keywords"
    id = Column(Integer, primary_key=True)
    keyword = Column(String(120), nullable=False, unique=True)


class Term(Base):
    __tablename__ = "terms"
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    zh = Column(String(255), nullable=False, index=True)
    en = Column(String(255), nullable=False, index=True)
    ru = Column(String(255))
    definition_zh_academic = Column(Text, nullable=False)
    definition_zh_popular = Column(Text)
    definition_en = Column(Text)
    application_scenario = Column(Text)
    formula_model = Column(Text)
    has_video = Column(Boolean, default=False, nullable=False)
    featured = Column(Boolean, default=False, nullable=False)
    review_status = Column(String(20), default="draft", nullable=False, index=True)
    review_comment = Column(Text)
    contributor_id = Column(Integer, ForeignKey("contributors.id", ondelete="SET NULL"))
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("review_status IN ('draft','submitted','approved')", name="ck_terms_review_status"),
        UniqueConstraint("zh", "en", name="uq_terms_zh_en"),
    )
    category = relationship("Category", back_populates="terms")
    contributor = relationship("Contributor")
    keywords = relationship("Keyword", secondary=term_keywords)
    references = relationship("TermReference", cascade="all, delete-orphan", back_populates="term")
    media_assets = relationship("MediaAsset", cascade="all, delete-orphan", back_populates="term")
    outgoing_relations = relationship("TermRelation", foreign_keys="TermRelation.term_id", cascade="all, delete-orphan")


class TermRelation(Base):
    __tablename__ = "term_relations"
    term_id = Column(Integer, ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True)
    related_term_id = Column(Integer, ForeignKey("terms.id", ondelete="CASCADE"), primary_key=True)
    relation_type = Column(String(50), default="related", nullable=False)


class TermReference(Base):
    __tablename__ = "term_references"
    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    citation = Column(Text, nullable=False)
    url = Column(Text)
    sort_order = Column(Integer, default=0, nullable=False)
    term = relationship("Term", back_populates="references")


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    media_type = Column(String(20), default="video", nullable=False)
    path = Column(Text, nullable=False)
    thumbnail_label = Column(String(60))
    thumbnail_hint = Column(Text)
    thumbnail_style = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    term = relationship("Term", back_populates="media_assets")
    __table_args__ = (CheckConstraint("media_type IN ('video','image','other')", name="ck_media_type"),)


class UserTermProgress(Base):
    __tablename__ = "user_term_progress"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    term_id = Column(Integer, ForeignKey("terms.id", ondelete="CASCADE"), nullable=False, index=True)
    is_favorite = Column(Boolean, default=False, nullable=False)
    learned_at = Column(DateTime(timezone=True))
    quiz_best_score = Column(Integer, default=0, nullable=False)
    note = Column(Text)
    last_viewed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "term_id", name="uq_user_term_progress"),)
    user = relationship("User")
    term = relationship("Term")


class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    difficulty = Column(String(20), default="入门", nullable=False)
    status = Column(String(20), default="draft", nullable=False, index=True)
    cover_label = Column(String(60))
    related_keywords = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('draft','approved')", name="ck_articles_status"),)


class AssistantJob(Base):
    """V4.0 legacy job table retained for compatibility."""
    __tablename__ = "assistant_jobs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    domain = Column(String(30), nullable=False, index=True)
    task_type = Column(String(60), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="completed", index=True)
    input_json = Column(Text)
    output_text = Column(Text)
    output_json = Column(Text)
    artifact_path = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_assistant_jobs_status"),)
    user = relationship("User")


class WorkspaceTask(Base):
    __tablename__ = "workspace_tasks"
    id = Column(Integer, primary_key=True)
    task_code = Column(String(36), nullable=False, unique=True, index=True)
    task_type = Column(String(80), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    current_step = Column(String(255))
    input_json = Column(Text)
    result_json = Column(Text)
    error_message = Column(Text)
    model_name = Column(String(120))
    model_version = Column(String(120))
    software_name = Column(String(120))
    software_version = Column(String(120))
    retry_of_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="SET NULL"), index=True)
    worker_id = Column(String(160), index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    heartbeat_at = Column(DateTime(timezone=True), index=True)
    lease_expires_at = Column(DateTime(timezone=True), index=True)
    last_claimed_at = Column(DateTime(timezone=True))
    timeout_seconds = Column(Integer, nullable=False, default=1800)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUSES}", name="ck_workspace_tasks_status"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_workspace_tasks_progress"),
    )
    user = relationship("User")
    files = relationship("TaskFile", cascade="all, delete-orphan", back_populates="task")
    events = relationship("TaskEvent", cascade="all, delete-orphan", back_populates="task", order_by="TaskEvent.id")


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"
    id = Column(Integer, primary_key=True)
    original_name = Column(String(512), nullable=False)
    storage_name = Column(String(255), nullable=False, unique=True)
    storage_path = Column(Text, nullable=False)
    file_type = Column(String(80), nullable=False)
    mime_type = Column(String(255))
    detected_mime_type = Column(String(255))
    validation_json = Column(Text)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    uploader_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="SET NULL"), index=True)
    confidentiality = Column(String(20), nullable=False, default="internal", index=True)
    parse_status = Column(String(24), nullable=False, default="pending", index=True)
    external_ai_allowed = Column(Boolean, nullable=False, default=True)
    duplicate_of_id = Column(Integer, ForeignKey("workspace_files.id", ondelete="SET NULL"))
    expires_at = Column(DateTime(timezone=True), index=True)
    deleted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint(f"confidentiality IN {CONFIDENTIALITY_LEVELS}", name="ck_workspace_files_confidentiality"),
        CheckConstraint(f"parse_status IN {PARSE_STATUSES}", name="ck_workspace_files_parse_status"),
        UniqueConstraint("uploader_id", "sha256", "deleted_at", name="uq_workspace_file_active_hash"),
    )
    uploader = relationship("User")


class TemplateFile(Base):
    __tablename__ = "template_files"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    category = Column(String(16), nullable=False, index=True)
    title = Column(String(512), nullable=False, index=True)
    uploader_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("category IN ('pdf','ppt','excel','word')", name="ck_template_files_category"),
    )
    file = relationship("WorkspaceFile")
    uploader = relationship("User")


class TaskFile(Base):
    __tablename__ = "task_files"
    task_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="CASCADE"), primary_key=True)
    file_id = Column(Integer, ForeignKey("workspace_files.id", ondelete="CASCADE"), primary_key=True)
    file_role = Column(String(20), nullable=False, default="input")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("file_role IN ('input','output','log','intermediate')", name="ck_task_files_role"),)
    task = relationship("WorkspaceTask", back_populates="files")
    file = relationship("WorkspaceFile")


class TaskEvent(Base):
    __tablename__ = "task_events"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(60), nullable=False, default="progress", index=True)
    level = Column(String(20), nullable=False, default="info")
    step = Column(String(255))
    progress = Column(Integer)
    message = Column(Text, nullable=False)
    data_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    task = relationship("WorkspaceTask", back_populates="events")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = Column(String(120), nullable=False, index=True)
    resource_type = Column(String(80), nullable=False, index=True)
    resource_id = Column(String(120), index=True)
    outcome = Column(String(20), nullable=False, default="success", index=True)
    detail_json = Column(Text)
    ip_address = Column(String(64))
    user_agent = Column(String(512))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    actor = relationship("User")


class AIUsageRecord(Base):
    __tablename__ = "ai_usage_records"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="SET NULL"), index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    provider = Column(String(80), nullable=False)
    model = Column(String(120), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost = Column(Numeric(14, 6), nullable=False, default=0)
    external = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Publication(Base):
    __tablename__ = "publications"
    id = Column(Integer, primary_key=True)
    doi = Column(String(255), unique=True, index=True)
    title = Column(String(1024), nullable=False)
    normalized_title = Column(String(1024), nullable=False, index=True)
    authors_json = Column(Text)
    institutions_json = Column(Text)
    abstract = Column(Text)
    keywords_json = Column(Text)
    journal = Column(String(512), index=True)
    year = Column(Integer, index=True)
    citation_count = Column(Integer, nullable=False, default=0)
    open_access = Column(Boolean)
    primary_source = Column(String(80), nullable=False)
    landing_page_url = Column(Text)
    fulltext_url = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PublicationSource(Base):
    __tablename__ = "publication_sources"
    id = Column(Integer, primary_key=True)
    publication_id = Column(Integer, ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True)
    source_name = Column(String(80), nullable=False, index=True)
    source_record_id = Column(String(512), nullable=False)
    raw_json = Column(Text)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("source_name", "source_record_id", name="uq_publication_source_record"),)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    scope_type = Column(String(32), nullable=False, default="personal", index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    description = Column(Text)
    allow_team_search = Column(Boolean, nullable=False, default=False)
    allow_ai = Column(Boolean, nullable=False, default=True)
    allow_export = Column(Boolean, nullable=False, default=True)
    retain_original = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("scope_type IN ('personal','group','project','enterprise','public_terms')", name="ck_knowledge_bases_scope"),)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("workspace_files.id", ondelete="SET NULL"), index=True)
    publication_id = Column(Integer, ForeignKey("publications.id", ondelete="SET NULL"), index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    title = Column(String(512), nullable=False)
    source_type = Column(String(80), nullable=False, default="upload")
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    page_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column(Text)
    structure_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class KnowledgePage(Base):
    __tablename__ = "knowledge_pages"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False, default="")
    extraction_method = Column(String(32), nullable=False, default="text")
    ocr_used = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(Text)
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_knowledge_page_number"),)


class KnowledgeTable(Base):
    __tablename__ = "knowledge_tables"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    table_number = Column(String(80), nullable=False)
    page_number = Column(Integer, nullable=False, index=True)
    title = Column(Text)
    data_json = Column(Text, nullable=False)
    markdown = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeFigure(Base):
    __tablename__ = "knowledge_figures"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    figure_number = Column(String(80), nullable=False)
    page_number = Column(Integer, nullable=False, index=True)
    caption = Column(Text)
    image_path = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    page_start = Column(Integer)
    page_end = Column(Integer)
    section = Column(String(255))
    embedding_model = Column(String(120))
    embedding_json = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_index"),)


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=False, unique=True, index=True)
    name_zh = Column(String(255), nullable=False)
    name_en = Column(String(255))
    domain = Column(String(120), nullable=False, default="general", index=True)
    node_type = Column(String(40), nullable=False, default="concept")
    description = Column(Text)
    linked_term_id = Column(Integer, ForeignKey("terms.id", ondelete="SET NULL"), index=True)
    level_scale = Column(Integer, nullable=False, default=5)
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("node_type IN ('concept','theory','method','tool','practice')", name="ck_knowledge_nodes_type"),
        CheckConstraint("status IN ('active','draft','archived')", name="ck_knowledge_nodes_status"),
        CheckConstraint("level_scale BETWEEN 1 AND 10", name="ck_knowledge_nodes_level_scale"),
    )


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    id = Column(Integer, primary_key=True)
    source_node_id = Column(Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(40), nullable=False, default="related")
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    rationale = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "relation_type", name="uq_knowledge_relation"),
        CheckConstraint("relation_type IN ('prerequisite','part_of','related','enables')", name="ck_knowledge_relation_type"),
    )


class Capability(Base):
    __tablename__ = "capabilities"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=False, unique=True, index=True)
    name_zh = Column(String(255), nullable=False)
    name_en = Column(String(255))
    category = Column(String(64), nullable=False, index=True)
    description = Column(Text)
    level_scale = Column(Integer, nullable=False, default=5)
    rubric_json = Column(Text)
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("category IN ('theory','methodology','computation','experiment','research','communication','project')", name="ck_capabilities_category"),
        CheckConstraint("status IN ('active','draft','archived')", name="ck_capabilities_status"),
        CheckConstraint("level_scale BETWEEN 1 AND 10", name="ck_capabilities_level_scale"),
    )


class CapabilityKnowledgeLink(Base):
    __tablename__ = "capability_knowledge_links"
    id = Column(Integer, primary_key=True)
    capability_id = Column(Integer, ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_node_id = Column(Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False, default="requires")
    required_level = Column(Numeric(4, 2), nullable=False, default=1.0)
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    rationale = Column(Text)
    __table_args__ = (
        UniqueConstraint("capability_id", "knowledge_node_id", "relation_type", name="uq_capability_knowledge_link"),
        CheckConstraint("relation_type IN ('requires','supports')", name="ck_capability_knowledge_relation_type"),
    )


class LearningResource(Base):
    __tablename__ = "learning_resources"
    id = Column(Integer, primary_key=True)
    code = Column(String(120), nullable=False, unique=True, index=True)
    resource_type = Column(String(40), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    subtitle = Column(String(512))
    discipline = Column(String(160), index=True)
    provider = Column(String(255))
    description = Column(Text)
    metadata_json = Column(Text)
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("resource_type IN ('course','book','project_task')", name="ck_learning_resources_type"),
        CheckConstraint("status IN ('active','draft','archived')", name="ck_learning_resources_status"),
    )


class ResourceKnowledgeLink(Base):
    __tablename__ = "resource_knowledge_links"
    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_node_id = Column(Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    coverage_level = Column(Numeric(4, 2), nullable=False, default=1.0)
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    evidence_strength = Column(Numeric(6, 3), nullable=False, default=0.5)
    note = Column(Text)
    __table_args__ = (UniqueConstraint("resource_id", "knowledge_node_id", name="uq_resource_knowledge_link"),)


class ResourceCapabilityLink(Base):
    __tablename__ = "resource_capability_links"
    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False, index=True)
    capability_id = Column(Integer, ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False, index=True)
    contribution_level = Column(Numeric(4, 2), nullable=False, default=1.0)
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    evidence_strength = Column(Numeric(6, 3), nullable=False, default=0.5)
    note = Column(Text)
    __table_args__ = (UniqueConstraint("resource_id", "capability_id", name="uq_resource_capability_link"),)


class StudentEvidence(Base):
    __tablename__ = "student_evidence"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id = Column(Integer, ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type = Column(String(40), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    grade_percent = Column(Numeric(5, 2))
    completion_ratio = Column(Numeric(6, 4), nullable=False, default=1.0)
    independence_ratio = Column(Numeric(6, 4))
    quality_rating = Column(Numeric(4, 2))
    mentor_rating = Column(Numeric(4, 2))
    verification_status = Column(String(24), nullable=False, default="self_reported", index=True)
    verified_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    verification_note = Column(Text)
    occurred_on = Column(Date)
    notes = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("evidence_type IN ('course_grade','book_reading','project_participation')", name="ck_student_evidence_type"),
        CheckConstraint("verification_status IN ('self_reported','pending','verified','rejected')", name="ck_student_evidence_verification"),
        CheckConstraint("grade_percent IS NULL OR (grade_percent >= 0 AND grade_percent <= 100)", name="ck_student_evidence_grade"),
        CheckConstraint("completion_ratio >= 0 AND completion_ratio <= 1", name="ck_student_evidence_completion"),
        CheckConstraint("independence_ratio IS NULL OR (independence_ratio >= 0 AND independence_ratio <= 1)", name="ck_student_evidence_independence"),
        CheckConstraint("quality_rating IS NULL OR (quality_rating >= 0 AND quality_rating <= 5)", name="ck_student_evidence_quality"),
        CheckConstraint("mentor_rating IS NULL OR (mentor_rating >= 0 AND mentor_rating <= 5)", name="ck_student_evidence_mentor"),
    )


class DevelopmentGoal(Base):
    __tablename__ = "development_goals"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    goal_type = Column(String(32), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(Text)
    target_project_id = Column(Integer, ForeignKey("research_projects.id", ondelete="SET NULL"), index=True)
    requirements_json = Column(Text)
    status = Column(String(24), nullable=False, default="active", index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("goal_type IN ('student_growth','teacher_research_direction')", name="ck_development_goals_type"),
        CheckConstraint("status IN ('active','archived')", name="ck_development_goals_status"),
    )


class DevelopmentPlanItem(Base):
    __tablename__ = "development_plan_items"
    id = Column(Integer, primary_key=True)
    goal_id = Column(Integer, ForeignKey("development_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(String(32), nullable=False)
    source_resource_id = Column(Integer, ForeignKey("learning_resources.id", ondelete="SET NULL"))
    source_publication_id = Column(Integer, ForeignKey("publications.id", ondelete="SET NULL"))
    source_project_id = Column(Integer, ForeignKey("research_projects.id", ondelete="SET NULL"))
    title = Column(String(1024), nullable=False)
    phase = Column(String(32), nullable=False, default="planned")
    priority_score = Column(Numeric(6, 2), nullable=False, default=0)
    status = Column(String(24), nullable=False, default="planned", index=True)
    progress_percent = Column(Integer, nullable=False, default=0)
    rationale = Column(Text)
    gap_targets_json = Column(Text)
    completion_note = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("item_type IN ('course','book','project_task','publication','research_project')", name="ck_development_plan_items_type"),
        CheckConstraint("status IN ('planned','in_progress','completed','skipped')", name="ck_development_plan_items_status"),
        CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="ck_development_plan_items_progress"),
        UniqueConstraint("goal_id", "item_type", "source_resource_id", "source_publication_id", "source_project_id", name="uq_development_plan_source"),
    )


class DevelopmentSnapshot(Base):
    __tablename__ = "development_snapshots"
    id = Column(Integer, primary_key=True)
    goal_id = Column(Integer, ForeignKey("development_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_type = Column(String(24), nullable=False, default="recalculated")
    match_score = Column(Numeric(6, 2), nullable=False, default=0)
    capability_fit = Column(Numeric(6, 2), nullable=False, default=0)
    knowledge_fit = Column(Numeric(6, 2), nullable=False, default=0)
    evidence_confidence = Column(Numeric(6, 2), nullable=False, default=0)
    critical_gap_count = Column(Integer, nullable=False, default=0)
    snapshot_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("snapshot_type IN ('baseline','recalculated','completion')", name="ck_development_snapshots_type"),)


class ResearchProject(Base):
    __tablename__ = "research_projects"
    id = Column(Integer, primary_key=True)
    title = Column(String(512), nullable=False)
    description = Column(Text)
    research_direction = Column(String(255))
    status = Column(String(24), nullable=False, default="draft", index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','archived')", name="ck_research_projects_status"),
    )


class ProjectCapabilityRequirement(Base):
    __tablename__ = "project_capability_requirements"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    capability_id = Column(Integer, ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False, index=True)
    required_level = Column(Numeric(4, 2), nullable=False, default=3.0)
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    is_critical = Column(Boolean, nullable=False, default=False)
    note = Column(Text)
    __table_args__ = (
        UniqueConstraint("project_id", "capability_id", name="uq_project_capability_requirement"),
        CheckConstraint("required_level >= 0 AND required_level <= 5", name="ck_project_capability_required_level"),
        CheckConstraint("weight > 0", name="ck_project_capability_weight"),
    )


class ProjectKnowledgeRequirement(Base):
    __tablename__ = "project_knowledge_requirements"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_node_id = Column(Integer, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    required_level = Column(Numeric(4, 2), nullable=False, default=3.0)
    weight = Column(Numeric(6, 3), nullable=False, default=1.0)
    is_critical = Column(Boolean, nullable=False, default=False)
    note = Column(Text)
    __table_args__ = (
        UniqueConstraint("project_id", "knowledge_node_id", name="uq_project_knowledge_requirement"),
        CheckConstraint("required_level >= 0 AND required_level <= 5", name="ck_project_knowledge_required_level"),
        CheckConstraint("weight > 0", name="ck_project_knowledge_weight"),
    )


class SimulationJob(Base):
    __tablename__ = "simulation_jobs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_task_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="SET NULL"), index=True)
    name = Column(String(255), nullable=False)
    software = Column(String(40), nullable=False, index=True)
    software_version = Column(String(120))
    status = Column(String(20), nullable=False, default="prepared", index=True)
    parameters_json = Column(Text, nullable=False)
    workdir = Column(Text, nullable=False)
    package_path = Column(Text)
    result_json = Column(Text)
    runner_pid = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('prepared','queued','running','completed','failed','cancelled')", name="ck_simulation_jobs_status"),)
    user = relationship("User")


class SimulationArtifact(Base):
    __tablename__ = "simulation_artifacts"
    id = Column(Integer, primary_key=True)
    simulation_job_id = Column(Integer, ForeignKey("simulation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("workspace_tasks.id", ondelete="SET NULL"), index=True)
    file_id = Column(Integer, ForeignKey("workspace_files.id", ondelete="SET NULL"), index=True)
    artifact_type = Column(String(80), nullable=False)
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QuizSession(Base):
    __tablename__ = "quiz_sessions"
    token_hash = Column(String(64), primary_key=True)
    term_id = Column(Integer, ForeignKey("terms.id", ondelete="CASCADE"), nullable=False)
    answers_json = Column(Text, nullable=False)
    expires_at = Column(Integer, nullable=False, index=True)


class SafetyLock(Base):
    __tablename__="safety_locks"
    id=Column(Integer,primary_key=True)
    value=Column(Integer,nullable=False)

class RateBucket(Base):
    __tablename__="rate_buckets"
    key=Column(String(64),primary_key=True)
    count=Column(Integer,nullable=False)
    expires_at=Column(Integer,nullable=False,index=True)

class AIBudgetReservation(Base):
    __tablename__="ai_budget_reservations"
    id=Column(String(36),primary_key=True)
    user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    day=Column(String(10),nullable=False)
    reserved_usd_micros=Column(Integer,nullable=False)
    expires_at=Column(Integer,nullable=False)
    status=Column(String(24),nullable=False)
    usage_json=Column(Text)
