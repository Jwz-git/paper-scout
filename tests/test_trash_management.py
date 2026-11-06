"""回收站不可逆删除的边界：事务、共享来源、在途请求及全量操作。"""
from datetime import datetime, timedelta, timezone
import asyncio
import time
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient
from backend.app.adapters.llm import LLMResponse
from backend.app.config import Settings
from backend.app.agent.service import AgentService
from backend.app.domain.models import Task, Run, Paper, SourceText, SourceType, Evidence, Report
from backend.app.main import create_app
from backend.app.storage.database import Database


def test_trash_search_sort_pagination_and_restore_all_beyond_100(client):
    db = client.app.state.db
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(105):
        db.create_task(Task(id=f"t-{index:03}", topic=f"人工问题 {index}",
                            title="literal % match" if index == 0 else f"Label {index:03}",
                            deleted_at=start + timedelta(minutes=index)))
    newest = client.get('/api/conversations/trash?limit=50').json()
    assert newest['total'] == newest['matched'] == 105
    assert len(newest['items']) == 50 and newest['items'][0]['id'] == 't-104'
    last = client.get('/api/conversations/trash?offset=100&limit=50').json()
    assert len(last['items']) == 5
    assert client.get('/api/conversations/trash?sort=oldest').json()['items'][0]['id'] == 't-000'
    filtered = client.get('/api/conversations/trash', params={'query': '%'}).json()
    assert filtered['matched'] == 1 and filtered['total'] == 105  # 搜索百分号不是通配符。
    assert client.get('/api/conversations/trash?query=label&sort=title').json()['items'][0]['id'] == 't-001'
    restored = client.post('/api/conversations/trash/restore', json={'ids': None})
    assert restored.status_code == 200 and len(restored.json()['tasks']) == 105
    assert client.get('/api/conversations/trash').json()['total'] == 0
    assert all(task.deleted_at is None for task in db.list_tasks(200))


def test_active_conversation_list_pages_and_searches_beyond_first_page(client):
    db = client.app.state.db
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(105):
        db.create_task(Task(id=f"a-{index:03}", topic=f"人工问题 {index}",
                            title="Needle % title" if index == 0 else None, updated_at=start + timedelta(minutes=index)))
    first = client.get('/api/conversations', params={'limit': 100}).json()
    rest = client.get('/api/conversations', params={'limit': 100, 'offset': 100}).json()
    assert [t['id'] for t in first][:2] == ['a-104', 'a-103'] and len(rest) == 5
    assert {t['id'] for t in first} | {t['id'] for t in rest} == {f"a-{i:03}" for i in range(105)}
    assert [t['id'] for t in client.get('/api/conversations', params={'query': 'needle %'}).json()] == ['a-000']
    assert [t['id'] for t in client.get('/api/conversations', params={'query': '问题 7'}).json()][-1] == 'a-007'


def test_batch_conflict_is_atomic_and_only_trash_can_be_deleted(client):
    db = client.app.state.db
    db.create_task(Task(id='trash', topic='deleted', deleted_at=datetime.now(timezone.utc)))
    db.create_task(Task(id='live', topic='keep'))
    for action in ('restore', 'delete'):
        assert client.post(f'/api/conversations/trash/{action}', json={'ids': ['trash', 'live']}).status_code == 409
        assert db.get_task('trash').deleted_at is not None and db.get_task('live') is not None
        assert client.post(f'/api/conversations/trash/{action}', json={'ids': []}).status_code == 422
        assert client.post(f'/api/conversations/trash/{action}', json={}).status_code == 422


def test_permanent_delete_removes_related_records_and_preserves_shared_sources(client):
    db = client.app.state.db
    created = client.post('/api/conversations', json={'content': 'artificial', 'request_id': 'delete-fixture'}).json()
    tid = created['task']['id']
    other = Task(id='keep', topic='keep'); db.create_task(other)
    for task_id, run_id in ((tid, 'r-delete'), ('keep', 'r-keep')):
        db.create_run(Run(id=run_id, task_id=task_id, initial_topic='artificial'))
    shared = Paper(id='shared', title='人工共享论文', source_id='shared', url='https://example.com/shared')
    private = Paper(id='private', title='人工独有论文', source_id='private', url='https://example.com/private')
    db.save_papers([shared, private], 'r-delete'); db.save_papers([shared], 'r-keep')
    for paper in (shared, private):
        source = SourceText(id=f's-{paper.id}', paper_id=paper.id, source_type=SourceType.ABSTRACT, content='quote')
        db.save_source_texts([source], 'r-delete')
        db.save_evidence([Evidence(id=f'e-{paper.id}', source_text_id=source.id, paper_id=paper.id,
                                  quote='quote', location_start=0, location_end=5)])
    with db._get_connection() as conn:
        conn.execute("INSERT INTO run_sources VALUES('r-keep','s-shared')")
        for table in ('events', 'search_queries', 'assessments'):
            conn.execute(f"INSERT INTO {table} VALUES(?, 'r-delete', '{{}}')", (f'fixture-{table}',))
        conn.execute("INSERT INTO run_messages(id,run_id,content,status,created_at) VALUES('m','r-delete','artificial','applied',?)",
                     (datetime.now(timezone.utc).isoformat(),))
    db.save_report(Report(id='report', run_id='r-delete', title='人工报告', content_markdown='fixture'))
    client.post(f'/api/conversations/{tid}/trash')
    assert client.post('/api/conversations/trash/delete', json={'ids': [tid]}).json()['ids'] == [tid]
    assert db.get_task(tid) is None and db.get_run('r-delete') is None
    assert client.get(f'/api/conversations/{tid}').status_code == 404
    assert client.post(f'/api/conversations/{tid}/restore').status_code == 404
    assert db.get_papers_by_run('r-keep')[0].id == 'shared'
    assert db.get_source_texts('shared', 'r-keep')[0].content == 'quote'
    assert db.get_evidence('shared', 'r-keep')[0].quote == 'quote'
    with db._get_connection() as conn:
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        assert not conn.execute("SELECT 1 FROM papers WHERE id='private'").fetchone()
        assert not conn.execute("SELECT 1 FROM conversation_turns WHERE task_id=?", (tid,)).fetchone()
        assert not conn.execute("SELECT 1 FROM chat_messages WHERE task_id=?", (tid,)).fetchone()
        assert not conn.execute("SELECT 1 FROM conversation_usage WHERE task_id=?", (tid,)).fetchone()
        for table in ('reports', 'run_messages', 'events', 'search_queries', 'assessments', 'conversation_run_states'):
            assert not conn.execute(f"SELECT 1 FROM {table} WHERE run_id='r-delete'").fetchone()


def test_delete_all_checks_inflight_target_before_deleting_any_record(client):
    db = client.app.state.db
    for index in range(105):
        db.create_task(Task(id=f't-{index:03}', topic='artificial', deleted_at=datetime.now(timezone.utc)))
    client.app.state.worker = SimpleNamespace(active_task_id='t-104')
    response = client.post('/api/conversations/trash/delete', json={'ids': None})
    assert response.status_code == 409
    assert client.get('/api/conversations/trash').json()['total'] == 105
    # 无关工作不阻止清理；所有页均被删除。
    client.app.state.worker.active_task_id = 'another-live-task'
    response = client.post('/api/conversations/trash/delete', json={'ids': None})
    assert response.status_code == 200 and len(response.json()['ids']) == 105
    assert client.get('/api/conversations/trash').json()['total'] == 0


def test_worker_holds_delete_until_the_stopped_turn_has_finished(tmp_path):
    started, released, finished = Event(), Event(), Event()

    class DelayedModel:
        async def generate(self, messages, **kwargs):
            started.set()
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, released.wait, 3)
            except asyncio.CancelledError:
                # 外部请求不会在取消的瞬间结束；本轮要等它返回、保存计数后才真正停止。
                await loop.run_in_executor(None, released.wait, 3)
                raise
            step = {"actions": [{"tool": "reply", "content": "late fixture", "evidence_ids": []}]}
            return LLMResponse(content=str(step), parsed_json=step)

    db = Database(tmp_path / 'worker.db')
    cfg = Settings(_env_file=None, llm_base_url='', llm_model='', llm_api_key='', data_dir=tmp_path)
    app = create_app(config=cfg, db=db, agent=AgentService(db, DelayedModel()))
    try:
        with TestClient(app) as client:
            process = app.state.agent.process

            async def observe(turn):
                try:
                    await process(turn)
                finally:
                    finished.set()

            app.state.agent.process = observe
            result = client.post('/api/conversations', json={'content': 'fixture', 'request_id': 'late-delete'}).json()
            tid = result['task']['id']
            assert started.wait(3) and app.state.worker.active_task_id == tid
            assert client.post(f'/api/conversations/{tid}/trash').status_code == 200
            assert client.post('/api/conversations/trash/delete', json={'ids': [tid]}).status_code == 409
            released.set()
            assert finished.wait(3)
            deadline = time.monotonic() + 3
            while app.state.worker.active_task_id is not None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert client.post('/api/conversations/trash/delete', json={'ids': [tid]}).status_code == 200
            assert db.get_task(tid) is None
    finally:
        released.set()
        db.close()
