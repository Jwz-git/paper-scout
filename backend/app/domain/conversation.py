"""持久化对话契约：每条用户消息交给同一个对话 agent，助手消息携带本轮工作状态。"""
from datetime import datetime
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from backend.app.domain.models import Run, SourceType, Task, utc_now

# ask 只用已保存资料回答，不发起检索或全文下载；research 提示 agent 用户要求开展调研。
ConversationMode = Literal["auto", "research", "ask"]
# 旧版对话消息保存过这些动作，读取历史时仍需通过校验。
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
    evidence_id: Optional[str] = None


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=200)
    status: Literal["pending", "in_progress", "done"] = "pending"


class AgentWork(BaseModel):
    """一轮 agent 工作的可见状态；执行中持续保存，供界面实时显示。"""
    run_id: str
    activity: Optional[str] = None
    steps: int = 0
    calls: int = 0
    model_calls: int = 0
    seconds: float = 0.0
    progress_at: Optional[datetime] = None
    todos: List[TodoItem] = Field(default_factory=list)
    subagents: int = 0
    report_id: Optional[str] = None
    stop_reason: Optional[str] = None
    # 用户在执行中发来新消息时，工作转到新消息下方继续；本段只保留到交接为止的记录。
    continued: bool = False
    limits: Dict[str, float] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    id: str
    task_id: str
    role: Literal["user", "assistant"]
    content: str
    status: Literal["queued", "processing", "completed", "failed", "interrupted"]
    action: Optional[ChatAction] = None
    run_id: Optional[str] = None
    citations: List[ChatCitation] = Field(default_factory=list)
    work: Optional[AgentWork] = None
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
