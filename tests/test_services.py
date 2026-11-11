"""Real service tests run in CI against disposable PostgreSQL/Redis containers."""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.services, pytest.mark.skipif(
    not (os.environ.get("SYSDESIGN_TEST_DATABASE_URL") and os.environ.get("SYSDESIGN_TEST_REDIS_URL")),
    reason="Disposable Redis/PostgreSQL URLs are not configured")]


def test_postgres_library_scope_and_concurrent_capacity(monkeypatch):
    from sim.config import Config
    from sim.history import RunStore
    monkeypatch.setenv("SYSDESIGN_DATABASE_URL", os.environ["SYSDESIGN_TEST_DATABASE_URL"])
    library, other = uuid4().hex, uuid4().hex
    store = RunStore()
    try:
        for i in range(99):
            store.save(library, str(i), Config(), {}, [])
        assert store.list(other) == []
        def save():
            try:
                store.save(library, "Concurrent", Config(), {}, [])
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sum(executor.map(lambda _: save(), range(2))) == 1
        records = store.list(library)
        assert len(records) == 100
        store.delete(other, records[0]["id"])
        assert len(store.list(library)) == 100
    finally:
        for record in store.list(library):
            store.delete(library, record["id"])


def test_redis_admission_is_atomic(monkeypatch):
    from sim import jobs
    monkeypatch.setenv("SYSDESIGN_REDIS_URL", os.environ["SYSDESIGN_TEST_REDIS_URL"])
    jobs.redis_client.cache_clear()
    client = jobs.redis_client()
    prefix = "test:" + uuid4().hex
    keys = [prefix + ":global", prefix + ":owner"]
    try:
        def admit(_):
            return client.eval(jobs.ADMIT, 2, *keys, time.time(), time.time() + 800, uuid4().hex, 32, 2)
        with ThreadPoolExecutor(max_workers=8) as executor:
            assert sum(executor.map(admit, range(8))) == 2
    finally:
        client.delete(*keys)


def test_celery_worker_executes_and_enforces_result_owner(monkeypatch, tmp_path):
    url = os.environ["SYSDESIGN_TEST_REDIS_URL"]
    monkeypatch.setenv("SYSDESIGN_REDIS_URL", url)
    from sim import jobs, worker
    from sim.config import Config, Workload
    from sim.execution import decode
    jobs.redis_client.cache_clear()
    worker.celery_app.conf.update(broker_url=url, result_backend=url)
    hostname = "test@" + uuid4().hex
    owner = uuid4().hex
    with (tmp_path / "worker.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "celery", "-A", "sim.worker:celery_app", "worker",
                                    "--pool=solo", "--concurrency=1", "--hostname=" + hostname],
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if worker.celery_app.control.ping(destination=[hostname], timeout=1):
                    break
                assert process.poll() is None, "Worker exited during startup"
            else:
                pytest.fail("Worker did not become ready")
            cfg = Config(workload=Workload(rps=20, duration_s=10, warmup_s=1))
            job_id = jobs.submit("simulate", {"config": cfg.to_dict()}, owner)
            with pytest.raises(jobs.JobError):
                jobs.poll(job_id, uuid4().hex)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                state, result = jobs.poll(job_id, owner)
                if state == "complete":
                    assert decode(result)[2]["served_rps"] > 0
                    break
                time.sleep(0.1)
            else:
                pytest.fail("Worker did not complete the submitted job")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
