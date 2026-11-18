import asyncio
import json
import logging
import pytest
pytest.importorskip('fastapi')
import httpx
from fastapi import HTTPException
from fullstack.backend import ai


@pytest.mark.parametrize('failure', [False, True])
def test_trace_is_structured_and_excludes_payload_and_secrets(monkeypatch, caplog, failure):
    monkeypatch.setenv('OPENAI_API_KEY', 'PRIVATE-KEY')
    def handler(request):
        if failure: raise httpx.ReadTimeout('PRIVATE-ERROR')
        answer = dict(summary='ok', observations=[dict(metric='p95_ms', interpretation='Observed')], next_experiment='test', limitations='test')
        return httpx.Response(200, json=dict(status='completed', usage=dict(input_tokens=10, output_tokens=20), output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(answer))])]))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with caplog.at_level(logging.INFO, logger='systems_lab.ai'):
        if failure:
            with pytest.raises(HTTPException): asyncio.run(ai.request_explanation('test-model', 'PRIVATE-PAYLOAD'))
        else: asyncio.run(ai.request_explanation('test-model', 'PRIVATE-PAYLOAD'))
    rows = [json.loads(record.message) for record in caplog.records if record.name == 'systems_lab.ai']
    assert len(rows) == 1
    assert rows[0]['status'] == ('error' if failure else 'ok')
    assert rows[0]['latency_ms'] >= 0
    assert rows[0]['trace_id']
    assert rows[0]['prompt_version']
    assert 'PRIVATE' not in caplog.text
    if not failure: assert rows[0]['input_tokens'] == 10
