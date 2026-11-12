import logging
from unittest.mock import Mock

import pytest

from sim import jobs, worker, execution
from tools.load_test import run_one, summarize


@pytest.mark.parametrize("kind,queue", [("simulate", "interactive"), ("replay", "interactive"),
    ("grade", "batch"), ("sweep_load", "batch"), ("sweep_replicas", "batch"), ("validate_mmc", "batch")])
def test_submission_routes_by_workload(monkeypatch, kind, queue):
    client = Mock()
    client.eval.return_value = 1
    send = Mock()
    monkeypatch.setattr(jobs, "redis_client", lambda: client)
    monkeypatch.setattr(worker.celery_app, "send_task", send)
    jobs.submit(kind, {}, "owner")
    assert send.call_args.kwargs["queue"] == queue
    assert send.call_args.kwargs["kwargs"]["submitted_at"] > 0


def test_unknown_job_is_rejected_before_admission(monkeypatch):
    monkeypatch.setattr(jobs, "redis_client", lambda: pytest.fail("Must not admit invalid job"))
    with pytest.raises(ValueError):
        jobs.submit("unknown", {}, "owner")


@pytest.mark.parametrize("fails", [False, True])
def test_worker_emits_metrics_and_releases_on_failure(monkeypatch, caplog, fails):
    monkeypatch.setattr(execution, "execute", Mock(side_effect=ValueError("invalid") if fails else None,
                                                   return_value={"type": "frame"}))
    release = Mock()
    monkeypatch.setattr(jobs, "release", release)
    caplog.set_level(logging.INFO, logger="sysdesign.metrics")
    result = worker.execute_job.apply(args=["simulate", {}, "private-owner"],
                                     kwargs={"submitted_at": 0}).get()
    assert bool(result.get("error")) == fails
    assert result["job_metrics"]["execution_s"] >= 0
    assert result["job_metrics"]["queue_wait_s"] > 0
    assert result["job_metrics"]["result_bytes"] > 0
    release.assert_called_once()
    assert '"outcome": "failed"' in caplog.text if fails else '"outcome": "complete"' in caplog.text
    assert "private-owner" not in caplog.text


def test_load_harness_counts_application_errors(monkeypatch):
    monkeypatch.setattr(jobs, "submit", lambda *a: "job")
    monkeypatch.setattr(jobs, "poll", lambda *a: ("complete", {"error": "invalid"}))
    result = run_one(0, run_id="test", batch_every=0, timeout=1, config={})
    assert result["outcome"] == "failed"


def test_load_report_keeps_workload_percentiles_separate():
    records = [dict(kind="simulate", outcome="complete", metrics={"queue_wait_s": x}) for x in (1, 2, 3)]
    records.append(dict(kind="sweep_load", outcome="unavailable"))
    report = summarize(records, 2)
    assert report["completed_per_second"] == 1.5
    assert report["outcomes"]["unavailable"] == 1
    assert report["queues"]["simulate"]["queue_wait_s"] == {"p50": 2, "p95": 3}
    assert report["queues"]["sweep_load"]["queue_wait_s"]["p95"] is None


def test_snapshot_counts_only_unexpired_leases(monkeypatch):
    client = Mock()
    pipe = client.pipeline.return_value
    pipe.execute.return_value = [4, 2, 1, 0]
    client.info.return_value = {"used_memory": 1234}
    monkeypatch.setattr(jobs, "redis_client", lambda: client)
    monkeypatch.setattr(jobs.time, "time", lambda: 100)
    assert jobs.queue_snapshot() == dict(admitted=4, ready=dict(interactive=2, batch=1, celery=0),
                                          redis_used_memory_bytes=1234)
    pipe.zcount.assert_called_once_with("sysdesign:active", 100, "+inf")


def test_legacy_worker_message_has_unknown_wait(monkeypatch):
    monkeypatch.setattr(execution, "execute", lambda *a: {"type": "frame"})
    monkeypatch.setattr(jobs, "release", Mock())
    result = worker.execute_job.apply(args=["simulate", {}, "owner"]).get()
    assert result["job_metrics"]["queue_wait_s"] is None
