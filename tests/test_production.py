import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from sim.auth import identity_key
from sim.config import Config, Workload
from sim.execution import decode, execute
from sim.limits import SimulationLimitError, validate_config


def test_identity_is_bound_to_issuer_and_subject():
    assert identity_key(dict(iss="provider", sub="user")) == identity_key(dict(iss="provider", sub="user", name="New name"))
    assert identity_key(dict(iss="other", sub="user")) != identity_key(dict(iss="provider", sub="user"))
    with pytest.raises(ValueError):
        identity_key(dict(email="unverified@example.com"))


def test_authenticated_library_ignores_url_owner(monkeypatch):
    import streamlit as st
    from sim.run_library_ui import library_key
    claims = dict(iss="trusted-provider", sub="account-a", is_logged_in=True)
    monkeypatch.setenv("SYSDESIGN_REQUIRE_AUTH", "true")
    monkeypatch.setattr(st, "user", claims)
    monkeypatch.setattr(st, "query_params", SimpleNamespace(get=lambda *a: pytest.fail("URL must not choose owner")))
    assert library_key() == identity_key(claims)


@pytest.mark.parametrize("field,value", [("rps", float("nan")), ("rps", -1),
                                        ("duration_s", 100000), ("warmup_s", 10000)])
def test_invalid_workloads_rejected_before_execution(field, value):
    cfg = Config()
    setattr(cfg.workload, field, value)
    with pytest.raises(SimulationLimitError):
        validate_config(cfg)


def test_arrival_budget_and_allocation_limits(monkeypatch):
    monkeypatch.setenv("SYSDESIGN_MAX_ARRIVALS", "100")
    with pytest.raises(SimulationLimitError, match="budget"):
        validate_config(Config())
    cfg = Config(workload=Workload(rps=1, duration_s=30))
    cfg.db.shards = 1000000
    with pytest.raises(SimulationLimitError):
        validate_config(cfg)
    cfg.db.shards = 1
    cfg.app.replicas = 1.0
    with pytest.raises(SimulationLimitError, match="integer"):
        validate_config(cfg)


def test_worker_simulation_json_roundtrip_preserves_results():
    cfg = Config(workload=Workload(rps=20, duration_s=10, warmup_s=1))
    data = json.loads(json.dumps(execute("simulate", {"config": cfg.to_dict()})))
    res, tl, summary, findings = decode(data)
    assert res.cfg == cfg
    assert len(res.requests) > 100
    assert res.requests.is_read.dtype == bool
    assert summary["served_rps"] > 0
    assert "util_app" in tl
    assert isinstance(findings, list)


def test_worker_rejects_unbounded_batch():
    with pytest.raises(ValueError, match="12"):
        execute("sweep_load", {"values": list(range(100)), "config": Config().to_dict()})
    with pytest.raises(ValueError, match="Unknown"):
        execute("arbitrary-code", {})


def test_job_ownership_checked_before_result_access(monkeypatch):
    from sim import jobs, worker
    monkeypatch.setattr(jobs, "redis_client", lambda: SimpleNamespace(get=lambda key: "owner-a"))
    monkeypatch.setattr(worker.celery_app, "AsyncResult", lambda key: pytest.fail("Unauthorized result lookup"))
    with pytest.raises(jobs.JobError, match="unavailable"):
        jobs.poll("job", "owner-b")
    monkeypatch.setattr(worker.celery_app, "AsyncResult", lambda key: SimpleNamespace(state="SUCCESS", result={"safe": True}))
    assert jobs.poll("job", "owner-a") == ("complete", {"safe": True})


def test_job_admission_rejects_busy_queue(monkeypatch):
    from sim import jobs
    monkeypatch.setattr(jobs, "redis_client", lambda: SimpleNamespace(eval=lambda *a: 0))
    with pytest.raises(jobs.JobError, match="busy"):
        jobs.submit("simulate", {}, "owner")


def test_stale_pending_job_does_not_poll_forever(monkeypatch):
    from sim import jobs, worker
    monkeypatch.setattr(jobs, "redis_client", lambda: SimpleNamespace(get=lambda key: "owner", ttl=lambda key: 2700))
    monkeypatch.setattr(worker.celery_app, "AsyncResult", lambda key: SimpleNamespace(state="PENDING"))
    with pytest.raises(jobs.JobError, match="expired"):
        jobs.poll("job", "owner")


@pytest.mark.ui
def test_auth_gate_prevents_running_app_without_identity(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("SYSDESIGN_REQUIRE_AUTH", "true")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=90).run()
    assert not at.exception
    assert any(b.label == "Sign in" for b in at.button)
    assert not at.metric


@pytest.mark.ui
def test_background_job_renders_results_after_polling(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from sim import jobs
    from sim.config import presets
    cfg = next(iter(presets().values())).cfg
    payload = execute("simulate", {"config": cfg.to_dict()})
    monkeypatch.setenv("SYSDESIGN_EXECUTION", "celery")
    monkeypatch.setenv("SYSDESIGN_RUN_DB", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setattr(jobs, "submit", lambda *args: "background-job")
    states = iter([("queued", None), ("queued", None)])
    monkeypatch.setattr(jobs, "poll", lambda *args: next(states, ("complete", deepcopy(payload))))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert not at.metric
    at.run()
    assert not at.exception
    assert len(at.metric) == 6
