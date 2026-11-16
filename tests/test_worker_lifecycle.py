"""Dynamic scheduling, subprocess lifecycle, and point-by-point progress contracts."""
import subprocess
import sys
from threading import Event, Lock, get_ident

import pytest

from sim import batch
from sim.config import Config, Workload


def small():
    return Config(workload=Workload(rps=20, duration_s=.5, warmup_s=.1), seed=7)




def test_real_child_reused_and_reaped():
    from sim.engine import run_summary
    cfg = small()
    child = batch._Worker()
    try:
        pid = child.process.pid
        assert child.run((2, cfg)) == (2, run_summary(cfg))
        cfg.seed = 9
        assert child.run((0, cfg)) == (0, run_summary(cfg))
        assert child.process.pid == pid and child.process.poll() is None
    finally:
        child.close()
    assert child.process.poll() is not None and not child.reader.is_alive()
    child.close()  # Cleanup is safe when a failure path already closed a worker.



def test_start_failure_closes_temporary_file(monkeypatch):
    import io
    stderr = io.StringIO()
    monkeypatch.setattr(batch.tempfile, "TemporaryFile", lambda **kwargs: stderr)
    def fail(*args, **kwargs):
        raise OSError("cannot launch")
    monkeypatch.setattr(batch.subprocess, "Popen", fail)
    with pytest.raises(ValueError, match="could not start"):
        batch._Worker()
    assert stderr.closed

