"""定向验证配置热切换、持久化失败和凭据不回显；不访问外部模型。"""
import asyncio
import json
import stat
from contextlib import suppress

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.domain.models import Run, Task
from backend.app.main import create_app
from backend.app.model_settings import ModelSettingsService
from backend.app.workflow.worker import SerialWorker


PAYLOAD = {"enabled": True, "protocol": "openai_responses", "base_url": "https://offline.example/v1",
           "model": "offline-model", "api_key": "artificial-secret-value"}


def test_save_applies_to_both_services_and_survives_restart(client):
    before = client.get('/api/settings')
    assert before.status_code == 200 and before.json()['source'] == 'environment'
    assert before.headers['cache-control'] == 'no-store'
    response = client.post('/api/settings', json=PAYLOAD)
    assert response.status_code == 200
    assert PAYLOAD['api_key'] not in response.text
    assert 'api_key' not in response.json() and response.json()['api_key_set']
    state = client.app.state
    assert state.engine.llm is state.dialogue.llm
    assert state.engine.llm.model == 'offline-model'
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
        assert restarted.app.state.dialogue.llm._api_key == PAYLOAD['api_key']


def test_keep_replace_clear_and_disable(client):
    client.post('/api/settings', json=PAYLOAD)
    changed = {**PAYLOAD, 'api_key': None, 'model': 'second-model'}
    assert client.post('/api/settings', json=changed).status_code == 200
    assert client.app.state.engine.llm._api_key == PAYLOAD['api_key']
    assert client.post('/api/settings', json={**changed, 'api_key': 'replacement'}).status_code == 200
    assert client.app.state.engine.llm._api_key == 'replacement'
    clear = client.post('/api/settings', json={**changed, 'clear_api_key': True})
    assert clear.status_code == 200 and not clear.json()['api_key_set']
    disabled = client.post('/api/settings', json={**changed, 'enabled': False})
    assert disabled.status_code == 200 and not disabled.json()['enabled']
    assert client.app.state.engine.llm is None and client.app.state.dialogue.llm is None
    assert not client.get('/api/health').json()['model_configured']


def test_new_address_cannot_reuse_saved_credential_implicitly(client):
    client.post('/api/settings', json=PAYLOAD)
    old = client.app.state.engine.llm
    changed = {**PAYLOAD, 'base_url': 'https://other.example/v1', 'api_key': None}
    assert client.post('/api/settings', json=changed).status_code == 422
    assert client.app.state.engine.llm is old
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


def test_queue_blocks_save_but_paused_run_allows_it(client):
    task = client.post('/api/tasks', json={'topic': 'offline task'}).json()
    run = client.post(f"/api/tasks/{task['id']}/runs").json()
    assert client.get('/api/settings').json()['busy']
    assert client.post('/api/settings', json=PAYLOAD).status_code == 409
    client.post(f"/api/runs/{run['id']}/pause")
    assert client.post('/api/settings', json=PAYLOAD).status_code == 200
    assert client.get(f"/api/runs/{run['id']}").json()['total_calls'] == 0


def test_queued_dialogue_blocks_save_until_stopped(client):
    task = client.post('/api/conversations', json={'content': 'offline question', 'request_id': 'settings-test'}).json()['task']
    assert client.post('/api/settings', json=PAYLOAD).status_code == 409
    client.post(f"/api/conversations/{task['id']}/stop")
    assert client.post('/api/settings', json=PAYLOAD).status_code == 200


def test_write_failure_preserves_runtime_and_previous_file(client, monkeypatch):
    client.post('/api/settings', json=PAYLOAD)
    service = client.app.state.model_settings
    before = service.path.read_bytes()
    adapter = client.app.state.engine.llm
    def fail_replace(*args):
        raise OSError('artificial disk failure')
    monkeypatch.setattr('backend.app.model_settings.os.replace', fail_replace)
    response = client.post('/api/settings', json={**PAYLOAD, 'model': 'not-saved'})
    assert response.status_code == 500 and PAYLOAD['api_key'] not in response.text
    assert service.path.read_bytes() == before
    assert client.app.state.engine.llm is adapter and client.app.state.dialogue.llm is adapter
    assert not list(service.path.parent.glob('tmp*'))


def test_other_websites_cannot_change_settings(client):
    response = client.post('/api/settings', json=PAYLOAD, headers={'Origin': 'https://untrusted.example'})
    assert response.status_code == 403
    assert not client.app.state.model_settings.path.exists()


def test_worker_remains_busy_until_cancelled_external_operation_finishes(client):
    async def scenario():
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        db = client.app.state.db
        task = Task(id='worker-task', topic='offline')
        db.create_task(task)
        db.create_run(Run(id='worker-run', task_id=task.id, initial_topic=task.topic))
        class OfflineEngine:
            llm = None
            async def execute_run(self, run_id):
                entered.set()
                await release.wait()
                finished.set()
        worker = SerialWorker(db, OfflineEngine())
        job = asyncio.create_task(worker.serve())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            db.cancel_run('worker-run')
            assert ModelSettingsService.busy(db, worker)
            release.set()
            await asyncio.wait_for(finished.wait(), 1)
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
