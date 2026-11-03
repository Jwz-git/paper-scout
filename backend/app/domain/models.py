from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    NEEDS_INPUT = "needs_input"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RunStage(str, Enum):
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    SEARCHING = "searching"
    SCREENING = "screening"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    ASSESSING = "assessing"
    SYNTHESIZING = "synthesizing"
    REPORTING = "reporting"


class MissingReason(str, Enum):
    NOT_AVAILABLE = "not_available"
    NOT_READ = "not_read"
    NOT_FOUND = "not_found"
    PARSE_FAILED = "parse_failed"
    NOT_APPLICABLE = "not_applicable"


class SourceType(str, Enum):
    METADATA = "metadata"
    ABSTRACT = "abstract"
    FULLTEXT = "fulltext"


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic: str = Field(min_length=1, max_length=2000)
    start_year: Optional[int] = Field(default=None, ge=1800, le=utc_now().year + 1, strict=True)
    end_year: Optional[int] = Field(default=None, ge=1800, le=utc_now().year + 1, strict=True)
    focus_dimensions: List[str] = Field(default_factory=list, max_length=12)
    output_requirements: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("focus_dimensions")
    @classmethod
    def clean_dimensions(cls, values):
        values = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in values):
            raise ValueError("关注维度必须为非空文本且不超过200字符")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def valid_years(self):
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("起始年份不能大于截止年份")
        return self


class Task(BaseModel):

    id: str
    topic: str
    title: Optional[str] = None
    deleted_at: Optional[datetime] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    focus_dimensions: List[str] = Field(default_factory=list)
    output_requirements: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Run(BaseModel):
    id: str
    task_id: str
    initial_topic: str
    status: RunStatus = RunStatus.QUEUED
    stage: RunStage = RunStage.UNDERSTANDING
    current_round: int = 1
    max_rounds: int = 3
    max_calls: int = 20
    total_calls: int = 0
    total_execution_seconds: float = 0.0
    max_seconds: float = 900.0
    initial_input: Optional[TaskInput] = None
    current_input: Optional[TaskInput] = None
    queries: List[str] = Field(default_factory=list)
    subproblems: List[str] = Field(default_factory=list)
    query_index: int = 0
    pdf_index: int = 0
    analysis_index: int = 0
    analysis_revision: int = 1
    scope_history: Dict[int, TaskInput] = Field(default_factory=dict)
    query_targets: Dict[str, List[str]] = Field(default_factory=dict)
    max_papers: int = 12
    min_papers: int = 6
    min_per_subproblem: int = 2
    min_field_completeness: float = 0.6
    assessment_rule: str = "coverage-v1"
    last_progress: List[int] = Field(default_factory=list)
    sufficient: bool = False
    pending_sections: List[dict] = Field(default_factory=list)
    synthesis_truncated: bool = False
    pdf_attempted: List[str] = Field(default_factory=list)
    no_new_rounds: int = 0
    papers_before_round: int = 0
    gaps: List[str] = Field(default_factory=list)
    model_calls: int = 0
    token_usage: Dict[str, Optional[int]] = Field(default_factory=lambda: {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None})
    stop_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class RunMessage(BaseModel):
    id: str
    run_id: str
    content: str
    status: str = "pending"
    impact_summary: Optional[str] = None
    proposed_scope: Optional[TaskInput] = None
    created_at: datetime = Field(default_factory=utc_now)


class Paper(BaseModel):
    id: str
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    source: str = "arxiv"
    source_id: str
    url: str
    pdf_url: Optional[str] = None
    abstract: Optional[str] = None
    primary_category: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=utc_now)


class Event(BaseModel):
    id: str
    run_id: str
    stage: RunStage
    category: str
    message: str
    created_at: datetime = Field(default_factory=utc_now)


class SearchQuery(BaseModel):
    id: str
    run_id: str
    round_number: int
    query_text: str
    raw_query: Optional[str] = None
    subproblems: List[str] = Field(default_factory=list)
    analysis_revision: int = 1
    source: str = "arxiv"
    total_results: int = 0
    error_category: Optional[str] = None
    executed_at: datetime = Field(default_factory=utc_now)


class SourceText(BaseModel):
    id: str
    paper_id: str
    source_type: SourceType
    source_url: Optional[str] = None
    page_number: Optional[int] = None
    content: str
    status: str = "ok"
    fetched_at: datetime = Field(default_factory=utc_now)


class Evidence(BaseModel):
    id: str
    source_text_id: str
    paper_id: str
    page_number: Optional[int] = None
    quote: str
    location_start: Optional[int] = None
    location_end: Optional[int] = None


class Extraction(BaseModel):
    id: str
    run_id: str
    paper_id: str
    field_name: str
    value: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    missing_reason: Optional[MissingReason] = None
    is_inference: bool = False
    origin: Literal["author", "inference", "user"] = "author"
    note: str = ""


class ReadRange(BaseModel):
    source_text_id: str
    source_type: SourceType
    page_number: Optional[int] = None
    location_start: int
    location_end: int
    original_length: int


class ReportSource(ReadRange):
    paper_id: str
    status: str
    source_url: Optional[str] = None


class PaperSelection(BaseModel):
    paper_id: str
    analysis_revision: int
    relevant: bool
    reason: str
    subproblems: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    reviewed: bool = True


class Experiment(BaseModel):
    id: str
    paper_id: str
    dataset: Optional[str] = None
    dataset_version: Optional[str] = None
    split: Optional[str] = None
    metric: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    direction: Optional[Literal["higher", "lower"]] = None
    protocol: Optional[str] = None
    compute: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


class PaperAnalysis(BaseModel):
    id: str
    run_id: str
    paper_id: str
    analysis_revision: int
    round_number: int
    status: Literal["completed", "failed", "unavailable"]
    focus_dimensions: List[str] = Field(default_factory=list)
    ranges: List[ReadRange] = Field(default_factory=list)
    fields: List[Extraction] = Field(default_factory=list)
    experiments: List[Experiment] = Field(default_factory=list)
    reused_from: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class Comparison(BaseModel):
    left_paper_id: str
    right_paper_id: str
    left_experiment_id: str
    right_experiment_id: str
    status: Literal["comparable", "not_comparable", "insufficient"]
    reasons: List[str]
    evidence_ids: List[str]
    metric: Optional[str] = None
    left_value: Optional[str] = None
    right_value: Optional[str] = None


class Assessment(BaseModel):
    id: str
    run_id: str
    round_number: int
    subproblem_coverage: Dict[str, float] = Field(default_factory=dict)
    field_completeness: Dict[str, float] = Field(default_factory=dict)
    gaps: List[str] = Field(default_factory=list)
    decision: str = "continue"
    analysis_revision: int = 1
    rule: str = "coverage-v1"
    supporting_papers: Dict[str, List[str]] = Field(default_factory=dict)
    field_counts: Dict[str, List[int]] = Field(default_factory=dict)
    paper_groups: Dict[str, str] = Field(default_factory=dict)
    duplicate_candidates: List[List[str]] = Field(default_factory=list)
    comparisons: List[Comparison] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    sufficient: bool = False


class ReportClaim(BaseModel):
    text: str
    evidence_ids: List[str]
    origin: Literal["author", "inference", "user"] = "inference"


class ReportSection(BaseModel):
    title: str
    claims: List[ReportClaim]


class ReportDocument(BaseModel):
    analysis_revision: int
    scope: TaskInput
    papers: List[Paper]
    queries: List[SearchQuery]
    selections: List[PaperSelection]
    analyses: List[PaperAnalysis]
    assessment: Optional[Assessment] = None
    sections: List[ReportSection] = Field(default_factory=list)
    evidence: List[Evidence]
    sources: List[ReportSource]
    total_calls: int
    model_calls: int
    token_usage: Dict[str, Optional[int]]
    semantic_review: str = "未进行人工语义复核；定位校验不证明主张成立"
    execution_seconds: float = 0.0
    limits: Dict[str, float] = Field(default_factory=dict)


class Report(BaseModel):
    id: str
    run_id: str
    title: str
    content_markdown: str
    document: Optional[ReportDocument] = None
    gaps: List[str] = Field(default_factory=list)
    stop_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
