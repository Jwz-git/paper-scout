"""agent 每一步输出的 JSON：{thought, actions}。在入口一次校验，执行时依赖这些类型。"""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.analysis import ExperimentOutput, FieldOutput
from backend.app.domain.conversation import TodoItem


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Search(Action):
    tool: Literal["search"]
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=15, ge=1, le=30)
    start_year: Optional[int] = Field(default=None, ge=1800, le=2100)
    end_year: Optional[int] = Field(default=None, ge=1800, le=2100)


class Read(Action):
    tool: Literal["read"]
    paper_id: str = Field(min_length=1, max_length=200)
    # 空列表读摘要；给页码读全文对应页。
    pages: List[int] = Field(default_factory=list, max_length=4)


class Find(Action):
    tool: Literal["find"]
    paper_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=2, max_length=120)


class Note(Action):
    tool: Literal["note"]
    paper_id: str = Field(min_length=1, max_length=200)
    findings: List[FieldOutput] = Field(default_factory=list, max_length=12)
    experiments: List[ExperimentOutput] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def not_empty(self):
        if not self.findings and not self.experiments:
            raise ValueError("note 至少包含一条 findings 或 experiments")
        return self


class Decision(Action):
    paper_id: str = Field(min_length=1, max_length=200)
    include: bool
    reason: str = Field(min_length=1, max_length=500)


class Decide(Action):
    tool: Literal["decide"]
    decisions: List[Decision] = Field(min_length=1, max_length=30)


class Task(Action):
    paper_id: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=1000)


class Delegate(Action):
    tool: Literal["delegate"]
    context: str = Field(min_length=1, max_length=2000)
    tasks: List[Task] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def distinct(self):
        if len({t.paper_id for t in self.tasks}) != len(self.tasks):
            raise ValueError("同一篇论文只能分配一个子任务")
        return self


class Todo(Action):
    tool: Literal["todo"]
    items: List[TodoItem] = Field(max_length=12)


class Claim(Action):
    text: str = Field(min_length=1, max_length=1500)
    origin: Literal["author", "inference"]
    evidence_ids: List[str] = Field(min_length=1, max_length=10)


class Section(Action):
    title: str = Field(min_length=1, max_length=120)
    claims: List[Claim] = Field(min_length=1, max_length=12)


class Report(Action):
    tool: Literal["report"]
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    sections: List[Section] = Field(min_length=1, max_length=10)
    gaps: List[str] = Field(default_factory=list, max_length=12)


class View(Action):
    tool: Literal["workspace"]
    paper_id: Optional[str] = Field(default=None, max_length=200)


class Reply(Action):
    tool: Literal["reply"]
    content: str = Field(min_length=1, max_length=12000)
    evidence_ids: List[str] = Field(default_factory=list, max_length=30)


class Done(Action):
    tool: Literal["done"]
    summary: str = Field(min_length=1, max_length=2000)


MainAction = Annotated[Union[Search, Read, Find, Note, Decide, Delegate, Todo, Report, View, Reply], Field(discriminator="tool")]
ReaderAction = Annotated[Union[Read, Find, Note, Done], Field(discriminator="tool")]


class MainStep(Action):
    thought: str = Field(default="", max_length=3000)
    actions: List[MainAction] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def reply_alone(self):
        if len(self.actions) > 1 and any(a.tool == "reply" for a in self.actions):
            raise ValueError("reply 必须是这一步唯一的动作")
        return self


class ReaderStep(Action):
    thought: str = Field(default="", max_length=3000)
    actions: List[ReaderAction] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def done_last(self):
        if any(a.tool == "done" for a in self.actions[:-1]):
            raise ValueError("done 只能是这一步最后一个动作")
        return self
