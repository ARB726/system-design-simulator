"""HTTP ownership, input limits, persistent workers, and result equivalence."""
import json

import pytest
pytest.importorskip('fastapi', reason='Install fullstack/backend/requirements.txt to run API tests.')
from fastapi.testclient import TestClient

from fullstack.backend.auth import secret
from fullstack.backend.jobs import execute
from fullstack.backend.main import app
from fullstack.backend.store import SQLStore, store
from fullstack.backend.worker import run_job
from sim.config import Config
from sim.execution import analyzed_run


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "lab.db"}')
    monkeypatch.setenv('LOCAL_SESSION_SECRET', 'test-session-secret-long-enough-for-hmac-key')
    monkeypatch.delenv('STORAGE_MODE', raising=False)
    store.cache_clear()
    secret.cache_clear()
    with TestClient(app) as client:
        yield client
    store().engine.dispose()
    store.cache_clear()
    secret.cache_clear()


def account(client, email='student@example.com'):
    r = client.post('/api/auth/register', json={'email': email, 'password': 'correct-horse-battery-staple'})
    assert r.status_code == 200
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def payload():
    cfg = Config()
    cfg.workload.rps = 30
    cfg.workload.duration_s = 10
    return {'name': 'Baseline', 'config': cfg.to_dict()}


def test_background_job_ownership_and_persistence(client):
    alice, bob = account(client), account(client, 'bob@example.com')
    assert client.post('/api/experiments', json=payload()).status_code == 401
    response = client.post('/api/experiments', headers=alice, json=payload())
    assert response.status_code == 202
    job_id = response.json()['id']
    assert response.json()['status'] == 'queued'
    assert 'owner' not in response.json()
    assert client.get('/api/experiments/' + job_id, headers=bob).status_code == 404
    assert client.get('/api/experiments', headers=bob).json() == []
    # A new SQLStore sees the committed queued job after API restart.
    other = SQLStore()
    job = other.claim()
    assert job['id'] == job_id
    assert other.claim() is None
    other.engine.dispose()
    run_job(job)
    response = client.get('/api/experiments/' + job_id, headers=alice).json()
    assert response['status'] == 'completed'
    assert response['result']['summary']['success_rate'] > 0
    assert len(response['result']['timeline']) == 10
    json.dumps(response, allow_nan=False)


def test_limits_and_pending_quota(client):
    headers = account(client)
    body = payload()
    body['config']['app']['replicas'] = -2
    assert client.post('/api/experiments', headers=headers, json=body).status_code == 422
    body = payload()
    body['config']['workload']['rps'] = 100000
    assert client.post('/api/experiments', headers=headers, json=body).status_code == 422
    body = payload()
    body['config']['cache']['enabled'] = 'yes'
    assert client.post('/api/experiments', headers=headers, json=body).status_code == 422
    assert client.post('/api/experiments', headers=headers, json=payload()).status_code == 202
    assert client.post('/api/experiments', headers=headers, json=payload()).status_code == 202
    assert client.post('/api/experiments', headers=headers, json=payload()).status_code == 422


def test_failed_worker_is_terminal_and_releases_quota(client, monkeypatch):
    from fullstack.backend import worker
    headers = account(client)
    client.post('/api/experiments', headers=headers, json=payload())
    job = store().claim()
    monkeypatch.setattr(worker, 'execute', lambda _: (_ for _ in ()).throw(RuntimeError('private diagnostic')))
    run_job(job)
    response = client.get('/api/experiments/' + job['id'], headers=headers).json()
    assert response['status'] == 'failed'
    assert 'private diagnostic' not in response['error']
    assert client.post('/api/experiments', headers=headers, json=payload()).status_code == 202


def test_login_and_token_validation(client):
    account(client)
    credentials = {'email': 'STUDENT@example.com', 'password': 'correct-horse-battery-staple'}
    assert client.post('/api/auth/login', json=credentials).status_code == 200
    credentials['password'] = 'a-wrong-long-password'
    assert client.post('/api/auth/login', json=credentials).status_code == 401
    assert client.get('/api/experiments', headers={'Authorization': 'Bearer forged'}).status_code == 401
    assert client.post('/api/auth/register', json={'email': 'student@example.com', 'password': 'correct-horse-battery-staple'}).status_code == 409


def test_results_match_existing_engine():
    body = payload()
    cfg = Config()
    cfg.workload.rps = 30
    cfg.workload.duration_s = 10
    _, _, expected, _ = analyzed_run(cfg)
    result = execute(body)
    for key in ('served_rps', 'success_rate', 'p95_ms', 'p99_ms'):
        assert result['summary'][key] == pytest.approx(expected[key], abs=1e-12)


def test_catalog_and_oversized_body(client):
    catalog = client.get('/api/catalog')
    assert catalog.status_code == 200
    assert len(catalog.json()['challenges']) == 6
    assert client.post('/api/experiments', content='a' * 24001).status_code == 413


def test_cloud_archive_can_be_restored_under_local_owner(client):
    headers = account(client)
    job = client.post('/api/experiments', headers=headers, json=payload()).json()
    run_job(store().claim())
    completed = client.get('/api/experiments/' + job['id'], headers=headers).json()
    second = account(client, 'restore@example.com')
    archive = {'version': 1, 'experiments': [completed]}
    assert client.post('/api/import', headers=second, json=archive).json() == {'imported': 1}
    restored = client.get('/api/experiments', headers=second).json()
    assert len(restored) == 1
    assert restored[0]['id'] != completed['id']
    result = client.get('/api/experiments/' + restored[0]['id'], headers=second).json()['result']
    assert result['summary'] == completed['result']['summary']
    archive['experiments'][0]['status'] = 'running'
    assert client.post('/api/import', headers=second, json=archive).status_code == 422


def test_all_learning_challenge_defaults_are_valid():
    from sim.challenges import challenges
    from fullstack.backend.jobs import validate
    for challenge in challenges().values():
        validate({'kind': 'grade', 'challenge': challenge.id, 'config': challenge.base.to_dict()})


def test_learning_grading_runs_real_engine_checks():
    from sim.challenges import challenges
    challenge = challenges()['launch']
    result = execute({'kind': 'grade', 'challenge': challenge.id, 'config': challenge.base.to_dict()})
    assert result['type'] == 'grade'
    assert len(result['checks']) == len(challenge.checks)
    assert all('p99_ms' in check and 'success' in check for check in result['checks'])
    assert isinstance(result['passed'], bool)
