"""模型列表与多选保存：只使用人工凭据和离线 HTTP 替身。"""
import asyncio
import json

import httpx
import pytest

from backend.app.adapters.llm import LLMError
from backend.app.adapters.model_catalog import ModelCatalogPage, AvailableModel, list_models


@pytest.mark.parametrize('protocol', ['openai_chat', 'openai_responses', 'anthropic_messages'])
def test_list_models_uses_protocol_auth_and_validates_page(protocol):
    async def scenario():
        def response(request):
            assert request.method == 'GET' and request.url.path == '/prefix/v1/models'
            if protocol == 'anthropic_messages':
                assert request.headers['x-api-key'] == 'artificial-key'
                assert request.headers['anthropic-version'] == '2023-06-01'
                assert request.url.params['after_id'] == 'cursor-before'
                assert request.url.params['limit'] == '100'
            else:
                assert request.headers['Authorization'] == 'Bearer artificial-key'
                assert not request.url.query
            return httpx.Response(200, json={'data': [{'id': 'a', 'display_name': '模型 A'}, {'id': 'b'}, {'id': 'a'}], 'has_more': True, 'last_id': 'b'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            result = await list_models('https://offline.example/prefix/v1', protocol, 'artificial-key', 'cursor-before', client)
            assert [item.id for item in result.models] == ['a', 'b']
            assert result.next_cursor == ('b' if protocol == 'anthropic_messages' else None)
    asyncio.run(scenario())


@pytest.mark.parametrize('status,body,code', [
    (401, {'error': 'artificial-secret'}, 'authentication_failed'),
    (429, {}, 'rate_limited'), (404, {}, 'not_supported'), (500, {}, 'http_error'),
    (302, {}, 'http_error'), (200, {'data': [{'id': 123}]}, 'invalid_response'),
    (200, {'wrong': []}, 'invalid_response'),
])
def test_catalog_failure_is_explicit_and_does_not_echo_provider_body(status, body, code):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body, headers={'Location': 'https://other.example'}))) as client:
            with pytest.raises(LLMError) as failure:
                await list_models('https://offline.example', 'openai_chat', 'artificial-secret', client=client)
            assert failure.value.code == code and 'artificial-secret' not in str(failure.value)
    asyncio.run(scenario())


def test_catalog_api_retains_key_without_writing_or_generating(client, monkeypatch):
    payload = {'name': 'saved', 'protocol': 'openai_chat', 'base_url': 'https://offline.example/v1', 'models': ['a'], 'api_key': 'artificial-secret'}
    profile_id = client.post('/api/settings/providers', json=payload).json()['provider_id']
    before = client.app.state.model_settings.path.read_bytes()
    requests = []

    async def fake_list(base_url, protocol, key, cursor):
        requests.append((base_url, protocol, key, cursor))
        return ModelCatalogPage(models=[AvailableModel(id='a', name='A')])

    monkeypatch.setattr('backend.app.adapters.model_catalog.list_models', fake_list)
    request = {'provider_id': profile_id, 'protocol': 'openai_chat', 'base_url': 'https://offline.example/v1'}
    response = client.post('/api/settings/models', json=request)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert requests == [('https://offline.example/v1', 'openai_chat', 'artificial-secret', None)]
    assert 'artificial-secret' not in response.text
    assert client.app.state.model_settings.path.read_bytes() == before
    assert client.app.state.model_settings.diagnostic_calls == 0
    changed = client.post('/api/settings/models', json={**request, 'base_url': 'https://another.example/v1'})
    assert changed.status_code == 422 and len(requests) == 1
    assert client.post('/api/settings/models', json={**request, 'api_key': {'value': 'artificial-secret'}}).status_code == 422
    assert 'artificial-secret' not in client.post('/api/settings/models', json={**request, 'api_key': 'bad key'}).text


def test_provider_keeps_one_credential_and_current_model_while_models_change(client):
    payload = {'name': '供应商 A', 'protocol': 'openai_responses', 'base_url': 'https://offline.example/v1', 'models': ['a', 'b'], 'api_key': 'artificial-secret'}
    response = client.post('/api/settings/providers', json=payload)
    assert response.status_code == 200
    result = response.json(); pid = result['provider_id']
    assert len(result['settings']['providers']) == 1
    assert result['settings']['active_model'] is None and not result['settings']['enabled']
    assert client.app.state.engine.llm is None and 'artificial-secret' not in response.text
    service = client.app.state.model_settings
    stored = json.loads(service.path.read_text())
    assert len(stored['providers']) == 1 and stored['providers'][0]['models'] == ['a', 'b']
    assert stored['providers'][0]['api_key'] == 'artificial-secret'
    assert client.post('/api/settings/selection', json={'provider_id': pid, 'model': 'b'}).status_code == 200
    updated = client.post(f'/api/settings/providers/{pid}', json={**payload, 'models': ['a', 'b', 'c'], 'api_key': None}).json()
    assert len(updated['settings']['providers']) == 1 and updated['settings']['active_model'] == 'b'
    assert client.app.state.engine.llm.model == 'b'
    removed = client.post(f'/api/settings/providers/{pid}', json={**payload, 'models': ['a'], 'api_key': None}).json()
    assert not removed['settings']['enabled'] and removed['settings']['active_provider_id'] is None
    assert client.app.state.engine.llm is None


def test_provider_write_failure_keeps_all_models_and_current_runtime(client, monkeypatch):
    payload = {'name': '', 'protocol': 'openai_chat', 'base_url': 'https://offline.example/v1', 'models': ['a', 'b'], 'api_key': 'artificial-secret'}
    result = client.post('/api/settings/providers', json=payload).json()
    pid = result['provider_id']; service = client.app.state.model_settings
    client.post('/api/settings/selection', json={'provider_id': pid, 'model': 'a'})
    before = service.path.read_bytes(); adapter = client.app.state.engine.llm
    def fail(*args):
        raise OSError('artificial failure')
    monkeypatch.setattr('backend.app.model_settings.os.replace', fail)
    response = client.post(f'/api/settings/providers/{pid}', json={**payload, 'models': ['c', 'd']})
    assert response.status_code == 500 and 'artificial-secret' not in response.text
    assert service.path.read_bytes() == before and client.app.state.engine.llm is adapter
    assert service.state.providers[0].models == ['a', 'b']
    assert client.post(f'/api/settings/providers/{pid}', json={**payload, 'models': ['a', ' ']}).status_code == 422


def test_profile_migration_groups_only_matching_connections_and_keys(tmp_path):
    from backend.app.config import Settings
    from backend.app.main import create_app
    from fastapi.testclient import TestClient
    def profile(pid, model, key):
        return {'id': pid, 'name': f'人工供应商 · {model}', 'protocol': 'openai_chat', 'base_url': 'https://offline.example/v1', 'model': model, 'api_key': key}
    old = {'enabled': True, 'active_profile_id': 'p2', 'profiles': [profile('p1', 'a', 'key-one'), profile('p2', 'b', 'key-one'), profile('p3', 'c', 'different-key')]}
    path = tmp_path / 'model-settings.json'; path.write_text(json.dumps(old))
    cfg = Settings(_env_file=None, data_dir=tmp_path, llm_base_url='', llm_model='', llm_api_key='')
    with TestClient(create_app(config=cfg, run_worker=False)) as client:
        public = client.get('/api/settings').json()
        assert len(public['providers']) == 2
        assert public['providers'][0]['name'] == '人工供应商'
        assert public['providers'][0]['models'] == ['a', 'b']
        assert public['active_provider_id'] == 'p1' and public['active_model'] == 'b'
        assert client.app.state.engine.llm.model == 'b' and client.app.state.engine.llm._api_key == 'key-one'
        assert json.loads(path.read_text()) == old
        provider = public['providers'][0]
        assert client.post('/api/settings/providers/p1', json={k: provider[k] for k in ('name', 'protocol', 'base_url', 'models')}).status_code == 200
        stored = json.loads(path.read_text())
        assert len(stored['providers']) == 2 and stored['providers'][0]['api_key'] == 'key-one'
        assert stored['providers'][1]['api_key'] == 'different-key'
    with TestClient(create_app(config=cfg, run_worker=False)) as client:
        assert client.get('/api/settings').json()['active_model'] == 'b'


def test_disabled_legacy_partial_configuration_is_kept(tmp_path):
    from backend.app.config import Settings
    from backend.app.model_settings import ModelSettingsService
    old = {'enabled': False, 'protocol': 'openai_chat', 'base_url': '',
           'model': 'offline-id', 'api_key': 'artificial-kept-key'}
    path = tmp_path / 'model-settings.json'; path.write_text(json.dumps(old))
    service = ModelSettingsService(Settings(_env_file=None, data_dir=tmp_path))
    assert not service.state.enabled and len(service.state.providers) == 1
    assert service.state.providers[0].models == ['offline-id']
    assert service.state.providers[0].api_key.get_secret_value() == 'artificial-kept-key'
    assert json.loads(path.read_text()) == old
