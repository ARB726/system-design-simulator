"""Verify real asymmetric JWT signatures and enforce private experiment ownership."""
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
pytest.importorskip('fastapi')
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from fullstack.backend import supabase_auth
from fullstack.backend.main import app
from fullstack.backend.store import store
from sim.config import Config


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    monkeypatch.setenv('SUPABASE_URL', 'https://test-project.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test_public_key')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "auth.db"}')
    monkeypatch.delenv('STORAGE_MODE', raising=False)
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(supabase_auth, 'signing_keys', lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())))
    store.cache_clear()
    def token(**changes):
        claims=dict(sub=str(uuid4()), exp=int(time.time())+3600, iat=int(time.time())-5,
                    iss='https://test-project.supabase.co/auth/v1', aud='authenticated', role='authenticated')
        claims.update(changes)
        return jwt.encode(claims, key, algorithm='ES256', headers={'kid': 'test-signing-key'})
    with TestClient(app) as client:
        yield client, token
    store().engine.dispose(); store.cache_clear()


def test_google_users_have_private_experiments_and_safe_settings(setup):
    client, token = setup
    first, second = token(), token()
    a, b = {'Authorization': 'Bearer '+first}, {'Authorization': 'Bearer '+second}
    settings=client.get('/api/settings').json()
    assert settings['auth']=='supabase' and settings['supabase_publishable_key'].startswith('sb_publishable_')
    assert client.post('/api/auth/register', json={'email':'a@example.com','password':'long-enough-password'}).status_code==404
    result=client.post('/api/experiments', headers=a, json={'name':'Private design','config':Config().to_dict()})
    assert result.status_code==202
    job_id=result.json()['id']
    assert client.get('/api/experiments/'+job_id, headers=a).status_code==200
    assert client.get('/api/experiments/'+job_id, headers=b).status_code==404
    assert client.post('/api/experiments/'+job_id+'/explanation', headers=b).status_code==404


@pytest.mark.parametrize('changes', [dict(iss='https://attacker.example/auth/v1'), dict(aud='service_role'), dict(role='service_role'), dict(exp=1), dict(iat=9999999999), dict(sub='not-a-user-id'), dict(is_anonymous=True)])
def test_invalid_claims_are_rejected(setup, changes):
    client, token=setup
    assert client.get('/api/experiments',headers={'Authorization':'Bearer '+token(**changes)}).status_code==401


def test_forged_signature_and_local_tokens_cannot_bypass_supabase(setup):
    client, token=setup
    forged=jwt.encode(dict(sub=str(uuid4()),exp=int(time.time())+3600), 'attacker-secret-with-32-characters-minimum', algorithm='HS256')
    assert client.get('/api/experiments',headers={'Authorization':'Bearer '+forged}).status_code==401


@pytest.mark.parametrize('key',['sb_secret_private',jwt.encode({'role':'service_role'},'test-secret-with-32-characters-minimum',algorithm='HS256')])
def test_secret_keys_are_never_published(setup,monkeypatch,key):
    client,_=setup
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY',key)
    response=client.get('/api/settings')
    assert response.status_code==503 and key not in response.text


def test_bad_url_fails_closed(setup,monkeypatch):
    client,_=setup
    monkeypatch.setenv('SUPABASE_URL','http://untrusted.example')
    assert client.get('/api/settings').status_code==503
    assert client.get('/api/experiments',headers={'Authorization':'Bearer token'}).status_code==503
