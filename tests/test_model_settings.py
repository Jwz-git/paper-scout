"""定向验证配置热切换、持久化失败和凭据不回显；不访问外部模型。"""
import asyncio
import json
import stat
from contextlib import suppress

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.agent.worker import SerialWorker
from backend.app.domain.conversation import ConversationCreateRequest
from backend.app.main import create_app
from backend.app.model_settings import ModelSettingsService
from backend.app.storage.conversations import ConversationStore


PAYLOAD = {"enabled": True, "protocol": "openai_responses", "base_url": "https://offline.example/v1",
           "model": "offline-model", "api_key": "artificial-secret-value"}


def test_save_applies_to_the_agent_and_survives_restart(client):
    before = client.get('/api/settings')
    assert before.status_code == 200 and before.json()['source'] == 'environment'
    assert before.headers['cache-control'] == 'no-store'
    response = client.post('/api/settings', json=PAYLOAD)
    assert response.status_code == 200
    assert PAYLOAD['api_key'] not in response.text
    assert 'api_key' not in response.json() and response.json()['api_key_set']
    state = client.app.state
    assert state.agent.llm.model == 'offline-model'
    assert client.get('/api/health').json()['model_configured']
    path = state.model_settings.path
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())['providers'][0]['api_key'] == PAYLOAD['api_key']
    cfg = Settings(_env_file=None, data_dir=path.parent, llm_base_url='https://ignored.example/v1',
                   llm_model='ignored-model', llm_api_key='environment-secret')
    with TestClient(create_app(config=cfg, db=state.db, run_worker=False)) as restarted:
        current = restarted.get('/api/settings')
        assert current.json()['source'] == 'local'
        assert current.json()['model'] == 'offline-model'
        assert 'environment-secret' not in current.text and PAYLOAD['api_key'] not in current.text
        assert restarted.app.state.agent.llm._api_key == PAYLOAD['api_key']


def test_keep_replace_clear_and_disable(client):
    client.post('/api/settings', json=PAYLOAD)
    changed = {**PAYLOAD, 'api_key': None, 'model': 'second-model'}
    assert client.post('/api/settings', json=changed).status_code == 200
    assert client.app.state.agent.llm._api_key == PAYLOAD['api_key']
    assert client.post('/api/settings', json={**changed, 'api_key': 'replacement'}).status_code == 200
    assert client.app.state.agent.llm._api_key == 'replacement'
    clear = client.post('/api/settings', json={**changed, 'clear_api_key': True})
    assert clear.status_code == 200 and not clear.json()['api_key_set']
    disabled = client.post('/api/settings', json={**changed, 'enabled': False})
    assert disabled.status_code == 200 and not disabled.json()['enabled']
    assert client.app.state.agent.llm is None
    assert not client.get('/api/health').json()['model_configured']


def test_new_address_cannot_reuse_saved_credential_implicitly(client):
    client.post('/api/settings', json=PAYLOAD)
    old = client.app.state.agent.llm
    changed = {**PAYLOAD, 'base_url': 'https://other.example/v1', 'api_key': None}
    assert client.post('/api/settings', json=changed).status_code == 422
    assert client.app.state.agent.llm is old
    assert client.post('/api/settings', json={**changed, 'clear_api_key': True}).status_code == 200
    assert not client.get('/api/settings').json()['api_key_set']


@pytest.mark.parametrize('change', [
    {'base_url': 'javascript:alert(1)'}, {'base_url': 'https://user:password@example.com'},
    {'base_url': 'https://example.com?token=hidden'}, {'base_url': 'https://bad host.example'},
    {'model': ''}, {'api_key': 'artificial-secret-value\n'},
    {'api_key': {'value': 'artificial-secret-value'}}, {'unknown': 'artificial-secret-value'},
])
def test_invalid_inputs_do_not_echo_credentials(client, change):
    response = client.post('/api/settings', json={**PAYLOAD, **change})
    assert response.status_code == 422
    assert 'artificial-secret-value' not in response.text
    assert not client.app.state.model_settings.path.exists()


def test_queued_dialogue_blocks_save_until_stopped(client):
    task = client.post('/api/conversations', json={'content': 'offline question', 'request_id': 'settings-test'}).json()['task']
    assert client.post('/api/settings', json=PAYLOAD).status_code == 409
    client.post(f"/api/conversations/{task['id']}/stop")
    assert client.post('/api/settings', json=PAYLOAD).status_code == 200


def test_write_failure_preserves_runtime_and_previous_file(client, monkeypatch):
    client.post('/api/settings', json=PAYLOAD)
    service = client.app.state.model_settings
    before = service.path.read_bytes()
    adapter = client.app.state.agent.llm
    def fail_replace(*args):
        raise OSError('artificial disk failure')
    monkeypatch.setattr('backend.app.model_settings.os.replace', fail_replace)
    response = client.post('/api/settings', json={**PAYLOAD, 'model': 'not-saved'})
    assert response.status_code == 500 and PAYLOAD['api_key'] not in response.text
    assert service.path.read_bytes() == before
    assert client.app.state.agent.llm is adapter
    assert not list(service.path.parent.glob('tmp*'))


def test_other_websites_cannot_change_settings(client):
    response = client.post('/api/settings', json=PAYLOAD, headers={'Origin': 'https://untrusted.example'})
    assert response.status_code == 403
    assert not client.app.state.model_settings.path.exists()


def test_worker_remains_busy_until_the_stopped_turn_finishes(client):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        db = client.app.state.db
        store = ConversationStore(db)

        class SlowAgent:
            llm = None

            async def process(self, turn):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    # 外部请求不会在取消的瞬间结束。
                    await release.wait()
                    raise
        worker = SerialWorker(db, SlowAgent())
        job = asyncio.create_task(worker.serve())
        try:
            task_id = store.enqueue(ConversationCreateRequest(content='offline', request_id='worker-test'))
            worker.notify()
            await asyncio.wait_for(entered.wait(), 1)
            store.stop(task_id)
            worker.cancel(task_id)
            assert ModelSettingsService.busy(db, worker)
            release.set()
            for _ in range(100):
                if not worker.busy:
                    break
                await asyncio.sleep(0.01)
            assert not ModelSettingsService.busy(db, worker)
        finally:
            job.cancel()
            with suppress(asyncio.CancelledError):
                await job
    asyncio.run(scenario())


def test_startup_validation_does_not_include_credentials(tmp_path):
    cfg = Settings(_env_file=None, data_dir=tmp_path, llm_base_url='https://user:artificial-secret-value@example.com',
                   llm_model='offline', llm_api_key='artificial-secret-value')
    with pytest.raises(RuntimeError) as captured:
        ModelSettingsService(cfg)
    assert 'artificial-secret-value' not in str(captured.value)
    assert 'LLM_BASE_URL' in str(captured.value)
    (tmp_path / 'model-settings.json').write_text('{"api_key": "artificial-secret-value"}')
    with pytest.raises(RuntimeError) as captured:
        ModelSettingsService(cfg)
    assert 'artificial-secret-value' not in str(captured.value)
