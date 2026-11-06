"""对话 agent 的离线替身：按脚本返回的模型步骤、固定的检索结果和全文页。只验证控制与证据契约，不代表科研答案。"""
import asyncio
import inspect
import json
from uuid import uuid4

from backend.app import prompts
from backend.app.adapters.llm import LLMResponse, LLMUsage
from backend.app.agent.service import AgentService
from backend.app.domain.conversation import ConversationCreateRequest, ConversationMessageRequest
from backend.app.domain.models import Paper, SourceText, SourceType

QUESTION = "调研 tool-using agent 的长程规划方法"


def paper(i, pdf=True):
    return Paper(id=f"arxiv:2401.0000{i}", source_id=f"2401.0000{i}", title=f"Fixture paper {i}", authors=[f"Author {i}"],
                 year=2024, url=f"https://arxiv.org/abs/2401.0000{i}",
                 pdf_url=f"https://arxiv.org/pdf/2401.0000{i}" if pdf else None,
                 abstract=f"Fixture {i} studies tool-using agents. We propose planner M{i} for long-horizon tasks. "
                          f"Experiments on benchmark B{i} report {70 + i} percent success.")


def page_text(paper_id, number):
    return (f"Page {number} of {paper_id}. Section {number} describes how the planner decomposes goals into subgoals "
            f"and verifies each step. On benchmark B the success rate is {60 + number} percent under protocol P{number}. ")


class Search:
    def __init__(self, papers):
        self.papers, self.queries = papers, []

    async def search(self, query, max_results=15, on_request=None):
        await on_request()
        self.queries.append(query)
        return [p.model_copy() for p in self.papers[:max_results]]


class Pdf:
    """pages 为页数（默认文本）或 {页码: 文本}；error 不为 None 时下载失败。"""

    def __init__(self, pages=3, error=None):
        self.pages, self.error, self.calls = pages, error, []

    async def download_and_extract(self, url, paper_id, on_request=None):
        await on_request()
        self.calls.append(paper_id)
        if self.error is not None:
            raise self.error
        pages = self.pages if isinstance(self.pages, dict) else {n: page_text(paper_id, n) for n in range(1, self.pages + 1)}
        return [SourceText(id="", paper_id=paper_id, source_type=SourceType.FULLTEXT, source_url=url, page_number=n, content=text)
                for n, text in pages.items()]


class Model:
    """按调用顺序返回脚本中的步骤：dict、异常，或接收本次请求消息的函数（可以是协程）。

    阅读子 agent 按论文分别取 readers[paper_id] 中的脚本；delay 让子 agent 的调用交错，用来观察并发。"""

    def __init__(self, steps, readers=None, delay=0):
        self.steps = list(steps)
        self.readers = {k: list(v) for k, v in (readers or {}).items()}
        self.requests = []
        self.delay, self.active, self.peak = delay, 0, 0

    async def generate(self, messages, **kwargs):
        assert kwargs == {"response_format": "json_object"}
        actor, queue = "agent", self.steps
        if messages[0].content == prompts.READER:
            paper_id = json.loads(messages[1].content)["paper"]["paper_id"]
            actor, queue = "reader:" + paper_id, self.readers[paper_id]
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(self.delay)
            finally:
                self.active -= 1
        self.requests.append((actor, messages))
        item = queue.pop(0)
        if callable(item):
            item = item(messages)
            if inspect.isawaitable(item):
                item = await item
        if isinstance(item, Exception):
            raise item
        return LLMResponse(content=json.dumps(item, ensure_ascii=False), parsed_json=item,
                           usage=LLMUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7))

    def calls(self, actor="agent"):
        return [messages for a, messages in self.requests if a == actor]


def observation(messages):
    """请求中最后一条 user 消息：上一步的结果、新消息或格式错误说明。"""
    return json.loads(messages[-1].content)


def results(messages, tool):
    return [r for r in observation(messages)["results"] if r["tool"] == tool]


def quote(source, text):
    return {"source_text_id": source, "quote": text}


def finding(field, value, source, text):
    return {"field_name": field, "value": value, "citations": [quote(source, text)]}


def reply(content, evidence_ids=()):
    return {"actions": [{"tool": "reply", "content": content, "evidence_ids": list(evidence_ids)}]}


def search_step(count):
    return {"actions": [{"tool": "search", "query": "all:agents", "max_results": count}]}


def message(content, mode="auto", create=False):
    cls = ConversationCreateRequest if create else ConversationMessageRequest
    return cls(content=content, mode=mode, request_id=uuid4().hex)


def send(service, content, task_id=None, mode="auto"):
    """发一条消息并处理到这一轮结束；返回对话 ID。"""
    task_id = service.store.enqueue(message(content, mode, create=task_id is None), task_id)
    asyncio.run(service.process(service.store.next_turn()))
    return task_id


def answer(store, task_id):
    return [m for m in store.messages(task_id) if m.role == "assistant"][-1]


def labelled(note_result):
    return {item.get("field_name") or item["experiment"]: item["evidence_ids"] for item in note_result["data"]["saved"]}


def research(db, question=QUESTION):
    """一轮完整的脚本化调研：计划与检索、读摘要和全文、记录发现并纳入、写报告、回复。返回 (service, task_id, model)。"""
    first, second = paper(0), paper(1)
    saved = {}

    def notes(messages):
        reads = results(messages, "read")
        abstract0 = reads[0]["data"]["abstract"]["source_text_id"]
        page1 = reads[1]["data"]["pages"][0]["source_text_id"]
        abstract1 = reads[2]["data"]["abstract"]["source_text_id"]
        experiment = "On benchmark B the success rate is 61 percent under protocol P1."
        return {"thought": "记录两篇论文的发现并纳入", "actions": [
            {"tool": "note", "paper_id": first.id, "findings": [
                finding("research_question", "工具使用 agent 的长程任务", abstract0, "Fixture 0 studies tool-using agents."),
                finding("method", "规划器 M0", abstract0, "We propose planner M0 for long-horizon tasks."),
                finding("datasets", "基准 B", page1, "On benchmark B the success rate"),
                finding("metrics", "成功率", page1, "the success rate is 61 percent"),
                finding("results", "成功率 61%", page1, experiment),
                {"field_name": "limitations", "value": None, "missing_reason": "not_found"}],
             "experiments": [{"dataset": "B", "metric": "success rate", "value": "61", "unit": "percent", "direction": "higher",
                              "protocol": "P1", "citations": [quote(page1, experiment)]}]},
            {"tool": "note", "paper_id": second.id, "findings": [
                finding("research_question", "工具使用 agent", abstract1, "Fixture 1 studies tool-using agents."),
                finding("method", "规划器 M1", abstract1, "We propose planner M1 for long-horizon tasks.")],
             "experiments": [{"dataset": "B1", "metric": "success rate", "value": "71", "unit": "percent",
                              "citations": [quote(abstract1, "Experiments on benchmark B1 report 71 percent success.")]}]},
            {"tool": "decide", "decisions": [{"paper_id": first.id, "include": True, "reason": "直接研究长程规划"},
                                             {"paper_id": second.id, "include": True, "reason": "提供另一基准上的结果"}]}]}

    def report(messages):
        one, two = (labelled(r) for r in results(messages, "note"))
        saved.update(one=one, two=two)
        return {"actions": [{"tool": "report", "title": "长程规划 agent 调研", "question": question, "sections": [
            {"title": "方法", "claims": [
                {"text": "M0 用规划器分解长程任务并逐步验证。", "origin": "author", "evidence_ids": one["method"]},
                {"text": "M1 同样采用规划器。", "origin": "author", "evidence_ids": two["method"]}]},
            {"title": "结果", "claims": [
                {"text": "两篇论文的成功率来自不同基准，不能直接比较。", "origin": "inference",
                 "evidence_ids": one["B / success rate"] + two["B1 / success rate"]}]}],
            "gaps": ["缺少同一基准上的对比实验"]}]}

    model = Model([
        {"thought": "先列计划，再检索", "actions": [
            {"tool": "todo", "items": [{"text": "检索候选论文", "status": "in_progress"}, {"text": "精读并记录证据"}, {"text": "写报告"}]},
            search_step(2)["actions"][0]]},
        {"actions": [{"tool": "read", "paper_id": first.id}, {"tool": "read", "paper_id": first.id, "pages": [1, 2]},
                     {"tool": "read", "paper_id": second.id}]},
        notes,
        report,
        lambda messages: reply("报告已写好：M0 在基准 B 上的成功率是 61%。", saved["one"]["results"]),
    ])
    service = AgentService(db, model, arxiv=Search([first, second]), pdf=Pdf())
    return service, send(service, question), model
