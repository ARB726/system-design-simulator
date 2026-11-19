"""Service-emulated transactions and stale writer races; no live AWS calls."""
from copy import deepcopy

import pytest

boto3 = pytest.importorskip('boto3')
mock_aws = pytest.importorskip('moto').mock_aws
from fullstack.backend import store as storage
from fullstack.backend.leases import LEASE_SECONDS, MAX_ATTEMPTS


@pytest.fixture
def queue(monkeypatch):
    # This Region exists only in Moto's in-process emulator.
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    monkeypatch.setenv('JOBS_TABLE', 'jobs')
    monkeypatch.setenv('RESULTS_BUCKET', 'lab-test-results')
    clock = [1000]
    monkeypatch.setattr(storage, 'now', lambda: clock[0])
    with mock_aws():
        ddb = boto3.client('dynamodb')
        ddb.create_table(TableName='jobs', KeySchema=[{'AttributeName': 'owner', 'KeyType': 'HASH'}, {'AttributeName': 'id', 'KeyType': 'RANGE'}], AttributeDefinitions=[{'AttributeName': n, 'AttributeType': 'S'} for n in ('owner', 'id')], BillingMode='PAY_PER_REQUEST')
        boto3.client('s3').create_bucket(Bucket='lab-test-results')
        url = boto3.client('sqs').create_queue(QueueName='jobs')['QueueUrl']
        monkeypatch.setenv('JOBS_QUEUE_URL', url)
        yield storage.AWSStore(), clock


def active(db):
    return int(db.table.get_item(Key={'owner': 'alice', 'id': '_quota'}, ConsistentRead=True)['Item']['active'])


def test_only_one_snapshot_claim_wins(queue):
    db, _ = queue
    first = db.create('alice', {})
    duplicate = deepcopy(first)
    assert db.mark_running(first)
    assert not db.mark_running(duplicate)
    assert active(db) == 1


def test_admission_quota_is_bounded(queue):
    db, _ = queue
    db.create('alice', {})
    db.create('alice', {})
    with pytest.raises(ValueError, match='Two experiments'):
        db.create('alice', {})
    assert active(db) == 2


def test_old_worker_cannot_corrupt_new_result_during_upload(queue, monkeypatch):
    db, clock = queue
    old = db.create('alice', {})
    assert db.mark_running(old)
    upload = db.s3.put_object

    def interleave(**kwargs):
        clock[0] += LEASE_SECONDS
        replacement = db.get('alice', old['id'])
        assert db.mark_running(replacement)
        # Disable the hook for the replacement's upload.
        monkeypatch.setattr(db.s3, 'put_object', upload)
        assert db.finish(replacement, result={'winner': 'replacement'})
        return upload(**kwargs)

    monkeypatch.setattr(db.s3, 'put_object', interleave)
    with pytest.raises(db.ddb.exceptions.TransactionCanceledException):
        db.finish(old, result={'winner': 'stale'})
    assert db.get('alice', old['id'])['result'] == {'winner': 'replacement'}
    assert active(db) == 0
    assert db.finish(old, result={'winner': 'duplicate'})
    assert active(db) == 0


def test_expired_publication_rejected_by_transaction(queue, monkeypatch):
    db, clock = queue
    job = db.create('alice', {})
    db.mark_running(job)
    upload = db.s3.put_object

    def expire(**kwargs):
        clock[0] += LEASE_SECONDS
        return upload(**kwargs)

    monkeypatch.setattr(db.s3, 'put_object', expire)
    with pytest.raises(db.ddb.exceptions.TransactionCanceledException):
        db.finish(job, result={})
    assert active(db) == 1
    assert db.get('alice', job['id'])['status'] == 'running'


def test_exhaustion_and_duplicate_dead_letter_release_once(queue):
    db, clock = queue
    job = db.create('alice', {})
    for _ in range(MAX_ATTEMPTS):
        assert db.mark_running(job)
        clock[0] += LEASE_SECONDS
    assert not db.mark_running(job)
    assert db.get('alice', job['id'])['status'] == 'failed'
    assert active(db) == 0
    assert db.finish(job, error='duplicate', exhausted=True)
    assert active(db) == 0
    assert db.create('alice', {})['status'] == 'queued'


def test_s3_failure_preserves_running_job_and_quota(queue, monkeypatch):
    db, _ = queue
    job = db.create('alice', {})
    db.mark_running(job)

    def fail(**_):
        raise OSError('injected upload failure')

    monkeypatch.setattr(db.s3, 'put_object', fail)
    with pytest.raises(OSError):
        db.finish(job, result={})
    assert db.get('alice', job['id'])['status'] == 'running'
    assert active(db) == 1
