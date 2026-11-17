"""AI service limits and transport contract, without network access."""
import asyncio
import json

import pytest
pytest.importorskip('fastapi')
httpx=pytest.importorskip('httpx')
from fastapi import HTTPException
from fullstack.backend import ai


def test_provider_contract(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    answer=dict(summary='Measured throughput is stable.',observations=[dict(metric='p95_ms',interpretation='Tail latency is measured.')],next_experiment='Change workers with seed fixed.',limitations='Simplified simulation.')
    def handler(request):
        body=json.loads(request.content)
        assert str(request.url)=='https://api.openai.com/v1/responses'
        assert body['input']=='{"metrics":{"p95_ms":50}}'
        assert body['store'] is False
        assert body['text']['format']['strict'] is True
        return httpx.Response(200,json=dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(answer))])]))
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    assert asyncio.run(ai.request_explanation('test-model','{"metrics":{"p95_ms":50}}'))==answer


def test_quotas_single_flight_and_cache_bounds(monkeypatch):
    clock = [10000.0]
    monkeypatch.setattr(ai.time, 'monotonic', lambda: clock[0])
    budget = ai.Budget()
    assert budget.admit('a', 'same') is None
    with pytest.raises(HTTPException) as duplicate: budget.admit('a', 'same')
    assert duplicate.value.status_code == 429
    budget.finish('same', {'cached': False})
    assert budget.admit('a', 'same')['cached']
    for i in range(4): budget.admit('a', str(i)); budget.finish(str(i))
    with pytest.raises(HTTPException): budget.admit('a', 'limit')
    for i in range(129): budget.finish('cache-' + str(i), {'cached': False})
    assert len(budget.cache) == 128
    assert 'same' not in budget.cache
    budget.admit('b', 'in-flight-1'); budget.admit('c', 'in-flight-2')
    with pytest.raises(HTTPException): budget.admit('d', 'in-flight-3')


def test_total_limit_and_hour_reset(monkeypatch):
    clock = [10000.0]
    monkeypatch.setattr(ai.time, 'monotonic', lambda: clock[0])
    budget = ai.Budget()
    for i in range(20): budget.admit(str(i), str(i)); budget.finish(str(i))
    with pytest.raises(HTTPException): budget.admit('new', 'new')
    clock[0] += 3601
    assert budget.admit('new', 'new') is None
