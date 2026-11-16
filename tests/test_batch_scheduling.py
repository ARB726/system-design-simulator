"""Dynamic scheduling, subprocess lifecycle, and point-by-point progress contracts."""
import subprocess
import sys
from threading import Event, Lock, get_ident

import pytest

from sim import batch
from sim.config import Config, Workload


def small():
    return Config(workload=Workload(rps=20, duration_s=.5, warmup_s=.1), seed=7)




def test_fast_worker_takes_next_points_and_results_keep_input_order(monkeypatch):
    release = Event()
    lock = Lock()
    children, started, active = [], [], [0, 0]

    class Child:
        def __init__(self):
            self.indices, self.closed = [], False
            children.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def close(self):
            self.closed = True
            release.set()

        def run(self, point):
            index, _ = point
            with lock:
                self.indices.append(index)
                started.append(index)
                active[0] += 1
                active[1] = max(active)
            if index == 0:
                assert release.wait(5), "Fast worker never received remaining points"
            if index == 3:
                release.set()
            with lock:
                active[0] -= 1
            return index, {"point": index}

    monkeypatch.setattr(batch, "_Worker", Child)
    monkeypatch.setattr(batch, "worker_limit", lambda: 2)
    progress, callback_threads = [], []
    caller_thread = get_ident()
    def report(value, label):
        progress.append(value)
        callback_threads.append(get_ident())
    result = batch.summaries([small() for _ in range(4)], workers=2,
                             progress=report)
    assert result == [{"point": i} for i in range(4)]
    assert children[0].indices == [0]
    assert children[1].indices == [1, 2, 3]
    assert progress == [.25, .5, .75, 1.]
    assert callback_threads == [caller_thread] * 4
    assert active[1] <= 2 and all(child.closed for child in children)



@pytest.mark.parametrize("failure", ["worker", "progress"])
def test_failure_closes_peers_before_waiting_for_threads(monkeypatch, failure):
    release = Event()
    started = Event()
    children = []

    class Child:
        def __init__(self):
            self.closed = False
            children.append(self)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()
        def close(self):
            self.closed = True
            release.set()
        def run(self, point):
            index, _ = point
            if index == 0:
                started.set()
                assert release.wait(5), "Scheduler joined threads before closing peers"
            else:
                assert started.wait(5)
                if failure == "worker":
                    raise ValueError("worker failed")
            return index, {}

    def progress(*args):
        raise ValueError("progress failed")
    monkeypatch.setattr(batch, "_Worker", Child)
    monkeypatch.setattr(batch, "worker_limit", lambda: 2)
    with pytest.raises(ValueError, match=failure):
        batch.summaries([small(), small()], workers=2, progress=progress if failure == "progress" else None)
    assert all(child.closed for child in children)

