"""离线回归：对话状态、付费幂等性、检查点、引用边界。无真实外部请求。"""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.app.adapters.llm import LLMError, LLMResponse, LLMUsage
from backend.app.dialogue import DialogueService
from backend.app.domain.conversation import ConversationCreateRequest, ConversationMessageRequest
from backend.app.domain.models import Paper, Run, RunStatus, SourceText, SourceType, Task, RunMessage
from backend.app.storage.database import Database, StateConflict
from backend.app.storage.conversations import ConversationStore
from backend.app.workflow.engine import WorkflowEngine
from backend.app.workflow.worker import SerialWorker


class Model:
    def __init__(self, outputs, hook=None):
        self.outputs = iter(outputs)
        self.requests = []
        self.hook = hook

    async def generate(self, messages, **kwargs):
        assert kwargs == {"response_format":"json_object"}
        self.requests.append(json.loads(messages[-1].content))
        if self.hook:
            self.hook()
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return LLMResponse(content=json.dumps(output),parsed_json=output,
            usage=LLMUsage(prompt_tokens=3,completion_tokens=4,total_tokens=7))


def req(content="Agents", key="one", mode="auto", create=False):
    cls = ConversationCreateRequest if create else ConversationMessageRequest
    return cls(content=content,request_id=key,mode=mode)


def complete(service):
    asyncio.run(service.process(service.store.next_turn()))


def turn_answer(store, task_id):
    with store.db._get_connection() as conn:
        mid = conn.execute("SELECT assistant_id FROM conversation_turns WHERE task_id=? ORDER BY rowid DESC LIMIT 1", (task_id,)).fetchone()[0]
    return store.message(mid)


def research(topic="Agents"):
    return {"action":"research","content":"开始资料调研","task_input":{"topic":topic}}


@pytest.fixture
def db():
    store = Database(":memory:")
    yield store
    store.close()


def legacy(db, status=RunStatus.QUEUED):
    db.create_task(Task(id="t",topic="Original",start_year=2022,focus_dimensions=["methods"]))
    db.create_run(Run(id="r",task_id="t",initial_topic="Original",status=status))
    return ConversationStore(db)


def citation_db(db, selected=True):
    store = legacy(db,RunStatus.PARTIAL)
    p = Paper(id="p",source_id="p",title="Study",url="https://arxiv.org/abs/p")
    db.save_papers([p],"r")
    db.save_source_texts([SourceText(id="s",paper_id="p",source_type=SourceType.FULLTEXT,
        page_number=2,source_url="https://arxiv.org/pdf/p",content="Literal evidence. "+"x"*3500)],"r")
    if not selected:
        db.select_papers("r",[])
    return store


def citation(**changes):
    result = {"source_text_id":"s","paper_id":"p","run_id":"r","source_type":"fulltext",
        "source_url":"https://arxiv.org/pdf/p","page_number":2,"quote":"Literal evidence.","location_start":0,"location_end":17}
    result.update(changes)
    return result


def test_api_enqueues_only_pair_and_idempotent_retry(client):
    body = {"content":"Agents","request_id":"create-1"}
    response = client.post("/api/conversations",json=body)
    assert response.status_code == 202
    view = response.json()
    assert set(view) == {"task","messages","runs","usage","busy","model_configured"}
    assert view["runs"] == [] and view["busy"] and not view["model_configured"]
    assert [m["role"] for m in view["messages"]] == ["user","assistant"]
    assert all(m["status"] == "queued" for m in view["messages"])
    assert client.post("/api/conversations",json=body).json() == view
    assert client.post("/api/conversations",json={**body,"content":"Changed"}).status_code == 409
    tid = view["task"]["id"]
    assert client.get("/api/conversations").json()[0]["id"] == tid
    assert client.post(f"/api/conversations/{tid}/messages",json={"content":"more","request_id":"new"}).status_code == 409
    assert client.post(f"/api/tasks/{tid}/runs").status_code == 409
    assert client.get("/api/conversations/missing").status_code == 404
    complete(client.app.state.dialogue)
    current = client.get(f"/api/conversations/{tid}").json()
    assert len(current["runs"]) == 1 and not current["busy"]  # running research does not disable chat
    assert client.post("/api/conversations",json=body).json() == current
    follow = {"content":"more","request_id":"follow"}
    one = client.post(f"/api/conversations/{tid}/messages",json=follow)
    assert one.status_code == 202 and one.json()["runs"][0]["status"] == "paused"
    assert client.post(f"/api/conversations/{tid}/messages",json=follow).json() == one.json()
    assert client.post(f"/api/conversations/{tid}/messages",json={**follow,"mode":"ask"}).status_code == 409


@pytest.mark.parametrize("body", [{"content":" ","request_id":"a"},{"content":"a"},{"content":"a","request_id":""},{"content":"a","request_id":"a","mode":"execute"},{"content":"x"*2001,"request_id":"a"}])
def test_api_input_boundary(client, body):
    assert client.post("/api/conversations",json=body).status_code == 422


def test_persistence_pairing_idempotency_and_interruption(tmp_path):
    path = tmp_path/"conversation.db"
    db = Database(path)
    store = ConversationStore(db)
    tid = store.enqueue(req(create=True))
    turn = store.next_turn()
    store.claim(turn)
    other = store.enqueue(req("Other","two",create=True))
    db.close()
    db = Database(path)
    store = ConversationStore(db)
    store.interrupt_processing()
    assert store.messages(tid)[1].status == "interrupted"
    assert store.messages(tid)[0].content == "Agents"
    assert store.messages(other)[1].status == "queued"
    assert store.enqueue(req(create=True)) == tid
    assert not store.pending(tid) and store.pending(other)
    db.close()


def test_simultaneous_retries_and_one_pending_turn(db):
    store = ConversationStore(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _:store.enqueue(req(create=True)),range(2)))
    assert ids[0] == ids[1] and len(db.list_tasks()) == 1
    complete(DialogueService(db))
    def post(i):
        try:
            store.enqueue(req("new",str(i)),ids[0])
            return True
        except StateConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(post,range(2))) == 1


def test_no_model_discloses_simple_initial_and_preserves_natural_followup(db):
    service = DialogueService(db)
    tid = service.store.enqueue(req(create=True))
    complete(service)
    assert service.store.messages(tid)[1].action == "research"
    assert "未配置模型" in service.store.messages(tid)[1].content
    rid = db.list_runs(tid)[0].id
    service.store.enqueue(req("只看低资源场景","supplement"),tid)
    complete(service)
    assert db.get_run(rid).status == RunStatus.PAUSED
    assert len(db.list_runs(tid)) == 1 and service.store.usage(tid).model_calls == 0
    assert next(m for m in reversed(service.store.messages(tid)) if m.role == "user").content == "只看低资源场景"
    assert turn_answer(service.store,tid).action == "clarify"
    service.store.enqueue(req("回答已有资料","ask","ask"),tid)
    complete(service)
    assert turn_answer(service.store,tid).action == "clarify"
    assert db.get_run(rid).status == RunStatus.PAUSED
    for i,mode in enumerate(("resume","pause","cancel")):
        service.store.enqueue(req(mode,str(i),mode),tid)
        complete(service)
        assert turn_answer(service.store,tid).action == mode
    assert db.get_run(rid).status == RunStatus.CANCELLED


def test_legacy_true_initial_input_and_durable_real_summaries(db):
    store = legacy(db,RunStatus.PAUSED)
    first = store.view("t",False)
    assert first.messages[0].content.startswith("Original")
    assert "methods" in first.messages[0].content and "原始范围" in first.messages[0].content
    assert all(m.action is None for m in first.messages)
    assert len(store.view("t",False).messages) == len(first.messages)
    db.transition("r",[RunStatus.PAUSED],RunStatus.QUEUED)
    db.pause_run("r")
    assert len(store.view("t",False).messages) == len(first.messages)+1
    assert "系统运行摘要（非模型回答）" in store.messages("t")[-1].content


def test_model_auto_clarifies_then_research_uses_bounded_history(db):
    model = Model([{"action":"clarify","content":"更关心方法还是评估？"},research("Agents evaluation")])
    service = DialogueService(db,model)
    tid = service.store.enqueue(req("比较智能体",create=True))
    complete(service)
    assert not db.list_runs(tid)
    service.store.enqueue(req("关注评估","second"),tid)
    complete(service)
    run = db.list_runs(tid)[0]
    assert run.initial_input.topic == "Agents evaluation"
    assert any(m["content"] == "比较智能体" for m in model.requests[1]["history"])
    assert "current_date_utc" in model.requests[1] and "context_limits" in model.requests[1]
    assert service.store.usage(tid).model_calls == 2
    assert service.store.usage(tid).token_usage["total_tokens"] == 14
    assert run.total_calls == 0


def test_active_scope_adjustment_reuses_run_engine_replan_and_original_content(db):
    store = legacy(db)
    db.save_papers([Paper(id="old",source_id="old",title="Old",url="https://arxiv.org/abs/old")],"r")
    model = Model([research("Robotics"),{"queries":["all:robotics"],"subproblems":["robotics"],"keep_paper_ids":[]}])
    service = DialogueService(db,model)
    store.enqueue(req("改为机器人方向","scope"),"t")
    complete(service)
    assert db.get_run("r").status == RunStatus.QUEUED
    supplement = db.list_run_messages("r")[0]
    assert supplement.content == "改为机器人方向" and supplement.proposed_scope.topic == "Robotics"
    assert db.get_task("t").topic == "Original" and db.get_run("r").initial_input.topic == "Original"
    class Search:
        async def search(self,query,**kwargs):
            await kwargs["on_request"]()
            return []
    run = db.get_run("r"); run.max_rounds=1; db.update_run(run)
    asyncio.run(WorkflowEngine(db,llm_adapter=model,arxiv_adapter=Search()).execute_run("r"))
    assert model.requests[1]["scope"]["topic"] == "Robotics"
    assert model.requests[1]["supplements"] == ["改为机器人方向"]
    assert db.get_run("r").current_input.topic == "Robotics"
    assert db.list_run_messages("r")[0].status == "processed"
    assert db.get_papers_by_run("r") and not db.get_papers_by_run("r",selected_only=True)
    assert service.store.usage("t").model_calls == 1 and db.get_run("r").model_calls == 1


@pytest.mark.parametrize("status", [RunStatus.PAUSED,RunStatus.NEEDS_INPUT])
def test_manual_pause_or_needs_input_is_not_automatically_resumed(db,status):
    store = legacy(db,status)
    service = DialogueService(db,Model([research("Adjusted")]))
    store.enqueue(req("调整范围","scope"),"t")
    complete(service)
    assert db.get_run("r").status == status
    assert db.list_run_messages("r")[0].status == "pending"


def test_manual_pause_during_model_call_revokes_owned_pause(db):
    store = legacy(db)
    store.enqueue(req("调整范围","scope"),"t")
    service = DialogueService(db,Model([research("Adjusted")],hook=lambda:db.pause_run("r")))
    complete(service)
    assert db.get_run("r").status == RunStatus.PAUSED
    assert db.list_run_messages("r")[0].content == "调整范围"


def test_cancel_during_model_call_does_not_create_replacement_run(db):
    store = legacy(db)
    store.enqueue(req("调整范围","scope"),"t")
    service = DialogueService(db,Model([research("Adjusted")],hook=lambda:db.cancel_run("r")))
    complete(service)
    assert db.get_run("r").status == RunStatus.CANCELLED and len(db.list_runs("t")) == 1
    assert turn_answer(store,"t").status == "failed"


def test_running_supplement_pauses_after_saved_external_result(db):
    store = legacy(db)
    model = Model([{"queries":["all:old","all:more"],"subproblems":["old"]},research("Adjusted")])
    class Search:
        calls = 0
        async def search(self,query,**kwargs):
            await kwargs["on_request"]()
            self.calls += 1
            store.enqueue(req("补充新方向","scope"),"t")
            assert db.get_run("r").status == RunStatus.PAUSE_REQUESTED
            return [Paper(id="p",source_id="p",title="Fetched",year=2024,url="https://arxiv.org/abs/p")]
    search = Search()
    engine = WorkflowEngine(db,llm_adapter=model,arxiv_adapter=search)
    async def scenario():
        result = await engine.execute_run("r")
        assert result.status == RunStatus.PAUSED and result.query_index == 1
        assert search.calls == 1 and db.get_papers_by_run("r")[0].title == "Fetched"
        await DialogueService(db,model).process(store.next_turn())
    asyncio.run(scenario())
    assert db.get_run("r").status == RunStatus.QUEUED
    assert db.list_run_messages("r")[0].content == "补充新方向"


@pytest.mark.parametrize("change", [{"run_id":"foreign"},{"paper_id":"foreign"},{"source_text_id":"unknown"},{"page_number":3},{"source_type":"abstract"},{"source_url":"https://evil.example"},{"quote":"fabricated"},{"location_start":1},{"quote":"xx","location_start":3000,"location_end":3002}])
def test_fabricated_foreign_or_out_of_context_citations_rejected(db,change):
    store = citation_db(db)
    service = DialogueService(db,Model([{"action":"answer","content":"结论","citations":[citation(**change)]}]))
    store.enqueue(req("解释这篇","answer","ask"),"t")
    complete(service)
    assert turn_answer(store,"t").status == "failed"
    assert not turn_answer(store,"t").citations
    assert len(db.list_runs("t")) == 1


def test_valid_saved_snapshot_answer_restores_only_owned_existing_research(db):
    store = citation_db(db)
    db.create_run(Run(id="active",task_id="t",initial_topic="Original"))
    model = Model([{"action":"answer","content":"该页原文为 Literal evidence.","citations":[citation()]}])
    service = DialogueService(db,model)
    store.enqueue(req("已有资料怎么说","answer","ask"),"t")
    complete(service)
    answer = turn_answer(store,"t")
    assert answer.status == "completed" and answer.citations[0].quote == "Literal evidence."
    assert "语义支持尚未核验" in answer.content
    assert db.get_run("active").status == RunStatus.QUEUED and len(db.list_runs("t")) == 2
    assert db.list_queries("active") == [] and "原先正在进行的研究在检查点后继续" in answer.content
    context = model.requests[0]["sources"][0]
    assert context["truncated"] and context["original_length"] > len(context["content"])


def test_unselected_paper_cannot_supply_answer_citation(db):
    store = citation_db(db,selected=False)
    model = Model([{"action":"answer","content":"结论","citations":[citation()]}])
    store.enqueue(req("解释","answer","ask"),"t")
    complete(DialogueService(db,model))
    assert model.requests[0]["sources"] == [] and turn_answer(store,"t").status == "failed"


@pytest.mark.parametrize("mode,decision", [("ask",research()),("research",{"action":"answer","content":"不研究"}),("auto",{"action":"research","content":"坏范围","task_input":{"topic":"x","start_year":2026,"end_year":2020}})])
def test_model_intent_and_scope_boundary_has_no_generic_success(db,mode,decision):
    store = legacy(db)
    store.enqueue(req("input","intent",mode),"t")
    complete(DialogueService(db,Model([decision])))
    assert turn_answer(store,"t").status == "failed"
    assert db.get_run("r").status == RunStatus.PAUSED and not db.list_run_messages("r")


def test_terminal_new_research_preserves_old_run_and_transcript(db):
    store = legacy(db,RunStatus.PARTIAL)
    before = store.view("t",False).messages
    store.enqueue(req("New topic","new","research"),"t")
    complete(DialogueService(db))
    runs = db.list_runs("t")
    assert len(runs) == 2 and runs[0].initial_input.topic == "Original"
    assert runs[1].initial_input.topic == "New topic"
    assert db.get_task("t").topic == "New topic"
    assert store.messages("t")[:len(before)] == before


@pytest.mark.parametrize("limit", ["calls","seconds"])
def test_cumulative_dialogue_budget_blocks_model_without_touching_run_budget(db,limit):
    store = legacy(db)
    store.ensure("t")
    usage = store.usage("t")
    if limit == "calls": usage.model_calls=usage.max_calls
    else: usage.total_execution_seconds=usage.max_seconds
    store.save_usage("t",usage)
    model = Model([])
    store.enqueue(req("input","budget"),"t")
    complete(DialogueService(db,model))
    assert not model.requests and turn_answer(store,"t").error_category == "conversation_budget_exhausted"
    assert db.get_run("r").total_calls == 0 and db.get_run("r").status == RunStatus.PAUSED


def test_timeout_and_failed_call_usage_unknown_is_not_zero(db):
    store = legacy(db)
    store.ensure("t")
    usage = store.usage("t"); usage.max_seconds=0.01; store.save_usage("t",usage)
    class Waiting:
        async def generate(self,*args,**kwargs):
            await asyncio.Event().wait()
    store.enqueue(req("input","timeout"),"t")
    complete(DialogueService(db,Waiting()))
    assert turn_answer(store,"t").status == "failed"
    assert store.usage("t").model_calls == 1
    assert store.usage("t").total_execution_seconds >= 0.01
    assert all(v is None for v in store.usage("t").token_usage.values())


def test_failed_adapter_usage_is_counted_and_later_unknown_remains_unknown(db):
    store = legacy(db)
    model = Model([LLMError("invalid_json","redacted",usage=LLMUsage(prompt_tokens=2,total_tokens=5)),LLMError("timeout","redacted")])
    service = DialogueService(db,model)
    for i in range(2):
        store.enqueue(req("input",str(i)),"t")
        complete(service)
        assert turn_answer(store,"t").status == "failed"
        if i == 0:
            assert store.usage("t").token_usage["total_tokens"] == 5
    assert store.usage("t").model_calls == 2 and store.usage("t").token_usage["total_tokens"] is None


def test_shutdown_interrupts_processing_turn_without_replay(db):
    store = legacy(db)
    store.enqueue(req("input","shutdown"),"t")
    async def scenario():
        started = asyncio.Event()
        class Waiting:
            async def generate(self,*args,**kwargs):
                started.set()
                await asyncio.Event().wait()
        service = DialogueService(db,Waiting())
        job = asyncio.create_task(service.process(store.next_turn()))
        await started.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError): await job
    asyncio.run(scenario())
    assert turn_answer(store,"t").status == "interrupted" and store.next_turn() is None
    assert store.usage("t").model_calls == 1 and db.get_run("r").status == RunStatus.PAUSED


def test_program_fault_persists_category_and_rolls_back_state_decision(db,monkeypatch):
    store = legacy(db)
    store.enqueue(req("input","fault"),"t")
    def broken(*args):
        raise KeyError("private raw text must not appear")
    monkeypatch.setattr(db,"transition",broken)
    with pytest.raises(KeyError):
        complete(DialogueService(db,Model([research("Adjusted")])))
    assert db.list_run_messages("r") == [] and db.get_run("r").status == RunStatus.PAUSED
    assert turn_answer(store,"t").error_category == "KeyError"
    assert "private raw text" not in turn_answer(store,"t").content


def test_worker_rechecks_dialogue_before_stale_queued_runs(db):
    db.create_task(Task(id="t1",topic="one")); db.create_task(Task(id="t2",topic="two"))
    db.create_run(Run(id="r1",task_id="t1",initial_topic="one")); db.create_run(Run(id="r2",task_id="t2",initial_topic="two"))
    order = []
    async def scenario():
        done = asyncio.Event()
        model = Model([{"action":"clarify","content":"需要澄清"}],hook=lambda:order.append("dialogue"))
        dialogue = DialogueService(db,model)
        class Engine:
            async def execute_run(self,run_id):
                order.append(run_id)
                db.transition(run_id,[RunStatus.QUEUED],RunStatus.FAILED)
                if run_id == "r1":
                    dialogue.store.enqueue(req("clarify","turn",create=True))
                else: done.set()
        worker = SerialWorker(db,Engine(),dialogue)
        job = asyncio.create_task(worker.serve())
        await done.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError): await job
    asyncio.run(scenario())
    assert order == ["r1","dialogue","r2"]


@pytest.mark.parametrize("status", [RunStatus.PAUSED,RunStatus.NEEDS_INPUT])
def test_answer_never_restores_manual_pause_or_needs_input(db,status):
    store = citation_db(db)
    db.create_run(Run(id="active",task_id="t",initial_topic="Original",status=status))
    service = DialogueService(db,Model([{"action":"answer","content":"来自旧来源","run_id":"r","citations":[citation()]}]))
    store.enqueue(req("answer","manual","ask"),"t")
    complete(service)
    assert turn_answer(store,"t").status == "completed"
    assert db.get_run("active").status == status


def test_answer_selected_old_run_restores_original_owned_active_run(db):
    store = citation_db(db)
    db.create_run(Run(id="active",task_id="t",initial_topic="Original"))
    store.enqueue(req("answer","selected","ask"),"t")
    complete(DialogueService(db,Model([{"action":"answer","content":"旧来源","run_id":"r","citations":[citation()]}])))
    assert db.get_run("active").status == RunStatus.QUEUED
    assert turn_answer(store,"t").run_id == "r"


def test_answer_manual_pause_during_call_revokes_owned_restoration(db):
    store = citation_db(db)
    db.create_run(Run(id="active",task_id="t",initial_topic="Original"))
    store.enqueue(req("answer","manual","ask"),"t")
    complete(DialogueService(db,Model([{"action":"answer","content":"旧来源","citations":[citation()]}],hook=lambda:db.pause_run("active"))))
    assert db.get_run("active").status == RunStatus.PAUSED


def test_real_foreign_source_snapshot_and_non_ok_source_are_excluded(db):
    store = citation_db(db)
    db.create_task(Task(id="foreign",topic="Foreign"))
    db.create_run(Run(id="foreign-run",task_id="foreign",initial_topic="Foreign"))
    db.save_papers(db.get_papers_by_run("r"),"foreign-run")
    db.save_source_texts([SourceText(id="foreign-source",paper_id="p",source_type=SourceType.FULLTEXT,page_number=2,
        source_url="https://arxiv.org/pdf/p",content="Literal evidence.")],"foreign-run")
    db.save_source_texts([SourceText(id="failed-source",paper_id="p",source_type=SourceType.FULLTEXT,page_number=2,
        source_url="https://arxiv.org/pdf/p",content="Literal evidence.",status="parse_failed")],"r")
    for i,c in enumerate((citation(run_id="foreign-run",source_text_id="foreign-source"),citation(source_text_id="failed-source"))):
        model = Model([{"action":"answer","content":"claim","citations":[c]}])
        store.enqueue(req("answer",str(i),"ask"),"t")
        complete(DialogueService(db,model))
        assert turn_answer(store,"t").status == "failed"
        assert {s["source_text_id"] for s in model.requests[0]["sources"]} == {"s"}


def test_single_model_call_timeout_cap_and_pending_history(db,monkeypatch):
    store = legacy(db,RunStatus.PAUSED)
    db.save_run_message(RunMessage(id="pending",run_id="r",content="original pending supplement"))
    store.enqueue(req("clarify","bounded"),"t")
    model = Model([{"action":"clarify","content":"需要澄清"}])
    original = asyncio.wait_for
    timeouts = []
    async def observe(operation, timeout):
        timeouts.append(timeout)
        return await original(operation,timeout=timeout)
    monkeypatch.setattr(asyncio,"wait_for",observe)
    complete(DialogueService(db,model))
    assert len(model.requests) == 1 and 0 < timeouts[0] <= 60
    assert model.requests[0]["pending_supplements"][0]["content"] == "original pending supplement"
    assert db.list_run_messages("r")[0].status == "pending"
    assert store.usage("t").total_execution_seconds > 0



def test_invalid_legacy_task_without_runs_can_be_viewed_without_revalidation(client):
    db = client.app.state.db
    db.create_task(Task(id="invalid-legacy",topic="",start_year=2026,end_year=2020,focus_dimensions=[""]))
    response = client.get("/api/conversations/invalid-legacy")
    assert response.status_code == 200
    view = response.json()
    assert view["task"]["topic"] == "" and view["task"]["focus_dimensions"] == [""]
    assert view["task"]["start_year"] == 2026 and view["task"]["end_year"] == 2020
    assert not view["runs"] and not view["busy"]
    assert len(view["messages"]) == 1 and view["messages"][0]["role"] == "user"
    assert '原始问题：""' in view["messages"][0]["content"]
    assert "未按当前规则校验" in view["messages"][0]["content"]
    assert client.get("/api/conversations/invalid-legacy").json() == view
    assert db.get_task("invalid-legacy").topic == "" and not db.list_runs("invalid-legacy")



def test_stop_queued_turn_before_any_paid_call_and_stale_worker_claim(db):
    model = Model([])
    service = DialogueService(db,model)
    tid = service.store.enqueue(req(create=True))
    stale = service.store.next_turn()
    service.store.stop(tid)
    asyncio.run(service.process(stale))
    assert not model.requests and service.store.usage(tid).model_calls == 0
    assert service.store.next_turn() is None and not service.store.pending(tid)
    assert service.store.message(stale["user_id"]).content == "Agents"
    answer = service.store.message(stale["assistant_id"])
    assert answer.status == "interrupted" and answer.error_category == "user_cancelled"
    assert "用户已停止本轮对话" in answer.content
    assert service.store.enqueue(req(create=True)) == tid and service.store.next_turn() is None


def test_stop_inflight_model_research_result_never_creates_run_and_preserves_usage(db):
    service = DialogueService(db)
    tid = service.store.enqueue(req(create=True))
    old_turn = service.store.next_turn()
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class Waiting:
            async def generate(self,*args,**kwargs):
                started.set()
                await release.wait()
                output = research("Late paid result")
                return LLMResponse(content=json.dumps(output),parsed_json=output,usage=LLMUsage(prompt_tokens=3,completion_tokens=4,total_tokens=7))
        service.llm = Waiting()
        job = asyncio.create_task(service.process(old_turn))
        await started.wait()
        service.store.stop(tid)
        stopped = service.store.message(old_turn["assistant_id"])
        # stop 解除了旧对话占位；新消息仍在同一串行 worker 后续队列等待。
        service.store.enqueue(req("New direction","new-after-stop"),tid)
        new_turn = service.store.next_turn()
        release.set()
        await job
        assert service.store.message(old_turn["assistant_id"]) == stopped
        assert service.store.message(new_turn["assistant_id"]).status == "queued"
    asyncio.run(scenario())
    assert db.list_runs(tid) == [] and db.get_task(tid).topic == "Agents"
    assert service.store.usage(tid).model_calls == 1
    assert service.store.usage(tid).token_usage["total_tokens"] == 7
    assert service.store.usage(tid).total_execution_seconds > 0


@pytest.mark.parametrize("completion", ["error","shutdown"])
def test_stop_inflight_late_error_or_shutdown_preserves_user_cancelled(db,completion):
    service = DialogueService(db)
    tid = service.store.enqueue(req(create=True))
    turn = service.store.next_turn()
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class Waiting:
            async def generate(self,*args,**kwargs):
                started.set()
                await release.wait()
                raise LLMError("timeout","service raw error",usage=LLMUsage(prompt_tokens=2,total_tokens=5))
        service.llm = Waiting()
        job = asyncio.create_task(service.process(turn))
        await started.wait()
        service.store.stop(tid)
        stopped = service.store.message(turn["assistant_id"])
        if completion == "shutdown":
            job.cancel()
            with pytest.raises(asyncio.CancelledError): await job
        else:
            release.set()
            await job
        assert service.store.message(turn["assistant_id"]) == stopped
    asyncio.run(scenario())
    assert service.store.message(turn["assistant_id"]).error_category == "user_cancelled"
    assert service.store.usage(tid).model_calls == 1 and not db.list_runs(tid)
    if completion == "error": assert service.store.usage(tid).token_usage["total_tokens"] == 5
    else: assert service.store.usage(tid).token_usage["total_tokens"] is None


def test_stop_blocks_apply_and_finish_even_after_decision_race(db):
    from backend.app.domain.conversation import DialogueDecision
    service = DialogueService(db)
    tid = service.store.enqueue(req(create=True))
    turn = service.store.next_turn()
    assert service.store.claim(turn)
    decision = DialogueDecision.model_validate(research("Unwanted run"))
    service.store.stop(tid)
    stopped = service.store.message(turn["assistant_id"])
    service.apply(turn,decision)
    service.store.finish(turn,decision)
    assert service.store.message(turn["assistant_id"]) == stopped
    assert not db.list_runs(tid) and db.get_task(tid).topic == "Agents"


def test_stop_api_cancels_active_run_and_is_idempotent_without_model(client):
    db = client.app.state.db
    legacy(db)
    response = client.post("/api/conversations/t/messages",json={"content":"adjust","request_id":"pending"})
    assert response.status_code == 202 and response.json()["busy"]
    assert db.get_run("r").status == RunStatus.PAUSED
    stopped = client.post("/api/conversations/t/stop")
    assert stopped.status_code == 200
    view = stopped.json()
    assert not view["busy"] and view["runs"][0]["status"] == "cancelled"
    assert view["usage"]["model_calls"] == 0
    interrupted = [m for m in view["messages"] if m["error_category"] == "user_cancelled"]
    assert len(interrupted) == 1 and interrupted[0]["status"] == "interrupted"
    assert client.post("/api/conversations/t/stop").json() == view
    assert client.post("/api/conversations/missing/stop").status_code == 404


def test_stop_api_initial_router_without_run_can_stop_and_retry_safely(client):
    payload = {"content":"Initial expensive intent","request_id":"initial-stop"}
    initial = client.post("/api/conversations",json=payload).json()
    tid = initial["task"]["id"]
    stopped = client.post(f"/api/conversations/{tid}/stop")
    assert stopped.status_code == 200
    view = stopped.json()
    assert not view["runs"] and not view["busy"]
    assert view["messages"][0]["content"] == payload["content"]
    assert view["messages"][1]["status"] == "interrupted"
    assert client.post("/api/conversations",json=payload).json() == view
    assert client.post(f"/api/conversations/{tid}/stop").json() == view
