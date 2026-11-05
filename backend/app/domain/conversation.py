"""持久化对话契约；显式模式只是自然对话路由的覆盖项。"""
from datetime import datetime
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.domain.models import Run, SourceType, Task, TaskInput, utc_now

ConversationMode = Literal["auto", "research", "ask", "pause", "resume", "cancel"]
ChatAction = Literal["research", "answer", "clarify", "pause", "resume", "cancel"]


class ConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)
    mode: ConversationMode = "auto"
    request_id: str = Field(min_length=1, max_length=200)


class ConversationCreateRequest(ConversationMessageRequest):
    content: str = Field(min_length=1, max_length=2000)


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text_id: str
    paper_id: str
    run_id: str
    source_type: SourceType
    source_url: Optional[str] = None
    page_number: Optional[int] = Field(default=None, ge=1, strict=True)
    quote: str = Field(min_length=1, max_length=4000)
    location_start: int = Field(ge=0, strict=True)
    location_end: int = Field(gt=0, strict=True)


class ChatMessage(BaseModel):
    id: str
    task_id: str
    role: Literal["user", "assistant"]
    content: str
    status: Literal["queued", "processing", "completed", "failed", "interrupted"]
    action: Optional[ChatAction] = None
    run_id: Optional[str] = None
    citations: List[ChatCitation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    error_category: Optional[str] = None


class ConversationUsage(BaseModel):
    model_calls: int = 0
    total_execution_seconds: float = 0.0
    token_usage: Dict[str, Optional[int]] = Field(default_factory=lambda: {
        "prompt_tokens": None, "completion_tokens": None, "total_tokens": None})


class ConversationView(BaseModel):
    task: Task
    messages: List[ChatMessage]
    runs: List[Run]
    usage: ConversationUsage
    busy: bool
    model_configured: bool


class DialogueDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: ChatAction
    content: str = Field(min_length=1, max_length=12000)
    task_input: Optional[TaskInput] = None
    run_id: Optional[str] = None
    citations: List[ChatCitation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def required_scope(self):
        if self.action == "research" and self.task_input is None:
            raise ValueError("research 必须给出完整、经校验的 TaskInput")
        if self.action != "answer" and self.citations:
            raise ValueError("仅 answer 可以引用来源")
        return self
