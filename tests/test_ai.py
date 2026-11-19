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
    monkeypatch.setenv('AI_PROVIDER', 'openai')
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
    claimed = store().claim()
    assert claimed['id'] == job['id']
    assert store().finish(claimed, result=result)
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
    assert first.json()['citations'][0]['source'] == 'result.summary.p95_ms'
    assert first.json()['citations'][0]['value'] == 50
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
    claimed = store().claim()
    assert claimed['id'] == job['id']
    assert store().finish(claimed, result=dict(type='simulation', summary={'p95_ms': 'bad'}))
    assert client.post(url, headers=headers()).status_code == 422
    assert ai.budget.total == 0


def test_fabricated_measurements_are_not_cached(client, monkeypatch, caplog):
    import logging
    answer = dict(ANSWER, observations=[dict(metric='p95_ms', interpretation='Latency is 900 ms.')])
    response = good_response()
    response['output'][0]['content'][0]['text'] = json.dumps(answer)
    transport(monkeypatch, lambda request: httpx.Response(200, json=response))
    with caplog.at_level(logging.INFO, logger='systems_lab.ai'):
        result = client.post(f'/api/experiments/{completed()}/explanation', headers=headers())
    assert result.status_code == 502
    assert not ai.budget.cache and not ai.budget.active
    assert 'grounding_rejected' in caplog.text


def gemini_response():
    return dict(candidates=[dict(finishReason='STOP', content={'parts': [{'text': json.dumps(ANSWER)}]})])


def configure_gemini(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-gemini-key')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-flash-latest')


def test_gemini_contract_and_public_metadata(client, monkeypatch):
    configure_gemini(monkeypatch)
    def handler(request):
        assert str(request.url) == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent'
        assert request.headers['x-goog-api-key'] == 'test-gemini-key'
        assert 'authorization' not in request.headers and 'test-gemini-key' not in str(request.url)
        body = json.loads(request.content)
        assert body['generationConfig']['responseMimeType'] == 'application/json'
        assert body['generationConfig']['maxOutputTokens'] == 1600
        assert body['generationConfig']['responseJsonSchema']['additionalProperties'] is False
        assert 'PRIVATE' not in body['contents'][0]['parts'][0]['text']
        assert body['systemInstruction']['parts'][0]['text'] == ai.INSTRUCTIONS
        return httpx.Response(200, json=gemini_response())
    transport(monkeypatch, handler)
    settings = client.get('/api/settings')
    assert settings.json()['ai_provider'] == 'gemini' and settings.json()['ai_enabled'] is True
    assert 'test-gemini-key' not in settings.text
    job = completed()
    result = client.post(f'/api/experiments/{job}/explanation', headers=headers())
    assert result.status_code == 200 and result.json()['provider'] == 'gemini'
    assert result.json()['explanation'] == ANSWER
    assert 'test-gemini-key' not in result.text


@pytest.mark.parametrize('mode', ['blocked', 'empty', 'truncated', 'safety', 'invalid', 'thought', 'shape', 'http', 'timeout'])
def test_gemini_failure_handling(client, monkeypatch, mode):
    configure_gemini(monkeypatch)
    def handler(request):
        data = gemini_response()
        if mode == 'blocked': data = {'promptFeedback': {'blockReason': 'SAFETY'}}
        if mode == 'empty': data['candidates'] = []
        if mode == 'truncated': data['candidates'][0]['finishReason'] = 'MAX_TOKENS'
        if mode == 'safety': data['candidates'][0]['safetyRatings'] = [{'blocked': True}]
        if mode == 'invalid': data['candidates'][0]['content']['parts'][0]['text'] = '{}'
        if mode == 'thought': data['candidates'][0]['content']['parts'][0]['thought'] = True
        if mode == 'shape': data = []
        if mode == 'http': return httpx.Response(429, text='PRIVATE provider error')
        if mode == 'timeout': raise httpx.ReadTimeout('PRIVATE provider error')
        return httpx.Response(200, json=data)
    transport(monkeypatch, handler)
    job = completed()
    response = client.post(f'/api/experiments/{job}/explanation', headers=headers())
    assert response.status_code == (504 if mode == 'timeout' else 502)
    assert 'PRIVATE' not in response.text
    assert not ai.budget.active and not ai.budget.cache


def test_provider_selection_fails_closed_without_fallback(client, monkeypatch):
    configure_gemini(monkeypatch)
    monkeypatch.delenv('GEMINI_API_KEY')
    assert client.get('/api/settings').json()['ai_enabled'] is False
    job = completed()
    assert client.post(f'/api/experiments/{job}/explanation', headers=headers()).status_code == 503
    monkeypatch.setenv('GEMINI_API_KEY', 'test-gemini-key')
    monkeypatch.setenv('GEMINI_MODEL', '../invalid/path')
    assert not ai.available()
    monkeypatch.setenv('AI_PROVIDER', 'unknown')
    assert not ai.available()


def test_provider_is_part_of_cache_identity(client, monkeypatch):
    configure_gemini(monkeypatch)
    monkeypatch.setenv('OPENAI_MODEL', 'gemini-flash-latest')
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json=gemini_response() if request.url.host == 'generativelanguage.googleapis.com' else good_response())
    transport(monkeypatch, handler)
    job = completed(); url = f'/api/experiments/{job}/explanation'
    assert client.post(url, headers=headers()).json()['cached'] is False
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    response = client.post(url, headers=headers()).json()
    assert response['cached'] is False and response['provider'] == 'openai'
    monkeypatch.setenv('AI_PROVIDER', 'gemini')
    assert client.post(url, headers=headers()).json()['cached'] is True
    assert calls == ['generativelanguage.googleapis.com', 'api.openai.com']


