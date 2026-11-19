"""Failure schedules for durable jobs, with no cloud credentials or services."""
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

pytest.importorskip('sqlalchemy')
from fullstack.backend import store as storage
from fullstack.backend.leases import LEASE_SECONDS, MAX_ATTEMPTS


@pytest.fixture
def queue(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr(storage, 'now', lambda: clock[0])
    db = storage.SQLStore(f'sqlite:///{tmp_path / "jobs.db"}')
    yield db, clock
    db.engine.dispose()


def test_crash_recovery_fences_stale_worker(queue):
    db, clock = queue
    ref = db.create('alice', {})
    old = db.claim()
    assert old['status'] == 'running'
    assert db.claim() is None
    clock[0] += LEASE_SECONDS
    assert db.finish(old, result={'stale': True}) is False
    replacement = db.claim()
    assert replacement['attempts'] == 2
    assert replacement['lease_token'] != old['lease_token']
    assert db.finish(old, error='late failure') is False
    assert db.finish(replacement, result={}) is True
    assert db.finish(old, result={'stale': True}) is False
    assert db.get('alice', ref['id'])['result'] == {}
    assert db.claim() is None


def test_crash_after_commit_does_not_repeat_job(queue):
    db, clock = queue
    ref = db.create('alice', {})
    job = db.claim()
    assert db.finish(job, result={'value': 42})
    clock[0] += LEASE_SECONDS * 2
    assert db.claim() is None
    assert not db.finish(job, result={'value': 0})
    assert db.get('alice', ref['id'])['result'] == {'value': 42}


def test_repeated_crashes_exhaust_attempts_and_release_quota(queue):
    db, clock = queue
    ref = db.create('alice', {})
    db.create('alice', {})
    with pytest.raises(ValueError):
        db.create('alice', {})
    # Both jobs may alternate as expired jobs are reclaimed.
    for _ in range(MAX_ATTEMPTS * 2):
        assert db.claim() is not None
        clock[0] += LEASE_SECONDS
    assert db.claim() is None
    assert db.get('alice', ref['id'])['status'] == 'failed'
    assert db.create('alice', {})['status'] == 'queued'


def test_concurrent_claims_have_one_winner(queue):
    db, _ = queue
    db.create('alice', {})
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: db.claim(), range(8)))
    assert len([j for j in claims if j]) == 1


def test_concurrent_submissions_respect_owner_quota(queue):
    db, _ = queue

    def submit(_):
        try:
            return db.create('alice', {})
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        submitted = list(pool.map(submit, range(8)))
    assert len([job for job in submitted if job]) == 2


def test_wrong_owner_cannot_publish(queue):
    db, _ = queue
    db.create('alice', {})
    job = db.claim()
    assert not db.finish({**job, 'owner': 'bob'}, result={})
    assert db.finish(job, result={})


def test_existing_database_is_upgraded(tmp_path):
    from sqlalchemy import create_engine
    url = f'sqlite:///{tmp_path / "old.db"}'
    engine = create_engine(url)
    with engine.begin() as cx:
        cx.exec_driver_sql('CREATE TABLE lab_jobs (id TEXT PRIMARY KEY, owner TEXT, created BIGINT, updated BIGINT, status TEXT, payload TEXT, result TEXT, error TEXT)')
        cx.exec_driver_sql("INSERT INTO lab_jobs VALUES ('old','alice',1,1,'running','{}',NULL,NULL)")
    engine.dispose()
    db = storage.SQLStore(url)
    try:
        assert db.claim()['id'] == 'old'
    finally:
        db.engine.dispose()


@pytest.fixture
def aws(monkeypatch):
    """SDK request contract fixture; not an emulation of DynamoDB isolation."""
    from unittest.mock import Mock
    db = storage.AWSStore.__new__(storage.AWSStore)
    db.table, db.s3, db.ddb = Mock(), Mock(), Mock()
    from botocore.exceptions import ClientError
    # Use a real exception type rather than Mock's dynamic attribute.
    db.table.meta.client.exceptions.ConditionalCheckFailedException = ClientError
    db.table.name = 'jobs'
    db.bucket = 'results'
    clock = [1000]
    monkeypatch.setattr(storage, 'now', lambda: clock[0])
    job = dict(id='job', owner='alice', status='queued', updated=1000, payload={})
    return db, job, clock


def test_aws_claim_updates_execution_snapshot_and_cas(aws):
    db, job, _ = aws
    assert db.mark_running(job)
    assert job['lease_token']
    assert job['attempts'] == 1
    request = db.table.update_item.call_args.kwargs
    assert request['ConditionExpression'] == '#doc=:old'
    assert json.loads(request['ExpressionAttributeValues'][':old'])['status'] == 'queued'
    assert not db.mark_running(job)
    assert db.table.update_item.call_count == 1


def test_aws_stale_attempt_does_not_upload(aws):
    db, job, clock = aws
    db.mark_running(job)
    old = deepcopy(job)
    clock[0] += LEASE_SECONDS
    assert db.mark_running(job)
    db.get = lambda *_: deepcopy(job)
    assert not db.finish(old, result={'stale': True})
    db.s3.put_object.assert_not_called()
    db.ddb.transact_write_items.assert_not_called()


def test_aws_publication_is_fenced_and_quota_release_atomic(aws):
    db, job, _ = aws
    db.mark_running(job)
    db.get = lambda *_: deepcopy(job)
    assert db.finish(job, result={})
    first = db.s3.put_object.call_args.kwargs['Key']
    assert db.finish(job, result={})
    assert first != db.s3.put_object.call_args.kwargs['Key']
    request = db.ddb.transact_write_items.call_args.kwargs
    assert len(request['ClientRequestToken']) == 36
    updates = request['TransactItems']
    assert len(updates) == 2
    assert 'lease_until > :timestamp' in updates[0]['Update']['ConditionExpression']
    assert updates[1]['Update']['ConditionExpression'] == '#active > :zero'


def test_aws_expiry_during_upload_is_checked_at_commit(aws):
    db, job, clock = aws
    db.mark_running(job)
    db.get = lambda *_: deepcopy(job)
    db.s3.put_object.side_effect = lambda **_: clock.__setitem__(0, clock[0] + LEASE_SECONDS)
    db.finish(job, result={})
    update = db.ddb.transact_write_items.call_args.kwargs['TransactItems'][0]['Update']
    assert int(update['ExpressionAttributeValues'][':timestamp']['N']) == job['lease_until']


def test_aws_dead_letter_does_not_interrupt_live_worker(aws):
    db, job, clock = aws
    db.mark_running(job)
    db.get = lambda *_: deepcopy(job)
    assert not db.finish(job, error='exhausted', exhausted=True)
    clock[0] += LEASE_SECONDS
    assert db.finish(job, error='exhausted', exhausted=True)


def test_aws_persistence_failure_propagates_for_redelivery(aws):
    db, job, _ = aws
    db.mark_running(job)
    db.get = lambda *_: deepcopy(job)
    db.ddb.transact_write_items.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError, match='storage unavailable'):
        db.finish(job, result={})
