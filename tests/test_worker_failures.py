"""Dynamic scheduling, subprocess lifecycle, and point-by-point progress contracts."""
import subprocess
import sys
from threading import Event, Lock, get_ident

import pytest

from sim import batch
from sim.config import Config, Workload


@pytest.mark.parametrize("returned_index", [True, 1.0])
def test_worker_rejects_noninteger_response_indices(returned_index):
    import io
    import json
    from time import perf_counter
    from unittest.mock import Mock

    child = batch._Worker.__new__(batch._Worker)
    child.started = perf_counter()
    child.process = Mock(stdin=io.StringIO())
    child.messages = Mock()
    child.messages.get.return_value = json.dumps([returned_index, {}])
    with pytest.raises(ValueError, match="worker"):
        child.run((1, small()))


def small():
    return Config(workload=Workload(rps=20, duration_s=.5, warmup_s=.1), seed=7)




@pytest.mark.parametrize("script", ["raise SystemExit(1)", "import time; time.sleep(30)",
                                  "import sys; sys.stdin.readline(); print('bad json', flush=True)",
                                  "import sys; sys.stdin.readline(); print('[99, {}]', flush=True)"])
def test_failed_real_children_are_reaped(monkeypatch, script):
    original = subprocess.Popen
    monkeypatch.setattr(batch.subprocess, "Popen", lambda *args, **kwargs: original([sys.executable, "-c", script], **kwargs))
    monkeypatch.setattr(batch, "WORKER_TIMEOUT_S", 2)
    child = batch._Worker()
    try:
        with pytest.raises(ValueError, match="worker"):
            child.run((0, small()))
    finally:
        child.close()
    assert child.process.poll() is not None and not child.reader.is_alive()

