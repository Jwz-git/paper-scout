"""会话管理与多模型配置的实际状态、迁移、凭据和失败边界。"""
import json

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.storage.conversations import ConversationStore


def provider(name='供应商 A', model='offline-a', key='artificial-key-a'):
    return {'name': name, 'protocol': 'openai_chat', 'base_url': 'https://offline.example/v1',
            'models': [model], 'api_key': key}


def test_rename_does_not_change_research_scope(client):
    task = client.post('/api/conversations', json={'content': 'original question', 'request_id': 'rename'}).json()['task']
    run = client.app.state.db.agent_run(task['id'])
    renamed = client.post(f"/api/conversations/{task['id']}/rename", json={'title': ' New label '})
    assert renamed.status_code == 200
    assert renamed.json()['title'] == 'New label' and renamed.json()['topic'] == 'original question'
    assert client.get(f"/api/runs/{run.id}").json()['initial_topic'] == 'original question'
    assert client.get('/api/conversations').json()[0]['title'] == 'New label'
    assert client.post(f"/api/conversations/{task['id']}/rename", json={'title': ' '}).status_code == 422


def test_trash_stops_work_hides_history_and_restore_keeps_messages(client):
    payload = {'content': 'offline question', 'request_id': 'create-before-trash'}
    first = client.post('/api/conversations', json=payload).json()
    tid = first['task']['id']
    before = len(first['messages'])
    assert client.post(f'/api/conversations/{tid}/trash').status_code == 200
    assert client.post(f'/api/conversations/{tid}/trash').status_code == 200
    assert not client.get('/api/conversations').json()
    assert client.get('/api/conversations?deleted=true').json()[0]['id'] == tid
    assert client.get(f'/api/conversations/{tid}').status_code == 404
    assert client.post('/api/conversations', json=payload).status_code == 409
    assert client.post(f'/api/conversations/{tid}/messages', json={'content': 'should not run', 'request_id': 'deleted'}).status_code == 404
    restored = client.post(f'/api/conversations/{tid}/restore')
    assert restored.status_code == 200 and restored.json()['deleted_at'] is None
    view = client.get(f'/api/conversations/{tid}').json()
    assert len(view['messages']) == before and not view['busy']
    assert view['messages'][-1]['status'] == 'interrupted'
    assert client.post('/api/conversations', json=payload).json()['task']['id'] == tid


def test_late_result_cannot_resurrect_trashed_conversation(client):
    result = client.post('/api/conversations', json={'content': 'offline', 'request_id': 'late'}).json()
    store = ConversationStore(client.app.state.db)
    turn = store.next_turn(); store.claim(turn)
    tid = result['task']['id']
    client.post(f'/api/conversations/{tid}/trash')
    store.finish(turn, content='late result must not replace stopped message')
    assert 'late result' not in store.messages(tid)[-1].content
    assert not client.get('/api/conversations').json()


def test_providers_share_one_key_across_models_and_delete_does_not_switch(client):
    a = client.post('/api/settings/providers', json={**provider(), 'models': ['a-1', 'a-2']}).json()
    aid = a['provider_id']
    assert not a['settings']['enabled']
    client.post('/api/settings/selection', json={'provider_id': aid, 'model': 'a-1'})
    b = client.post('/api/settings/providers', json=provider('供应商 B', 'b', 'artificial-key-b')).json()
    bid = b['provider_id']
    public = client.get('/api/settings')
    assert 'artificial-key-a' not in public.text and 'artificial-key-b' not in public.text
    assert len(public.json()['providers']) == 2 and public.json()['active_provider_id'] == aid
    assert client.post('/api/settings/selection', json={'provider_id': aid, 'model': 'a-2'}).status_code == 200
    assert client.app.state.agent.llm.model == 'a-2'
    assert client.post('/api/settings/selection', json={'provider_id': bid, 'model': 'b'}).status_code == 200
    assert client.app.state.agent.llm._api_key == 'artificial-key-b'
    updated = {**provider('供应商 B 改名', 'b', None), 'models': ['b', 'b-2']}
    assert client.post(f'/api/settings/providers/{bid}', json=updated).status_code == 200
    assert client.app.state.agent.llm._api_key == 'artificial-key-b'
    assert client.post('/api/settings/selection', json={'provider_id': bid, 'model': 'foreign'}).status_code == 422
    deleted = client.post(f'/api/settings/providers/{bid}/delete').json()
    assert not deleted['enabled'] and deleted['active_provider_id'] is None
    assert any(p['id'] == aid for p in deleted['providers'])
    assert client.app.state.agent.llm is None


def test_inactive_provider_can_be_saved_during_work_but_current_cannot(client):
    a = client.post('/api/settings/providers', json=provider()).json()['provider_id']
    client.post('/api/settings/selection', json={'provider_id': a, 'model': 'offline-a'})
    adapter = client.app.state.agent.llm
    task = client.post('/api/conversations', json={'content': 'offline', 'request_id': 'busy'}).json()['task']
    b = client.post('/api/settings/providers', json=provider('供应商 B', 'offline-b', None))
    assert b.status_code == 200
    bid = b.json()['provider_id']
    assert client.app.state.agent.llm is adapter
    assert client.post('/api/settings/selection', json={'provider_id': bid, 'model': 'offline-b'}).status_code == 409
    assert client.post(f'/api/settings/providers/{a}', json=provider()).status_code == 409
    assert client.post(f'/api/settings/providers/{a}/delete').status_code == 409
    client.post(f"/api/conversations/{task['id']}/stop")
    assert client.post('/api/settings/selection', json={'provider_id': bid, 'model': 'offline-b'}).status_code == 200
    assert client.app.state.agent.llm._api_key == ''


def test_legacy_single_model_is_preserved_until_next_save(tmp_path):
    old = {'enabled': True, 'protocol': 'openai_responses', 'base_url': 'https://legacy.example/v1',
           'model': 'legacy-model', 'api_key': 'artificial-legacy-key'}
    path = tmp_path / 'model-settings.json'; path.write_text(json.dumps(old))
    cfg = Settings(_env_file=None, data_dir=tmp_path, llm_base_url='', llm_model='', llm_api_key='')
    with TestClient(create_app(config=cfg, run_worker=False)) as client:
        settings = client.get('/api/settings').json()
        assert settings['providers'][0]['models'] == ['legacy-model']
        assert json.loads(path.read_text()) == old
        assert client.post('/api/settings/providers', json=provider()).status_code == 200
        saved = json.loads(path.read_text())
        assert saved['providers'][0]['api_key'] == old['api_key']
        assert 'profiles' not in saved
    with TestClient(create_app(config=cfg, run_worker=False)) as client:
        assert len(client.get('/api/settings').json()['providers']) == 2
        assert client.app.state.agent.llm.model == 'legacy-model'


def test_provider_address_change_and_validation_never_echo_keys(client):
    saved = client.post('/api/settings/providers', json=provider()).json()['provider_id']
    changed = {**provider(key=None), 'base_url': 'https://new.example/v1'}
    assert client.post(f'/api/settings/providers/{saved}', json=changed).status_code == 422
    response = client.post('/api/settings/providers', json={**provider(), 'api_key': {'value': 'artificial-secret'}})
    assert response.status_code == 422 and 'artificial-secret' not in response.text
    assert client.post('/api/settings/providers', json=provider(), headers={'Origin': 'https://evil.example'}).status_code == 403
