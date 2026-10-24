from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

ReviewStatus = str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    display_name: str
    research_direction: Optional[str] = None
    must_change_password: bool = False


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class CategoryBase(BaseModel):
    code: str
    name_zh: str
    name_en: Optional[str] = None
    name_ru: Optional[str] = None
    description_zh: Optional[str] = None
    sort_order: int = 0


class CategoryCreate(CategoryBase):
    pass


class CategoryOut(CategoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TermBase(BaseModel):
    category_id: Optional[int] = None
    zh: str
    en: str
    ru: Optional[str] = None
    definition_zh_academic: str
    definition_zh_popular: Optional[str] = None
    definition_en: Optional[str] = None
    application_scenario: Optional[str] = None
    formula_model: Optional[str] = None
    has_video: bool = False
    featured: bool = False
    review_status: ReviewStatus = Field(default="draft", pattern="^(draft|submitted|approved)$")
    review_comment: Optional[str] = None
    contributor_name: Optional[str] = None
    contributor_research_direction: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    related_term_ids: List[int] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    video_path: Optional[str] = None
    thumbnail_label: Optional[str] = None
    thumbnail_hint: Optional[str] = None
    thumbnail_style: Optional[str] = None


class TermCreate(TermBase):
    pass


class TermUpdate(TermBase):
    pass


class ReviewRequest(BaseModel):
    review_status: ReviewStatus = Field(pattern="^(draft|submitted|approved)$")
    review_comment: Optional[str] = None


class TermOut(TermBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: Optional[CategoryOut] = None
    contributor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: List[str] = Field(default_factory=list)



class ProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_favorite: Optional[bool] = None
    learned: Optional[bool] = None
    note: Optional[str] = None


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    term_id: int
    is_favorite: bool = False
    learned_at: Optional[datetime] = None
    quiz_best_score: int = 0
    note: Optional[str] = None
    last_viewed_at: Optional[datetime] = None


class ArticleBase(BaseModel):
    title: str
    summary: str
    content: str
    difficulty: str = "入门"
    status: str = Field(default="draft", pattern="^(draft|approved)$")
    cover_label: Optional[str] = None
    related_keywords: List[str] = Field(default_factory=list)


class ArticleCreate(ArticleBase):
    pass


class ArticleUpdate(ArticleBase):
    pass


class ArticleOut(ArticleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class QuizOption(BaseModel):
    id: str
    text: str


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: List[QuizOption]


class QuizOut(BaseModel):
    term_id: int
    title: str
    quiz_token: str
    questions: List[QuizQuestion]


class QuizSubmitRequest(BaseModel):
    quiz_token: str
    answers: dict[str, str]


class QuizQuestionResult(BaseModel):
    id: str
    selected_answer: Optional[str] = None
    correct_answer: str
    correct: bool
    explanation: str


class QuizSubmitResult(BaseModel):
    score: int
    correct_count: int
    total: int
    best_score: Optional[int] = None
    results: List[QuizQuestionResult] = Field(default_factory=list)


class LiteratureSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    year_from: Optional[int] = Field(default=None, ge=1900, le=2100)
    year_to: Optional[int] = Field(default=None, ge=1900, le=2100)
    open_access: Optional[bool] = None
    language: Optional[str] = Field(default=None, max_length=20)
    sort: str = "relevance_score:desc"
    limit: int = Field(default=20, ge=1, le=100)


class HotspotRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    recent_years: int = Field(default=2, ge=1, le=10)
    comparison_years: int = Field(default=2, ge=1, le=10)
    limit: int = Field(default=20, ge=1, le=50)


class WritingRequest(BaseModel):
    task_type: str = Field(pattern="^(literature_review|academic_report|grant_proposal|academic_ppt|production_report)$")
    title: str = Field(min_length=2, max_length=255)
    instructions: Optional[str] = Field(default=None, max_length=10000)
    source_text: Optional[str] = Field(default=None, max_length=100000)
    literature: List[dict] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
    output_format: str = Field(default="markdown", pattern="^(markdown|docx|pptx)$")


class WeldingRequest(BaseModel):
    material_name: Optional[str] = None
    base_material: Optional[str] = None
    material_group: str = "carbon_low_alloy_steel"
    composition: dict[str, float] = Field(default_factory=dict)
    thickness_mm: float = Field(default=0, ge=0, le=2000)
    structure: Optional[str] = None
    joint_type: str = "butt"
    position: str = "flat"
    process: Optional[str] = None
    hydrogen_level: str = "low"
    service_condition: Optional[str] = None
    defect_type: Optional[str] = None
    observations: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class TelemetryBatchRequest(BaseModel):
    """来自焊机、PLC、DAQ 或边缘网关的一批时序采样。

    每个 sample 可直接放 current_a/voltage_v/travel_speed_mm_s 等字段，
    也可放在 values 字典中。timestamp_ms 或 time_s 用于估算采样率。
    """
    session_id: str = Field(min_length=1, max_length=120)
    process: Optional[str] = Field(default=None, max_length=80)
    samples: List[dict] = Field(min_length=2, max_length=20000)
    metadata: dict = Field(default_factory=dict)
    known_quality: Optional[str] = Field(default=None, max_length=120)


class SimulationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    software: str = Field(pattern="^(hypermesh|ansys_mapdl|ansys_fluent|marc|flow3d)$")
    parameters: dict = Field(default_factory=dict)


class AssistantJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain: str
    task_type: str
    title: str
    status: str
    output_text: Optional[str] = None
    output_json: Optional[dict] = None
    artifact_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SimulationJobOut(BaseModel):
    id: int
    name: str
    software: str
    status: str
    parameters: dict
    package_url: Optional[str] = None
    result: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
