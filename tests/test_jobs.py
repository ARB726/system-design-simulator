"""Queue failures must recover capacity and preserve actionable errors."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from kombu.exceptions import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from sim import jobs, worker


@pytest.mark.parametrize("stage", ["ownership", "publish"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_submission_failure_cleans_up_without_masking_error(monkeypatch, stage, cleanup_fails):
    failure = RedisConnectionError("ownership failed") if stage == "ownership" else OperationalError("publish failed")
    client = Mock()
    client.eval.return_value = 1
    if stage == "ownership":
        client.set.side_effect = failure
    publish = Mock(side_effect=failure)
    release = Mock(side_effect=OSError("cleanup unavailable") if cleanup_fails else None)
    monkeypatch.setattr(jobs, "redis_client", lambda: client)
    monkeypatch.setattr(jobs, "release", release)
    monkeypatch.setattr(worker.celery_app, "send_task", publish)

    with pytest.raises(jobs.JobError, match="queue is unavailable") as caught:
        jobs.submit("simulate", {}, "owner")

    assert caught.value.__cause__ is failure
    job_id, owner = release.call_args.args
    assert owner == "owner"
    client.delete.assert_called_once_with(f"sysdesign:job:{job_id}")
    assert publish.call_count == (stage == "publish")


@pytest.mark.parametrize("failure", [RedisConnectionError("offline"), OSError("offline"), OperationalError("offline")])
def test_poll_backend_outage_has_user_facing_error(monkeypatch, failure):
    monkeypatch.setattr(jobs, "redis_client", lambda: SimpleNamespace(get=lambda key: "owner"))
    monkeypatch.setattr(worker.celery_app, "AsyncResult", Mock(side_effect=failure))
    with pytest.raises(jobs.JobError, match="queue is unavailable") as caught:
        jobs.poll("job", "owner")
    assert caught.value.__cause__ is failure
