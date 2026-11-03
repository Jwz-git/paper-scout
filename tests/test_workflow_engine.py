import asyncio
import json
import pytest
from backend.app.adapters.llm import LLMError, LLMResponse, LLMUsage
from backend.app.domain.models import Paper, Run, RunStatus, RunStage, Task, TaskInput, RunMessage
from backend.app.storage.database import Database
from tests.analysis_samples import analysis_response, planned
from backend.app.workflow.engine import WorkflowEngine


def paper(pid="p1", year=2024):
    return Paper(id=pid,title="Agent study",source="arxiv",source_id=pid,
                 url="https://arxiv.org/abs/"+pid,abstract="A literal abstract about agents.",year=year)


class Search:
    def __init__(self, rows=None, hook=None):
        self.rows = rows if rows is not None else [paper(),paper("p2")]
        self.calls = []
        self.hook = hook

    async def search(self, query, **kwargs):
        if kwargs.get("on_request"):
            await kwargs["on_request"]()
        self.calls.append(query)
        if self.hook:
            self.hook()
        return self.rows


class Model:
    def __init__(self, plans):
        self.plans = iter(plans)
        self.requests = []

    async def generate(self, messages, **kwargs):
        request = json.loads(messages[-1].content)
        self.requests.append(request)
        plan = analysis_response(request) if "operation" in request else planned(next(self.plans))
        return LLMResponse(content=json.dumps(plan),parsed_json=plan,
                           usage=LLMUsage(prompt_tokens=3,completion_tokens=4,total_tokens=7))


@pytest.fixture
def store():
    db = Database(":memory:")
    db.create_task(Task(id="t",topic="Agents",start_year=2022,end_year=2026))
    yield db
    db.close()


def make_run(store, **kwargs):
    run = Run(id="r",task_id="t",initial_topic="Agents",**kwargs)
    store.create_run(run)
    return run


def test_two_papers_are_partial_not_semantically_complete(store):
    make_run(store)
    search = Search()
    final = asyncio.run(WorkflowEngine(store,arxiv_adapter=search).execute_run("r"))
    assert final.status == RunStatus.PARTIAL
    assert final.total_calls == 1  # 本地规划、快照、报告不是外部调用。
    assert "submittedDate:[202201010000 TO 202612312359]" in search.calls[0]
    report = store.get_report("r")
    assert report.stop_reason == final.stop_reason
    assert report.gaps == final.gaps and report.gaps
    assert "阶段性资料报告" in report.title
    assert "字符[" in report.content_markdown
    assert all(store.get_evidence(p.id, "r") for p in store.get_papers_by_run("r"))


def test_empty_results_fail_without_a_fake_report(store):
    make_run(store)
    final = asyncio.run(WorkflowEngine(store,arxiv_adapter=Search([])).execute_run("r"))
    assert final.status == RunStatus.FAILED
    assert store.get_report("r") is None


def test_planning_json_failure_keeps_safe_diagnostic_and_usage(store):
    make_run(store)
    search = Search()
    diagnostic = "JSON语法错误：第1行，第1列（共20字符）。"
    class FailingModel:
        async def generate(self, *args, **kwargs):
            raise LLMError("invalid_json", "private_raw_service_error",
                           usage=LLMUsage(prompt_tokens=5, completion_tokens=7, total_tokens=12), diagnostic=diagnostic)
    engine = WorkflowEngine(store, arxiv_adapter=search, llm_adapter=FailingModel())
    final = asyncio.run(engine.execute_run("r"))
    assert final.status == RunStatus.FAILED
    assert final.total_calls == final.model_calls == 1 and final.token_usage["total_tokens"] == 12
    assert not search.calls and store.get_report("r") is None
    assert diagnostic in final.stop_reason and "private_raw_service_error" not in final.stop_reason
    errors = [event for event in store.list_events("r") if event.category == "service_error"]
    assert len(errors) == 1 and errors[0].message == final.stop_reason


def test_pause_after_first_request_preserves_cursor_and_results(store):
    make_run(store)
    model = Model([{"queries":["all:agent","all:planning"],"subproblems":["planning"]}])
    first = True
    def pause():
        nonlocal first
        if first:
            first = False
            store.transition("r",[RunStatus.RUNNING],RunStatus.PAUSE_REQUESTED)
    search = Search(hook=pause)
    engine = WorkflowEngine(store,arxiv_adapter=search,llm_adapter=model)
    async def scenario():
        paused = await engine.execute_run("r")
        assert paused.status == RunStatus.PAUSED
        assert paused.query_index == 1 and len(search.calls) == 1
        assert len(store.get_papers_by_run("r")) == 2
        before = paused.total_calls
        store.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
        resumed = await engine.execute_run("r")
        assert len(search.calls) == 2  # 已完成的查询不重放。
        assert resumed.total_calls == before + 5  # 剩余检索、筛选、两篇提取、综合；没有重放。
    # 单轮结束无需第二次模型规划。
    r=store.get_run("r"); r.max_rounds=1; store.update_run(r)
    asyncio.run(scenario())


def test_supplements_require_processing_and_preserve_initial_scope(store):
    make_run(store,status=RunStatus.PAUSED)
    store.save_run_message(RunMessage(id="m",run_id="r",content="改为2025年机器人方向"))
    model = Model([{"queries":["all:robotics"],"subproblems":["robotics"],
                    "revised_scope":{"topic":"Robotics","start_year":2025,"end_year":2026},
                    "keep_paper_ids":[]}])
    store.save_papers([paper("old")],"r")
    r=store.get_run("r"); r.max_rounds=1; store.update_run(r)
    store.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
    final = asyncio.run(WorkflowEngine(store,arxiv_adapter=Search([paper("new",2025)]),llm_adapter=model).execute_run("r"))
    assert final.initial_input.topic == "Agents" and final.initial_input.start_year == 2022
    assert final.current_input.topic == "Robotics"
    assert {p.id for p in store.get_papers_by_run("r")} == {"old","new"}
    assert {p.id for p in store.get_papers_by_run("r",selected_only=True)} == {"new"}
    assert store.list_run_messages("r")[0].status == "processed"
    assert final.token_usage["total_tokens"] == 28  # 规划、筛选、提取、综合各一次。


def test_without_model_supplement_is_not_silently_ignored(store):
    make_run(store,status=RunStatus.PAUSED)
    store.save_run_message(RunMessage(id="m",run_id="r",content="改范围"))
    store.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
    final=asyncio.run(WorkflowEngine(store,arxiv_adapter=Search()).execute_run("r"))
    assert final.status == RunStatus.NEEDS_INPUT
    assert store.list_run_messages("r")[0].status == "pending"
    assert final.total_calls == 0


def test_call_limit_stops_model_and_preserves_existing_results(store):
    make_run(store,max_calls=0)
    model=Model([])
    final=asyncio.run(WorkflowEngine(store,llm_adapter=model).execute_run("r"))
    assert final.status == RunStatus.FAILED
    assert final.total_calls == 0 and not model.requests
    assert "调用次数" in final.stop_reason


def test_total_time_limit_terminates_inflight_request(store):
    make_run(store,max_seconds=0.01)
    class Slow(Search):
        async def search(self,*args,**kwargs):
            await kwargs["on_request"]()
            await asyncio.Event().wait()
    final=asyncio.run(WorkflowEngine(store,arxiv_adapter=Slow()).execute_run("r"))
    assert final.status == RunStatus.FAILED and final.total_calls == 1
    assert "时间" in final.stop_reason
    assert store.list_queries("r")[0].error_category == "execution_limit"


def test_programming_error_is_not_empty_search_success(store):
    make_run(store)
    class Broken(Search):
        async def search(self,*args,**kwargs):
            raise KeyError("implementation bug")
    with pytest.raises(KeyError):
        asyncio.run(WorkflowEngine(store,arxiv_adapter=Broken()).execute_run("r"))
    assert store.get_run("r").status == RunStatus.FAILED


def test_cancel_during_request_is_not_overwritten(store):
    make_run(store)
    def cancel():
        store.transition("r",[RunStatus.RUNNING],RunStatus.CANCELLED)
    final=asyncio.run(WorkflowEngine(store,arxiv_adapter=Search(hook=cancel)).execute_run("r"))
    assert final.status == RunStatus.CANCELLED
    assert len(store.get_papers_by_run("r")) == 2
    assert store.get_report("r") is None


@pytest.mark.parametrize("status", [RunStatus.PARTIAL,RunStatus.COMPLETED,RunStatus.FAILED,RunStatus.CANCELLED,RunStatus.INTERRUPTED,RunStatus.PAUSED,RunStatus.NEEDS_INPUT])
def test_no_implicit_restart(store,status):
    make_run(store,status=status)
    search=Search()
    final=asyncio.run(WorkflowEngine(store,arxiv_adapter=search).execute_run("r"))
    assert final.status == status and search.calls == []


def test_pdf_redirects_each_count_and_stop_before_overrun(store):
    make_run(store,max_calls=2)
    p=paper(); p.pdf_url="https://arxiv.org/pdf/test"
    class Download:
        def __init__(self):
            self.requests=0
        async def download_and_extract(self,url,paper_id,*,on_request):
            await on_request(); self.requests+=1
            await on_request(); self.requests+=1
            raise AssertionError("over-budget request should not happen")
    pdf=Download()
    final=asyncio.run(WorkflowEngine(store,arxiv_adapter=Search([p]),pdf_adapter=pdf).execute_run("r"))
    assert final.total_calls == 2 and pdf.requests == 1
    assert final.status == RunStatus.PARTIAL and store.get_report("r") is not None


def test_repeated_model_queries_with_date_filters_stop(store):
    make_run(store)
    model=Model([{"queries":["all:agent"],"subproblems":["agent"]}]*2)
    search=Search()
    final=asyncio.run(WorkflowEngine(store,arxiv_adapter=search,llm_adapter=model).execute_run("r"))
    assert final.status == RunStatus.PARTIAL
    assert len(search.calls)==1 and "新查询" in final.stop_reason
    assert final.total_calls==7


def test_pause_waiting_time_is_not_execution_time(store,monkeypatch):
    from backend.app.workflow import engine as engine_module
    clock=[100.0]
    monkeypatch.setattr(engine_module.time,"monotonic",lambda:clock[0])
    make_run(store)
    def pause():
        clock[0]=110.0
        store.transition("r",[RunStatus.RUNNING],RunStatus.PAUSE_REQUESTED)
    workflow=WorkflowEngine(store,arxiv_adapter=Search(hook=pause))
    async def scenario():
        paused=await workflow.execute_run("r")
        assert paused.total_execution_seconds==10.0
        clock[0]=1000.0
        store.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
        final=await workflow.execute_run("r")
        assert final.total_execution_seconds==10.0
    asyncio.run(scenario())


def test_engine_serializes_different_runs(store):
    store.create_task(Task(id="t2",topic="Other"))
    make_run(store)
    store.create_run(Run(id="r2",task_id="t2",initial_topic="Other"))
    class Concurrent(Search):
        active=0
        maximum=0
        async def search(self,*args,**kwargs):
            self.active+=1
            self.maximum=max(self.maximum,self.active)
            await asyncio.sleep(0)
            self.active-=1
            return self.rows
    search=Concurrent()
    workflow=WorkflowEngine(store,arxiv_adapter=search)
    async def scenario():
        await asyncio.gather(workflow.execute_run("r"),workflow.execute_run("r2"))
    asyncio.run(scenario())
    assert search.maximum==1


def test_duplicate_query_supplement_is_processed_atomically(store):
    from backend.app.domain.models import SourceText,SourceType,SearchQuery
    make_run(store,status=RunStatus.PAUSED)
    p=paper()
    store.save_papers([p],"r")
    store.save_source_texts([SourceText(id="oldsource",paper_id=p.id,source_type=SourceType.ABSTRACT,content=p.abstract)],"r")
    store.save_query(SearchQuery(id="q",run_id="r",round_number=1,query_text="all:agent",raw_query="all:agent"))
    store.save_run_message(RunMessage(id="m",run_id="r",content="保留已有范围，整理已有资料"))
    model=Model([{"queries":["all:agent"],"subproblems":["agents"],"keep_paper_ids":[p.id]}])
    store.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
    final=asyncio.run(WorkflowEngine(store,llm_adapter=model,arxiv_adapter=Search()).execute_run("r"))
    assert final.status==RunStatus.PARTIAL
    assert store.list_run_messages("r")[0].status=="processed"
    assert len(store.get_papers_by_run("r",selected_only=True))==1


def test_missing_supplement_selection_does_not_discard_history(store):
    from backend.app.domain.models import SourceText,SourceType
    make_run(store,status=RunStatus.PAUSED)
    p=paper(); store.save_papers([p],"r")
    store.save_source_texts([SourceText(id="s",paper_id=p.id,source_type=SourceType.ABSTRACT,content=p.abstract)],"r")
    store.save_run_message(RunMessage(id="m",run_id="r",content="调整范围"))
    store.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
    model=Model([{"queries":["all:updated"],"subproblems":["agents"]}])
    final=asyncio.run(WorkflowEngine(store,llm_adapter=model).execute_run("r"))
    assert final.status==RunStatus.PARTIAL
    assert store.list_run_messages("r")[0].status=="pending"
    assert len(store.get_papers_by_run("r",selected_only=True))==1
    assert final.current_input==final.initial_input


def test_program_fault_during_pause_is_not_left_pending(store):
    make_run(store)
    class Fault(Search):
        async def search(self,*args,**kwargs):
            await kwargs["on_request"]()
            store.transition("r",[RunStatus.RUNNING],RunStatus.PAUSE_REQUESTED)
            raise KeyError("program fault")
    with pytest.raises(KeyError):
        asyncio.run(WorkflowEngine(store,arxiv_adapter=Fault()).execute_run("r"))
    assert store.get_run("r").status==RunStatus.FAILED


def test_process_cancel_during_requested_pause_is_interrupted(store):
    make_run(store)
    async def scenario():
        started=asyncio.Event()
        class Waiting(Search):
            async def search(self,*args,**kwargs):
                await kwargs["on_request"]()
                started.set()
                await asyncio.Event().wait()
        engine=WorkflowEngine(store,arxiv_adapter=Waiting())
        task=asyncio.create_task(engine.execute_run("r"))
        await started.wait()
        store.transition("r",[RunStatus.RUNNING],RunStatus.PAUSE_REQUESTED)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.get_run("r").status==RunStatus.INTERRUPTED
    asyncio.run(scenario())
