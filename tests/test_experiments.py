import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from sim.batch import summaries
from sim.config import Config, Event, Workload, config_from_dict
from sim.execution import decode, execute
from sim.experiments import compare_seeds, sweep_load, sweep_replicas
from sim.limits import SimulationLimitError
from sim.telemetry import queue_for


def small():
    return Config(workload=Workload(rps=60, duration_s=2, warmup_s=.25), seed=7)


def test_seed_aggregates_and_paired_differences_match_raw_samples():
    cfg = small()
    candidate = config_from_dict(cfg.to_dict())
    candidate.app.replicas += 1
    report = compare_seeds(cfg, candidate, [7, 8, 9])
    rows = pd.DataFrame(report["rows"])
    for aggregate in report["aggregates"]:
        values = rows[rows.design == aggregate["design"]][aggregate["metric"]]
        assert aggregate["mean"] == pytest.approx(values.mean())
        assert aggregate["sd"] == pytest.approx(values.std())
        assert aggregate["minimum"] == values.min()
        assert aggregate["maximum"] == values.max()
    for delta in report["deltas"]:
        values = rows.pivot(index="seed", columns="design", values=delta["metric"])
        assert delta["mean"] == pytest.approx((values.Candidate - values.Baseline).mean())
    assert cfg.seed == 7 and candidate.seed == 7
    json.dumps(report, allow_nan=False)


def test_identical_designs_have_zero_paired_differences():
    cfg = small()
    report = compare_seeds(cfg, cfg, [7, 8, 9])
    assert all(row["mean"] == 0 and row["sd"] == 0 and row["tied_seeds"] == 3 for row in report["deltas"])


@pytest.mark.parametrize("seeds", [[1, 2], [1, 1, 2], [True, 2, 3], [-1, 2, 3], [1.5, 2, 3], [[], 2, 3], None])
def test_bad_seed_batches_are_rejected(seeds):
    with pytest.raises(ValueError):
        compare_seeds(small(), small(), seeds)


@pytest.mark.parametrize("change", ["workload", "events", "mode"])
def test_confounded_comparisons_are_rejected(change):
    a, b = small(), small()
    if change == "workload":
        b.workload.rps += 1
    elif change == "events":
        b.events = [Event("kill_app", .5, 1, 1)]
    else:
        b.app_only = True
    with pytest.raises(ValueError, match="identical"):
        compare_seeds(a, b, [1, 2, 3])


def test_parallel_sweeps_preserve_point_order_and_values(monkeypatch):
    monkeypatch.setenv("SYSDESIGN_SWEEP_WORKERS", "2")
    cfg = small()
    for function, args in [(sweep_load, ([20, 80, 40],)), (sweep_replicas, ([1, 3], ["least_queue", "random"]))]:
        progress = Mock()
        serial = function(cfg, *args, duration_s=1, warmup_s=.1)
        parallel = function(cfg, *args, duration_s=1, warmup_s=.1, workers=2, progress=progress)
        pd.testing.assert_frame_equal(serial, parallel, check_exact=True)
        assert progress.call_args.args[0] == 1


def test_batch_budget_and_worker_limit_checked_before_execution(monkeypatch):
    monkeypatch.setenv("SYSDESIGN_MAX_BATCH_ARRIVALS", "200")
    with pytest.raises(SimulationLimitError, match="batch"):
        compare_seeds(small(), small(), [1, 2, 3])
    monkeypatch.setenv("SYSDESIGN_MAX_BATCH_ARRIVALS", "10000")
    monkeypatch.setenv("SYSDESIGN_SWEEP_WORKERS", "1")
    with pytest.raises(ValueError, match="workers"):
        summaries([small()], workers=2)


def test_worker_comparison_protocol_and_no_nested_parallelism(monkeypatch):
    import sim.experiments as experiments
    original = experiments.compare_seeds
    call = Mock(wraps=original)
    monkeypatch.setattr(experiments, "compare_seeds", call)
    cfg = small().to_dict()
    report = execute("compare_seeds", dict(baseline=cfg, candidate=cfg, seeds=[1, 2, 3], workers=4))
    assert call.call_args.kwargs["workers"] == 1
    assert decode(json.loads(json.dumps(report))) == report["report"]
    assert queue_for("compare_seeds") == "batch"


def test_traffic_counts_survive_worker_roundtrip():
    cfg = small()
    cfg.policy.rate_limit_rps, cfg.policy.burst = 10, 1
    result = execute("simulate", dict(config=cfg.to_dict()))
    decoded = decode(json.loads(json.dumps(result)))[0]
    assert decoded.traffic == result["traffic"] and decoded.traffic["rate_limited_attempts"] > 0


@pytest.mark.parametrize("failure", ["timeout", "exit"])
def test_parallel_worker_errors_are_actionable(monkeypatch, failure):
    import sim.batch as batch
    if failure == "timeout":
        monkeypatch.setattr(batch.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("worker", 180)))
    else:
        monkeypatch.setattr(batch.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=1, stderr="test worker failure")))
    with pytest.raises(ValueError, match="worker"):
        batch._chunk([(0, small())])
