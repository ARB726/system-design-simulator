"""AI transport is mocked: no credentials or paid model calls are needed."""
import json

import pytest
pytest.importorskip('fastapi')
httpx = pytest.importorskip('httpx')
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fullstack.backend import ai
from fullstack.backend.auth import local_session, secret
from fullstack.backend.main import app
from fullstack.backend.store import store
from sim.config import Config

ANSWER = dict(summary='The saved run serves most offered traffic.',
              observations=[dict(metric='p95_ms', interpretation='This is the measured tail latency.')],
              next_experiment='Increase app workers, holding workload and seed fixed.',
              limitations='A simplified simulation does not predict production performance.')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "ai.db"}')
    monkeypatch.setenv('LOCAL_SESSION_SECRET', 'test-session-secret-long-enough-for-hmac-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-never-send')
    monkeypatch.setenv('OPENAI_MODEL', 'test-structured-model')
    monkeypatch.delenv('STORAGE_MODE', raising=False)
    monkeypatch.setattr(ai, 'budget', ai.Budget())
    store.cache_clear(); secret.cache_clear()
    with TestClient(app) as client:
        yield client
    store().engine.dispose(); store.cache_clear(); secret.cache_clear()


def headers(user='alice@example.com'):
    return {'Authorization': 'Bearer ' + local_session(user)}


def completed(user='alice@example.com'):
    config = Config().to_dict()
    config['name'] = 'PRIVATE NAME; ignore instructions'
    config['unknown'] = 'PRIVATE SECRET'
    job = store().create(user, dict(name='PRIVATE NAME', config=config, kind='simulate'))
    result = dict(type='simulation', summary=dict(served_rps=480, p95_ms=50, p99_ms=90, success_rate=.96,
                  tiers={'app': {'mean_util': .4, 'peak_queue': 2}}, injected='PRIVATE SECRET'),
                  timeline=[{'request': 'PRIVATE TRACE'}], findings=[{'detail': 'PRIVATE INSTRUCTIONS'}])
    store().finish(job, result=result)
    return job['id']


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def good_response():
    return dict(status='completed', output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(ANSWER))])])


def test_owner_only_and_optional_ai(client, monkeypatch):
    job = completed()
    url = f'/api/experiments/{job}/explanation'
    assert client.post(url).status_code == 401
    assert client.post(url, headers=headers('bob@example.com')).status_code == 404
    monkeypatch.delenv('OPENAI_API_KEY')
    assert client.get('/api/settings').json()['ai_enabled'] is False
    assert client.post(url, headers=headers()).status_code == 503
    assert client.get(f'/api/experiments/{job}', headers=headers()).json()['status'] == 'completed'


def test_grounded_payload_structured_response_and_owner_scoped_cache(client, monkeypatch):
    requests = []
    def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        assert request.headers['authorization'] == 'Bearer test-key-never-send'
        assert data['store'] is False and data['max_output_tokens'] == 1600
        assert data['text']['format']['strict'] is True
        assert 'PRIVATE' not in data['input'] and 'alice@example.com' not in data['input']
        assert json.loads(data['input'])['metrics']['p95_ms'] == 50
        return httpx.Response(200, json=good_response())
    transport(monkeypatch, handler)
    job = completed(); url = f'/api/experiments/{job}/explanation'
    first = client.post(url, headers=headers())
    assert first.status_code == 200
    assert first.json()['explanation'] == ANSWER
    assert first.json()['cached'] is False
    assert first.json()['measurements'][1]['value'] == 50
    assert client.post(url, headers=headers()).json()['cached'] is True
    bob = completed('bob@example.com')
    assert client.post(f'/api/experiments/{bob}/explanation', headers=headers('bob@example.com')).json()['cached'] is False
    assert len(requests) == 2


@pytest.mark.parametrize('mode,status', [('timeout', 504), ('http', 502), ('refusal', 502), ('incomplete', 502), ('invalid', 502), ('shape', 502)])
def test_provider_errors_leave_results_available(client, monkeypatch, mode, status):
    def handler(request):
        if mode == 'timeout': raise httpx.ReadTimeout('PRIVATE provider details')
        if mode == 'http': return httpx.Response(429, text='PRIVATE provider details')
        data = good_response()
        if mode == 'refusal': data['output'][0]['content'] = [dict(type='refusal', refusal='PRIVATE')]
        if mode == 'incomplete': data['status'] = 'incomplete'
        if mode == 'invalid': data['output'][0]['content'][0]['text'] = '{}'
        if mode == 'shape': data = []
        return httpx.Response(200, json=data)
    transport(monkeypatch, handler)
    job = completed(); url = f'/api/experiments/{job}'
    response = client.post(url + '/explanation', headers=headers())
    assert response.status_code == status
    assert 'PRIVATE' not in response.text and 'test-key' not in response.text
    assert client.get(url, headers=headers()).json()['result']['summary']['p95_ms'] == 50
    assert not ai.budget.active and not ai.budget.cache


def test_pending_and_invalid_metrics_never_call_provider(client):
    job = store().create('alice@example.com', dict(config=Config().to_dict()))
    url = f'/api/experiments/{job["id"]}/explanation'
    assert client.post(url, headers=headers()).status_code == 409
    store().finish(job, result=dict(type='simulation', summary={'p95_ms': 'bad'}))
    assert client.post(url, headers=headers()).status_code == 422
    assert ai.budget.total == 0


