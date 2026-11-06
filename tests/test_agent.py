"""对话 agent 的定向离线测试：工具循环与计数、引文核对、执行上限与收尾、执行中插话、停止、阅读子 agent、上下文压缩。

模型、arXiv 和 PDF 都是脚本化替身，只验证控制与证据契约，不评估科研语义。"""
import asyncio
import json
import time
from contextlib import suppress

import httpx
import pytest

from backend.app.adapters.llm import LLMError, LLMUsage, OpenAIResponsesAdapter
from backend.app.adapters.pdf import PdfError
from backend.app.agent import service as agent
from backend.app.agent.actions import Decide, Find, MainStep, Note, Read, Report
from backend.app.agent.service import AgentService, Transcript
from backend.app.agent.worker import SerialWorker
from backend.app.agent.workspace import ToolError, Workspace
from backend.app.domain.models import Evidence, Run, RunStatus, SourceText, SourceType, Task
from backend.app.storage.database import Database
from tests.agent_fakes import (
    QUESTION, Model, Pdf, Search, answer, finding, message, observation, page_text, paper, reply, research, results,
    search_step, send,
)


@pytest.fixture
def db(tmp_path):
    store = Database(tmp_path / "agent.db")
    yield store
    store.close()


def service_with(db, steps, papers=(), **kwargs):
    return AgentService(db, Model(steps, **kwargs), arxiv=Search(list(papers)), pdf=Pdf())


def events(db, task_id):
    return db.list_events(db.agent_run(task_id).id)


async def until(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "条件没有在限定时间内满足"
        await asyncio.sleep(0.01)


# --- 主循环与计数 ---

def test_research_turn_runs_tools_and_saves_counted_progress(db):
    service, task_id, model = research(db)
    run = db.agent_run(task_id)
    final = answer(service.store, task_id)
    assert final.status == "completed" and final.content.startswith("报告已写好")
    assert final.citations and all(c.evidence_id and c.run_id == run.id for c in final.citations)
    work = final.work
    # 5 次模型调用 + 1 次检索 + 1 次全文下载；只下载了要读全文的那一篇。
    assert (work.steps, work.model_calls, work.calls) == (5, 5, 7) and work.activity is None
    assert service.pdf.calls == [paper(0).id] and len(service.arxiv.queries) == 1
    assert [t.status for t in work.todos] == ["in_progress", "pending", "pending"]
    usage = service.store.usage(task_id)
    assert usage.model_calls == 5 and usage.token_usage["total_tokens"] == 35
    assert (run.total_calls, run.model_calls, run.token_usage["total_tokens"]) == (7, 5, 35)
    report = db.get_report(run.id)
    assert report.id == work.report_id and [s.title for s in report.document.sections] == ["方法", "结果"]
    assert any("未读取全文" in gap for gap in report.gaps)
    assert report.document.assessment.comparisons[0].status == "not_comparable"
    assert {e.turn_id for e in events(db, task_id)} == {final.id}
    assert {"thought", "tool"} <= {e.category for e in events(db, task_id)}
    opening = observation(model.calls()[0][:2])
    assert opening["message"] == QUESTION and opening["workspace"]["counts"]["candidates"] == 0


def test_each_message_gets_a_fresh_budget_while_conversation_usage_accumulates(db):
    service, task_id, _ = research(db)
    service.llm = Model([reply("工作区已有 2 篇纳入论文。")])
    send(service, "现在有哪些资料？", task_id)
    final = answer(service.store, task_id)
    assert final.content == "工作区已有 2 篇纳入论文。" and (final.work.steps, final.work.calls) == (1, 1)
    assert service.store.usage(task_id).model_calls == 6 and db.agent_run(task_id).total_calls == 8
    opening = observation(service.llm.calls()[0])
    assert [m["role"] for m in opening["conversation"]] == ["user", "assistant"]
    assert opening["workspace"]["counts"]["included"] == 2 and opening["workspace"]["latest_report"]


def test_without_a_model_the_message_fails_with_a_setup_hint(db):
    service = AgentService(db, None, arxiv=Search([]), pdf=Pdf())
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert final.status == "failed" and final.error_category == "model_not_configured"
    assert "配置并启用模型" in final.content and db.list_runs(task_id) == []


def test_program_error_fails_the_turn_visibly_and_is_raised(db, monkeypatch):
    def broken(self, action):
        raise KeyError("private detail")
    monkeypatch.setattr(Workspace, "decide", broken)
    service = service_with(db, [{"actions": [{"tool": "decide", "decisions": [{"paper_id": "x", "include": True, "reason": "r"}]}]}])
    task_id = service.store.enqueue(message("调研", create=True))
    with pytest.raises(KeyError):
        asyncio.run(service.process(service.store.next_turn()))
    final = answer(service.store, task_id)
    assert final.status == "failed" and final.error_category == "internal_error"
    assert "KeyError" in final.content and "private detail" not in final.content


# --- 证据 ---

LONG_PAGE = ("Results are reported in Table 1. " + "x " * 300 + "The verifier rejects unsafe plans. "
             + "y " * 300 + "Results are reported in Table 1. A distant sentence about compute budgets.")


class Budget:
    """Workspace 用到的预算接口：全文下载计数和外部请求计数。"""
    max_fulltext = 10

    def __init__(self):
        self.fulltexts, self.calls = 0, 0

    async def external(self):
        self.calls += 1


async def open_workspace(db, pdf=None, offline=False):
    db.create_task(Task(id="t", topic="Agents"))
    run = db.agent_run("t")
    db.save_papers([paper(0), paper(1)], run.id, selected=False)
    return Workspace(db, run, Search([]), pdf or Pdf(), Budget(), asyncio.Lock(), offline=offline)


def note(paper_id, *findings):
    return Note(tool="note", paper_id=paper_id, findings=list(findings))


def test_note_keeps_only_exact_quotes_from_text_the_agent_has_read(db):
    pid = paper(0).id

    async def scenario():
        ws = await open_workspace(db, Pdf({1: page_text(pid, 1), 2: LONG_PAGE}))
        with pytest.raises(ToolError, match="还没有读过这篇论文"):
            ws.note(note(pid, finding("method", "M0", "src_any", "We propose planner M0")))
        # find 只把命中处前后的窗口记为已读。
        _, found = await ws.find(Find(tool="find", paper_id=pid, text="verifier rejects"))
        page = found["matches"][0]["source_text_id"]
        summary, data = ws.note(note(pid,
            finding("method", "M", page, "The  verifier rejects unsafe\nplans."),
            finding("results", "r", page, "A distant sentence about compute budgets."),
            finding("datasets", "d", page, "Results are reported in Table 1."),
            finding("metrics", "m", page, "Table 1"),
            finding("limitations", "l", page, "The verifier accepts unsafe plans."),
            finding("research_question", "q", "src_foreign", "Fixture 0 studies tool-using agents.")))
        assert [item["field_name"] for item in data["saved"]] == ["method"] and "5 条引文未通过核对" in summary
        errors = {r["field_name"]: r["error"] for r in data["rejected"]}
        assert "还没有读过" in errors["results"] and "多次" in errors["datasets"] and "太短" in errors["metrics"]
        assert "不一致" in errors["limitations"] and "不属于这篇论文" in errors["research_question"]
        evidence = db.get_evidence(pid, ws.run.id)[0]
        assert evidence.quote == "The verifier rejects unsafe plans."
        assert LONG_PAGE[evidence.location_start:evidence.location_end] == evidence.quote
        with pytest.raises(ToolError, match="没有保存任何发现"):
            ws.note(note(pid, finding("results", "r", page, "A distant sentence about compute budgets.")))
        # 一步能返回的原文有上限：放不下的页不读，也不记为已读。
        _, data = await ws.read(Read(tool="read", paper_id=pid, pages=[1, 2]), room=len(page_text(pid, 1)) + 10)
        assert [p["page"] for p in data["pages"]] == [1] and data["skipped_pages"]["pages"] == [2]
        assert not any(r.source_text_id == page and r.location_end == len(LONG_PAGE) for r in ws.analyses()[pid].ranges)
        with pytest.raises(ToolError, match="已到上限"):
            await ws.read(Read(tool="read", paper_id=pid, pages=[2]), room=10)
    asyncio.run(scenario())


def test_report_rejects_unknown_or_excluded_evidence_and_includes_cited_papers(db):
    async def scenario():
        ws = await open_workspace(db)
        ids = {}
        for i in (0, 1):
            pid = paper(i).id
            _, data = await ws.read(Read(tool="read", paper_id=pid))
            source = data["abstract"]["source_text_id"]
            _, saved = ws.note(note(pid, finding("method", f"M{i}", source, f"We propose planner M{i} for long-horizon tasks.")))
            ids[pid] = saved["saved"][0]["evidence_ids"]

        def report(evidence_ids):
            return Report(tool="report", title="t", question="q", sections=[
                {"title": "s", "claims": [{"text": "c", "origin": "author", "evidence_ids": evidence_ids}]}])
        first, second = paper(0).id, paper(1).id
        with pytest.raises(ToolError, match="不存在"):
            ws.report(report(["ev_invented"]), {})
        ws.decide(Decide(tool="decide", decisions=[{"paper_id": first, "include": False, "reason": "离题"}]))
        with pytest.raises(ToolError, match="已排除"):
            ws.report(report(ids[first]), {})
        _, data = ws.report(report(ids[second]), {})
        selection = ws.selections()[second]
        assert data["papers"] == 1 and selection.relevant and selection.reason == "报告引用了这篇论文的证据"
        with pytest.raises(ToolError, match="不存在"):
            ws.citations(["ev_invented"])
        assert [c.evidence_id for c in ws.citations(ids[second])] == ids[second]
    asyncio.run(scenario())


def test_temporary_pdf_failure_can_be_retried_but_unreadable_pdf_is_recorded_missing(db):
    async def scenario():
        pdf = Pdf(error=PdfError("download_timeout", "artificial timeout"))
        ws = await open_workspace(db, pdf)
        first, second = paper(0).id, paper(1).id
        with pytest.raises(ToolError, match="暂时失败"):
            await ws.read(Read(tool="read", paper_id=first, pages=[1]))
        assert "未下载" in ws.fulltext_status(paper(0))
        pdf.error = None
        _, data = await ws.read(Read(tool="read", paper_id=first, pages=[1]))
        assert data["pages"][0]["page"] == 1
        pdf.error = PdfError("parse_failed", "artificial parse failure")
        for _ in range(2):
            with pytest.raises(ToolError, match="全文不可用"):
                await ws.read(Read(tool="read", paper_id=second, pages=[1]))
        assert ws.fulltext_status(paper(1)) == "不可用（parse_failed）"
        assert pdf.calls == [first, first, second] and ws.budget.calls == 3
    asyncio.run(scenario())


def test_ask_mode_answers_from_saved_material_without_external_requests(db):
    pid = paper(0).id
    model = Model([
        {"actions": [{"tool": "search", "query": "agents"}, {"tool": "read", "paper_id": pid, "pages": [1]},
                     {"tool": "read", "paper_id": pid}]},
        reply("它提出规划器 M0。", ["ev_invented"]),
        reply("它提出规划器 M0。"),
    ])
    service = AgentService(db, model, arxiv=Search([paper(0)]), pdf=Pdf())
    task_id = service.store.enqueue(message("这篇讲了什么？", mode="ask", create=True))
    db.save_papers([paper(0)], db.agent_run(task_id).id, selected=False)
    asyncio.run(service.process(service.store.next_turn()))
    search, fulltext, abstract = observation(model.calls()[1])["results"]
    assert "仅用已有资料" in search["error"] and "还没有下载全文" in fulltext["error"] and abstract["ok"]
    assert "不存在" in observation(model.calls()[2])["results"][0]["error"]
    final = answer(service.store, task_id)
    assert final.content == "它提出规划器 M0。" and not final.citations and final.work.calls == 3
    assert service.arxiv.queries == [] and service.pdf.calls == []


# --- 模型输出与服务错误 ---

@pytest.mark.parametrize("bad", ["schema", "json"])
def test_invalid_output_goes_back_to_the_model_with_the_reason(db, bad):
    usage = LLMUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5)
    wrong = {"thought": "忘了 actions"} if bad == "schema" else LLMError("invalid_json", "x", usage=usage, diagnostic="第 1 行第 9 列")
    service = service_with(db, [wrong, reply("好的。")])
    task_id = send(service, "你好")
    final = answer(service.store, task_id)
    assert final.status == "completed" and final.content == "好的。"
    retry = service.llm.calls()[1]
    error = observation(retry)["output_error"]
    if bad == "schema":
        assert retry[-2].role == "assistant" and json.loads(retry[-2].content) == wrong
        assert error.startswith("输出不符合格式") and "actions" in error
    else:
        assert error == "输出不是有效的 JSON 对象（第 1 行第 9 列）"
        assert service.store.usage(task_id).token_usage["total_tokens"] == 12
    assert any(e.category == "error" for e in events(db, task_id))


def test_three_invalid_outputs_in_a_row_fail_the_turn_but_keep_the_workspace(db):
    service = service_with(db, [{"actions": []}] * 3)
    task_id = send(service, "你好")
    final = answer(service.store, task_id)
    assert final.status == "failed" and final.error_category == "invalid_output"
    assert "可以稍后发送“继续”" in final.content and len(service.llm.requests) == 3


@pytest.mark.parametrize("errors, outcome, calls", [
    (["server_error", "rate_limited"], "completed", 3),
    (["server_error"] * 3, "server_error", 3),
    (["http_error"], "http_error", 1),
])
def test_only_temporary_model_errors_are_retried_and_every_attempt_is_counted(db, monkeypatch, errors, outcome, calls):
    monkeypatch.setattr(agent, "RETRY_DELAYS", (0, 0))
    service = service_with(db, [LLMError(code, "artificial outage") for code in errors] + [reply("恢复了。")])
    task_id = send(service, "你好")
    final = answer(service.store, task_id)
    assert service.store.usage(task_id).model_calls == calls
    if outcome == "completed":
        assert final.content == "恢复了。" and len([e for e in events(db, task_id) if e.category == "retry"]) == 2
    else:
        assert final.status == "failed" and final.error_category == outcome


def test_responses_adapter_format_errors_go_back_to_the_model(db):
    bodies = []
    outputs = ['{"thought": ', "```json\n" + json.dumps(reply("完成。")) + "\n```"]

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "completed", "usage": {"input_tokens": 5, "output_tokens": 7}, "output": [
            {"type": "message", "phase": "commentary", "content": [{"type": "output_text", "text": "Working on it."}]},
            {"type": "message", "phase": "final_answer", "content": [{"type": "output_text", "text": outputs[len(bodies) - 1]}]}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = OpenAIResponsesAdapter("https://model.test/v1", "fixture", client=client)
            service = AgentService(db, adapter, arxiv=Search([]), pdf=Pdf())
            task_id = service.store.enqueue(message("你好", create=True))
            await service.process(service.store.next_turn())
            return service, task_id
    service, task_id = asyncio.run(scenario())
    assert answer(service.store, task_id).content == "完成。" and len(bodies) == 2
    assert "output_error" in json.loads(bodies[1]["input"][-1]["content"])
    assert service.store.usage(task_id).token_usage["total_tokens"] == 24


# --- 执行上限 ---

def test_step_limit_wraps_up_with_a_reply_and_refuses_more_tools(db, monkeypatch):
    monkeypatch.setitem(agent.LIMITS, "steps", 2)
    service = service_with(db, [search_step(1), search_step(1), search_step(1), reply("检索了两次，还没有证据。")], [paper(0)])
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert final.content == "检索了两次，还没有证据。" and final.work.stop_reason == "达到本轮步数上限"
    assert final.work.steps == 2 and len(service.arxiv.queries) == 2
    wrap, retry = service.llm.calls()[2:]
    assert observation(wrap)["final"].startswith("达到本轮步数上限")
    assert observation(retry)["output_error"] == "收尾阶段只能输出 reply"
    assert any(e.category == "limit" for e in events(db, task_id))


def test_call_limit_stops_tools_and_only_the_reserved_reply_call_follows(db, monkeypatch):
    monkeypatch.setitem(agent.LIMITS, "calls", 3)
    service = service_with(db, [search_step(1), search_step(1), reply("预算用完，只检索了一次。")], [paper(0)])
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert final.content == "预算用完，只检索了一次。" and final.work.stop_reason == "达到本轮外部调用上限"
    assert final.work.calls == 4 <= agent.LIMITS["calls"] + agent.FINAL_CALLS and len(service.arxiv.queries) == 1
    assert "达到本轮外部调用上限" in observation(service.llm.calls()[2])["results"][0]["error"]


def test_time_limit_cuts_off_a_hanging_model_call(db, monkeypatch):
    monkeypatch.setitem(agent.LIMITS, "seconds", 0.2)
    monkeypatch.setattr(agent, "FINAL_SECONDS", 0)

    async def hang(messages):
        await asyncio.Event().wait()
    service = service_with(db, [hang])
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert final.status == "completed" and final.content.startswith("达到本轮执行时间上限，没能生成本轮总结")
    usage = service.store.usage(task_id)
    assert usage.model_calls == 1 and usage.token_usage["total_tokens"] is None and usage.total_execution_seconds > 0.2


def test_invalid_wrap_up_falls_back_to_a_summary_of_saved_material(db, monkeypatch):
    monkeypatch.setitem(agent.LIMITS, "steps", 1)
    service = service_with(db, [search_step(2), {"thought": "没有动作"}, search_step(1)], [paper(0), paper(1)])
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert final.status == "completed" and not final.citations
    assert final.content.startswith("达到本轮步数上限，没能生成本轮总结") and "候选论文 2 篇" in final.content
    assert len(service.llm.requests) == 1 + agent.FINAL_CALLS


# --- 执行中插话与停止 ---

def test_message_sent_during_work_joins_the_running_turn(db):
    def first(messages):
        service.store.enqueue(message("只看 2024 年以后的"), task_id)
        return {"thought": "先检索", "actions": search_step(1)["actions"]}
    service = service_with(db, [first, reply("已按 2024 年以后筛选。")], [paper(0)])
    task_id = service.store.enqueue(message("调研规划方法", create=True))
    asyncio.run(service.process(service.store.next_turn()))
    _, handed_over, joined, final = service.store.messages(task_id)
    assert observation(service.llm.calls()[1])["new_messages"] == [{"content": "只看 2024 年以后的", "mode": "auto"}]
    assert handed_over.status == "completed" and handed_over.content == "" and handed_over.work.continued
    assert handed_over.work.steps == 1 and final.work.steps == 2 and final.content == "已按 2024 年以后筛选。"
    assert joined.status == "completed" and not service.store.pending(task_id)
    log = events(db, task_id)
    assert {e.turn_id for e in log if e.category in ("thought", "tool")} == {handed_over.id}
    received = next(e for e in log if e.category == "message")
    assert received.actor == "user" and received.turn_id == final.id


def test_messages_queued_before_work_starts_are_read_together_and_the_latest_mode_applies(db):
    service = service_with(db, [search_step(1), reply("一起处理了。")], [paper(0)])
    task_id = service.store.enqueue(message("第一条", create=True))
    service.store.enqueue(message("第二条", mode="ask"), task_id)
    asyncio.run(service.process(service.store.next_turn()))
    _, skipped, _, final = service.store.messages(task_id)
    assert skipped.work is None and skipped.content == "" and skipped.status == "completed"
    assert final.content == "一起处理了。"
    opening = observation(service.llm.calls()[0])
    assert opening["message"] == "第一条" and opening["new_messages"] == [{"content": "第二条", "mode": "ask"}]
    assert "仅用已有资料" in observation(service.llm.calls()[1])["results"][0]["error"] and not service.arxiv.queries


@pytest.mark.parametrize("how", ["stop", "shutdown"])
def test_stop_or_shutdown_cancels_the_model_call_and_keeps_counted_usage(db, how):
    async def scenario():
        started = asyncio.Event()

        async def hang(messages):
            started.set()
            await asyncio.Event().wait()
        service = service_with(db, [hang, reply("继续完成。")])
        worker = SerialWorker(db, service)
        serving = asyncio.create_task(worker.serve())
        task_id = service.store.enqueue(message("调研", create=True))
        worker.notify()
        await asyncio.wait_for(started.wait(), 5)
        if how == "stop":
            service.store.stop(task_id)
            worker.cancel(task_id)
            await until(lambda: not worker.busy)
            # 停止后 worker 继续处理后续消息。
            service.store.enqueue(message("继续"), task_id)
            worker.notify()
            await until(lambda: not service.store.pending(task_id))
        serving.cancel()
        with suppress(asyncio.CancelledError):
            await serving
        return service, task_id
    service, task_id = asyncio.run(scenario())
    messages = service.store.messages(task_id)
    stopped, usage = messages[1], service.store.usage(task_id)
    assert stopped.status == "interrupted" and stopped.work.activity is None
    # 被取消的调用已经计数；它的 token 未知，之后的累计也保持未知。
    assert usage.token_usage["total_tokens"] is None
    if how == "stop":
        assert stopped.error_category == "user_cancelled" and stopped.content == "已停止。"
        assert messages[3].content == "继续完成。" and usage.model_calls == 2
    else:
        assert stopped.error_category == "process_interrupted" and "处理已中断" in stopped.content
        assert usage.model_calls == 1 and service.store.next_turn() is None


# --- 阅读子 agent ---

def reader(pid, number):
    def read_abstract(messages):
        return {"thought": "先读摘要", "actions": [{"tool": "read", "paper_id": pid}]}

    def note_and_finish(messages):
        source = results(messages, "read")[0]["data"]["abstract"]["source_text_id"]
        return {"actions": [
            {"tool": "note", "paper_id": pid, "findings": [
                finding("method", f"M{number}", source, f"We propose planner M{number} for long-horizon tasks.")]},
            {"tool": "done", "summary": f"M{number} 是规划器"}]}
    return [read_abstract, note_and_finish]


def delegate_step(papers):
    return {"actions": [{"tool": "delegate", "context": "调研长程规划方法", "tasks": [
        {"paper_id": p.id, "instruction": "记录方法并给出引文"} for p in papers]}]}


def test_readers_work_in_parallel_within_the_limit_and_report_evidence(db, monkeypatch):
    monkeypatch.setitem(agent.LIMITS, "readers", 2)
    papers = [paper(i) for i in range(3)]
    delegated = {}

    def summarize(messages):
        delegated.update(results(messages, "delegate")[0])
        return reply("三篇都读完了。", [i for ids in delegated["evidence"].values() for i in ids])
    model = Model([search_step(3), delegate_step(papers), summarize],
                  readers={p.id: reader(p.id, i) for i, p in enumerate(papers)}, delay=0.02)
    service = AgentService(db, model, arxiv=Search(papers), pdf=Pdf())
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert model.peak == 2
    outcomes = delegated["data"]["results"]
    assert [o["status"] for o in outcomes] == ["done"] * 3 and all(o["evidence"] and o["read"] == "摘要" for o in outcomes)
    assert len(final.citations) == 3 and final.work.subagents == 3
    assert service.store.usage(task_id).model_calls == 3 + 6
    assert {"reader:" + p.id for p in papers} <= {e.actor for e in events(db, task_id)}
    # 子 agent 只看到自己的论文和主 agent 的说明，看不到对话。
    opening = observation(model.calls("reader:" + papers[0].id)[0][:2])
    assert opening["paper"]["paper_id"] == papers[0].id and opening["context"] == "调研长程规划方法"
    assert "conversation" not in opening


def test_readers_stop_at_the_shared_call_limit_and_the_main_agent_wraps_up(db, monkeypatch):
    monkeypatch.setitem(agent.LIMITS, "calls", 5)
    papers = [paper(0), paper(1)]
    delegated = {}

    def wrap(messages):
        delegated.update(results(messages, "delegate")[0])
        return reply("预算用完：两篇只读了摘要。")
    model = Model([search_step(2), delegate_step(papers), wrap], readers={p.id: reader(p.id, i)[:1] for i, p in enumerate(papers)})
    service = AgentService(db, model, arxiv=Search(papers), pdf=Pdf())
    task_id = send(service, "调研")
    final = answer(service.store, task_id)
    assert [(o["status"], o["summary"]) for o in delegated["data"]["results"]] == [("incomplete", "达到本轮外部调用上限")] * 2
    assert final.content == "预算用完：两篇只读了摘要。" and final.work.stop_reason == "达到本轮外部调用上限"
    assert final.work.calls == 6


# --- 上下文压缩与旧数据 ---

def test_transcript_compacts_old_steps_but_keeps_user_messages_and_alternation():
    transcript = Transcript("system", {"message": "hi"}, keep=2, slack=1, cap=100000)
    for n in range(4):
        step = MainStep.model_validate({"thought": f"step {n}", "actions": [{"tool": "search", "query": f"q{n}"}]})
        extra = {"new_messages": [{"content": "补充", "mode": "auto"}]} if n == 0 else {}
        transcript.add(step, [{"tool": "search", "ok": True, "summary": f"s{n}", "data": {"papers": ["x" * 50]}}], extra)
    transcript.memo["todos"] = [{"text": "检索", "status": "done"}]
    messages = transcript.messages()
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant", "user"]
    opening = json.loads(messages[1].content)
    assert [s["thought"] for s in opening["earlier_steps"]] == ["step 0", "step 1"]
    assert opening["earlier_steps"][0]["new_messages"] == [{"content": "补充", "mode": "auto"}]
    assert "data" not in opening["earlier_steps"][0]["results"][0] and opening["todos"][0]["text"] == "检索"
    transcript.cap = 10
    assert len(transcript.messages()) == 4 and transcript.compacted == 3


def test_old_pipeline_runs_are_closed_and_their_material_joins_the_agent_workspace(db):
    db.create_task(Task(id="t", topic="Agents"))
    db.create_run(Run(id="old", task_id="t", initial_topic="Agents", status=RunStatus.PAUSED))
    old = paper(0)
    db.save_papers([old], "old")
    db.save_source_texts([SourceText(id="s0", paper_id=old.id, source_type=SourceType.ABSTRACT, content=old.abstract)], "old")
    db.save_evidence([Evidence(id="e0", source_text_id="s0", paper_id=old.id, quote="Fixture 0", location_start=0, location_end=9)])
    db.interrupt_running()
    assert db.get_run("old").status == RunStatus.INTERRUPTED and "旧运行不再继续" in db.get_run("old").stop_reason
    run = db.agent_run("t")
    assert run.agent and db.agent_run("t").id == run.id != "old"
    assert [p.id for p in db.get_papers_by_run(run.id)] == [old.id] and not db.get_papers_by_run(run.id, selected_only=True)
    assert [e.id for e in db.run_evidence(run.id)] == ["e0"]
