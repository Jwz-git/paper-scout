"""离线回归：对话消息的排队、幂等、持久化、停止和旧数据展示。无真实外部请求。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.agent.service import AgentService
from backend.app.domain.conversation import ConversationCreateRequest, ConversationMessageRequest
from backend.app.domain.models import Run, RunStatus, Task
from backend.app.storage.conversations import ConversationStore
from backend.app.storage.database import Database
from tests.agent_fakes import Model, Pdf, Search, answer, reply


def req(content="Agents", key="one", mode="auto", create=False):
    cls = ConversationCreateRequest if create else ConversationMessageRequest
    return cls(content=content, request_id=key, mode=mode)


@pytest.fixture
def db():
    store = Database(":memory:")
    yield store
    store.close()


def test_api_enqueues_pairs_idempotently_and_accepts_messages_while_busy(client):
    body = {"content": "Agents", "request_id": "create-1"}
    response = client.post("/api/conversations", json=body)
    assert response.status_code == 202
    view = response.json()
    assert set(view) == {"task", "messages", "runs", "usage", "busy", "model_configured"}
    assert view["runs"] == [] and view["busy"] and not view["model_configured"]
    assert [m["role"] for m in view["messages"]] == ["user", "assistant"]
    assert all(m["status"] == "queued" for m in view["messages"])
    assert client.post("/api/conversations", json=body).json() == view
    assert client.post("/api/conversations", json={**body, "content": "Changed"}).status_code == 409
    tid = view["task"]["id"]
    assert client.get("/api/conversations").json()[0]["id"] == tid
    # 执行中发送的消息排在后面，由 agent 在下一步并入。
    follow = {"content": "more", "request_id": "follow"}
    one = client.post(f"/api/conversations/{tid}/messages", json=follow)
    assert one.status_code == 202 and [m["content"] for m in one.json()["messages"]] == ["Agents", "", "more", ""]
    assert client.post(f"/api/conversations/{tid}/messages", json=follow).json() == one.json()
    assert client.post(f"/api/conversations/{tid}/messages", json={**follow, "mode": "ask"}).status_code == 409
    assert client.get("/api/conversations/missing").status_code == 404


@pytest.mark.parametrize("body", [{"content": " ", "request_id": "a"}, {"content": "a"}, {"content": "a", "request_id": ""},
                                  {"content": "a", "request_id": "a", "mode": "execute"}, {"content": "x" * 2001, "request_id": "a"}])
def test_api_input_boundary(client, body):
    assert client.post("/api/conversations", json=body).status_code == 422


def test_persistence_pairing_idempotency_and_interruption(tmp_path):
    path = tmp_path / "conversation.db"
    db = Database(path)
    store = ConversationStore(db)
    tid = store.enqueue(req(create=True))
    store.claim(store.next_turn())
    other = store.enqueue(req("Other", "two", create=True))
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


def test_simultaneous_retries_create_one_conversation_and_one_message(db):
    store = ConversationStore(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: store.enqueue(req(create=True)), range(2)))
    assert ids[0] == ids[1] and len(db.list_tasks()) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: store.enqueue(req("new", "follow"), ids[0]), range(2)))
    assert [m.content for m in store.messages(ids[0]) if m.role == "user"] == ["Agents", "new"]


def test_usage_from_earlier_turns_is_statistics_not_a_limit(db):
    service = AgentService(db, Model([reply("需要哪方面？")]), arxiv=Search([]), pdf=Pdf())
    tid = service.store.enqueue(req(create=True))
    usage = service.store.usage(tid)
    usage.model_calls = 1000
    service.store.save_usage(tid, usage)
    run = db.agent_run(tid)
    run.total_calls = 1000
    db.update_run(run)
    asyncio.run(service.process(service.store.next_turn()))
    assert answer(service.store, tid).content == "需要哪方面？"
    assert service.store.usage(tid).model_calls == 1001 and db.agent_run(tid).total_calls == 1001


def test_stopped_turn_is_never_claimed_or_charged(db):
    model = Model([])
    service = AgentService(db, model, arxiv=Search([]), pdf=Pdf())
    tid = service.store.enqueue(req(create=True))
    stale = service.store.next_turn()
    service.store.stop(tid)
    asyncio.run(service.process(stale))
    assert not model.requests and service.store.usage(tid).model_calls == 0 and db.list_runs(tid) == []
    assert service.store.next_turn() is None and not service.store.pending(tid)
    assert service.store.message(stale["user_id"]).content == "Agents"
    stopped = service.store.message(stale["assistant_id"])
    assert stopped.status == "interrupted" and stopped.error_category == "user_cancelled" and stopped.content == "已停止。"
    assert service.store.enqueue(req(create=True)) == tid and service.store.next_turn() is None


def test_stop_api_interrupts_every_queued_message_and_is_idempotent(client):
    payload = {"content": "Initial question", "request_id": "initial-stop"}
    tid = client.post("/api/conversations", json=payload).json()["task"]["id"]
    client.post(f"/api/conversations/{tid}/messages", json={"content": "more", "request_id": "more"})
    stopped = client.post(f"/api/conversations/{tid}/stop")
    assert stopped.status_code == 200
    view = stopped.json()
    assert not view["runs"] and not view["busy"] and view["usage"]["model_calls"] == 0
    assert [(m["content"], m["status"]) for m in view["messages"]] == [
        ("Initial question", "completed"), ("已停止。", "interrupted"), ("more", "completed"), ("已停止。", "interrupted")]
    assert client.post("/api/conversations", json=payload).json() == view
    assert client.post(f"/api/conversations/{tid}/stop").json() == view
    assert client.post("/api/conversations/missing/stop").status_code == 404


def test_legacy_task_shows_its_original_scope_and_why_old_runs_stopped(db):
    db.create_task(Task(id="t", topic="Original", start_year=2022, focus_dimensions=["methods"]))
    db.create_run(Run(id="r", task_id="t", initial_topic="Original", status=RunStatus.PAUSED))
    store = ConversationStore(db)
    first = store.view("t", False).messages
    assert first[0].content.startswith("Original") and "methods" in first[0].content and "原始范围" in first[0].content
    assert first[-1].content.startswith("研究已暂停")
    db.interrupt_running()
    messages = store.view("t", False).messages
    assert len(messages) == len(first) + 1 and messages[-1].content.startswith("研究已中断")
    assert "旧运行不再继续" in messages[-1].content
    assert store.view("t", False).messages == messages


def test_invalid_legacy_task_without_runs_can_be_viewed_without_revalidation(client):
    db = client.app.state.db
    db.create_task(Task(id="invalid-legacy", topic="", start_year=2026, end_year=2020, focus_dimensions=[""]))
    response = client.get("/api/conversations/invalid-legacy")
    assert response.status_code == 200
    view = response.json()
    assert view["task"]["topic"] == "" and view["task"]["focus_dimensions"] == [""]
    assert view["task"]["start_year"] == 2026 and view["task"]["end_year"] == 2020
    assert not view["runs"] and not view["busy"]
    assert len(view["messages"]) == 1 and view["messages"][0]["role"] == "user"
    assert '原始问题：""' in view["messages"][0]["content"]
    assert client.get("/api/conversations/invalid-legacy").json() == view
    assert db.get_task("invalid-legacy").topic == "" and not db.list_runs("invalid-legacy")
