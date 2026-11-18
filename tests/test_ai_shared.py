"""Shared AI limits survive independent API instances and recover abandoned leases."""
from concurrent.futures import ThreadPoolExecutor

import pytest
pytest.importorskip('fastapi')
pytest.importorskip('sqlalchemy')
from fastapi import HTTPException
from fullstack.backend.ai_shared import SharedBudget, configured_budget, ready


@pytest.fixture
def gates(tmp_path):
    clock=[10000]
    url=f'sqlite:///{tmp_path / "shared.db"}'
    first,second=SharedBudget(url,lambda:clock[0]),SharedBudget(url,lambda:clock[0])
    yield first,second,clock
    first.engine.dispose();second.engine.dispose()


def test_shared_cache_is_owner_scoped_and_free_of_extra_attempts(gates):
    a,b,_=gates
    lease=a.admit('alice','key')
    a.finish('key',{'cached':False,'explanation':{'summary':'Measured result'}},lease)
    assert b.admit('alice','key')['cached'] is True
    with pytest.raises(HTTPException) as error:b.admit('bob','key')
    assert error.value.status_code==409
    for i in range(4):
        key='attempt-'+str(i);lease=b.admit('alice',key);b.finish(key,None,lease)
    with pytest.raises(HTTPException) as error:a.admit('alice','sixth')
    assert error.value.status_code==429


def test_cross_instance_concurrency_is_atomic(gates):
    a,b,_=gates
    def reserve(i):
        gate=a if i%2 else b
        try:return i,gate,gate.admit('user-'+str(i),'key-'+str(i))
        except HTTPException as exc:
            assert exc.status_code==429
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted=[r for r in pool.map(reserve,range(8)) if r]
    assert len(accepted)==2
    for i,gate,lease in accepted:gate.finish('key-'+str(i),None,lease)
    lease=b.admit('new-user','new-key')
    b.finish('new-key',None,lease)


def test_global_cap_survives_new_gate_and_resets_next_utc_hour(gates):
    a,b,clock=gates
    for i in range(20):
        gate=a if i%2 else b
        lease=gate.admit('user-'+str(i),'key-'+str(i));gate.finish('key-'+str(i),None,lease)
    with pytest.raises(HTTPException) as error:a.admit('new-user','blocked')
    assert error.value.status_code==429
    clock[0]+=3600
    lease=b.admit('new-user','allowed');b.finish('allowed',None,lease)


def test_old_request_cannot_overwrite_reclaimed_cache_lease(gates):
    a,b,clock=gates
    old=a.admit('alice','same')
    clock[0]+=31
    new=b.admit('alice','same')
    a.finish('same',{'cached':False,'answer':'old'},old)
    with pytest.raises(HTTPException):a.admit('alice','same')
    b.finish('same',{'cached':False,'answer':'new'},new)
    assert a.admit('alice','same')['answer']=='new'


def test_public_ai_fails_closed_without_shared_postgres(monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER','supabase')
    monkeypatch.delenv('AI_BUDGET_DATABASE_URL',raising=False)
    assert not ready()
    with pytest.raises(HTTPException) as error:configured_budget()
    assert error.value.status_code==503
    monkeypatch.setenv('AI_BUDGET_DATABASE_URL','sqlite:///not-a-shared-public-database.db')
    assert not ready()
