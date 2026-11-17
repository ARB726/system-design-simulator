"""Dynamic scheduling, subprocess lifecycle, and point-by-point progress contracts."""
import subprocess
import sys
from threading import Event, Lock, get_ident

import pytest

from sim import batch
from sim.config import Config, Workload


def test_expired_worker_does_not_accept_queued_result_or_send_work(monkeypatch):
    import io
    from unittest.mock import Mock

    child = batch._Worker.__new__(batch._Worker)
    child.started = 0
    child.process = Mock(stdin=io.StringIO())
    child.messages = Mock()
    child.messages.get.return_value = '[0, {}]'
    monkeypatch.setattr(batch, "perf_counter", lambda: batch.WORKER_TIMEOUT_S + 1)
    with pytest.raises(ValueError, match="timed out"):
        child.run((0, small()))
    assert child.process.stdin.getvalue() == ""
    child.messages.get.assert_not_called()


def small():
    return Config(workload=Workload(rps=20, duration_s=.5, warmup_s=.1), seed=7)




def test_invalid_batch_rejected_before_children_start(monkeypatch):
    monkeypatch.setattr(batch, "_Worker", lambda: pytest.fail("Must validate first"))
    cfg = small()
    cfg.seed = -1
    with pytest.raises(ValueError):
        batch.summaries([small(), cfg], workers=2)



def test_assigning_another_point_does_not_reset_lifetime_budget(monkeypatch):
    import io
    from unittest.mock import Mock
    child = batch._Worker.__new__(batch._Worker)
    child.started = 0
    child.process = Mock(stdin=io.StringIO())
    child.messages = Mock()
    child.messages.get.side_effect = ['[0, {}]', '[1, {}]']
    ticks = iter([10, 20])
    monkeypatch.setattr(batch, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(batch, "WORKER_TIMEOUT_S", 30)
    child.run((0, small()))
    child.run((1, small()))
    assert [call.kwargs["timeout"] for call in child.messages.get.call_args_list] == [20, 10]
