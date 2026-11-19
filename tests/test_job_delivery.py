"""Per-record acknowledgement boundaries and interrupted invocation schedules."""
import json
from unittest.mock import Mock

import pytest

from fullstack.backend import worker


def record(identifier, body):
    return {'messageId': identifier, 'body': json.dumps(body)}


@pytest.fixture
def queue(monkeypatch):
    db = Mock()
    db.get.return_value = {'owner': 'alice', 'id': 'job', 'status': 'queued', 'payload': {}}
    db.mark_running.return_value = True
    db.finish.return_value = True
    monkeypatch.setattr(worker, 'store', lambda: db)
    monkeypatch.setattr(worker, 'execute', lambda _: {'value': 42})
    return db


def test_one_bad_message_does_not_replay_successful_sibling(queue):
    event = {'Records': [{'messageId': 'bad', 'body': '{'}, record('good', {'owner': 'alice', 'id': 'job'})]}
    assert worker.handler(event, None) == {'batchItemFailures': [{'itemIdentifier': 'bad'}]}
    queue.finish.assert_called_once()


def test_read_failure_is_isolated_to_record(queue):
    queue.get.side_effect = [RuntimeError('unavailable'), None]
    records = [record(str(i), {'owner': 'alice', 'id': str(i)}) for i in range(2)]
    assert worker.handler({'Records': records}, None) == {'batchItemFailures': [{'itemIdentifier': '0'}]}


@pytest.mark.parametrize('status', ['completed', 'failed'])
def test_terminal_redelivery_does_not_execute(queue, monkeypatch, status):
    execute = Mock()
    monkeypatch.setattr(worker, 'execute', execute)
    queue.get.return_value['status'] = status
    assert worker.handler({'Records': [record('done', {'owner': 'alice', 'id': 'job'})]}, None) == {'batchItemFailures': []}
    execute.assert_not_called()


def test_live_duplicate_is_retried_without_execution(queue, monkeypatch):
    queue.mark_running.return_value = False
    execute = Mock()
    monkeypatch.setattr(worker, 'execute', execute)
    assert worker.handler({'Records': [record('busy', {'owner': 'alice', 'id': 'job'})]}, None)['batchItemFailures'] == [{'itemIdentifier': 'busy'}]
    execute.assert_not_called()


@pytest.mark.parametrize('failure', ['lease', 'persistence'])
def test_failed_publication_requests_redelivery(queue, failure):
    if failure == 'lease':
        queue.finish.return_value = False
    else:
        queue.finish.side_effect = RuntimeError('storage unavailable')
    assert worker.handler({'Records': [record('retry', {'owner': 'alice', 'id': 'job'})]}, None)['batchItemFailures'] == [{'itemIdentifier': 'retry'}]


def test_process_death_leaves_lease_for_recovery(queue, monkeypatch):
    def die(_):
        raise SystemExit('injected process death')
    monkeypatch.setattr(worker, 'execute', die)
    with pytest.raises(SystemExit):
        worker.run_job(queue.get.return_value)
    queue.finish.assert_not_called()


def test_dead_letter_cannot_acknowledge_live_lease(queue):
    queue.finish.return_value = False
    assert worker.dead_letter_handler({'Records': [record('busy', {'owner': 'alice', 'id': 'job'})]}, None)['batchItemFailures'] == [{'itemIdentifier': 'busy'}]
    assert queue.finish.call_args.kwargs['exhausted'] is True


def test_dead_letter_failure_is_isolated(queue):
    queue.get.side_effect = [RuntimeError('unavailable'), None]
    records = [record(str(i), {'owner': 'alice', 'id': str(i)}) for i in range(2)]
    assert worker.dead_letter_handler({'Records': records}, None)['batchItemFailures'] == [{'itemIdentifier': '0'}]
