"""Compact execution must preserve full-trace statistics, not approximate them."""
import pytest

from sim.config import Config, Workload, Event
from sim.engine import Simulation, run, run_summary
from sim.experiments import _quick, sweep_load, sweep_replicas


def scenario(name):
    cfg = Config(workload=Workload(rps=100, duration_s=3, warmup_s=.5))
    if name == "overload":
        cfg.app.workers = 1
        cfg.app.replicas = 1
        cfg.app.max_queue = 2
        cfg.app.latency_ms = 100
    elif name == "no_timeout":
        cfg.workload.timeout_ms = None
        cfg.app.workers = 1
        cfg.app.replicas = 1
        cfg.app.max_queue = 2
        cfg.app.latency_ms = 500
    elif name == "async":
        cfg.queue.enabled = True
        cfg.queue.max_depth = 2
        cfg.workload.read_ratio = 0
        cfg.db.write_ms = 100
    elif name == "chaos":
        cfg.events = [Event("kill_app", .5, 1, 3), Event("cold_cache", .2, 1, 0)]
    elif name == "shards":
        cfg.db.shards = 4
        cfg.db.read_replicas = 2
        cfg.cdn.enabled = True
    elif name == "empty":
        cfg.workload.rps = .01
    elif name == "shared":
        cfg.app.lb_strategy = "shared"
    elif name == "app_only":
        cfg.app_only = True
    return cfg


@pytest.mark.parametrize("name", ["baseline", "overload", "no_timeout", "async", "chaos",
                                 "shards", "empty", "shared", "app_only"])
@pytest.mark.parametrize("seed", [7, 23])
def test_summary_matches_full_trace(name, seed):
    cfg = scenario(name)
    cfg.seed = seed
    assert run_summary(cfg) == pytest.approx(_quick(run(cfg)), rel=1e-12, abs=1e-12)


def test_summary_does_not_retain_trace_artifacts():
    sim = Simulation(scenario("async"), summary_only=True)
    sim.run()
    assert not sim.records and not sim.samples and not sim.lag
    assert sim.latencies.itemsize == 8


def test_no_timeout_failure_penalty_includes_warmup_maximum():
    cfg = scenario("no_timeout")
    sim = Simulation(cfg, summary_only=True)
    sim._record(0, 10, "ok", True, None, False)
    sim._record(1, .1, "dropped", True, None, False)
    sim._record(1.5, .2, "incomplete", True, None, False)
    # Stop new arrivals; check finalization of the explicitly seeded records.
    def no_arrivals():
        yield sim.env.timeout(100)
    sim._arrivals = no_arrivals
    summary = sim.run()
    assert summary["p50_ms"] == pytest.approx(5100)
    assert summary["success_rate"] == 0


def test_sweeps_use_compact_path_with_unchanged_results(monkeypatch):
    import sim.experiments as experiments
    cfg = scenario("baseline")
    compact_load = sweep_load(cfg, [20, 100], duration_s=3, warmup_s=.5)
    compact_replicas = sweep_replicas(cfg, [1, 3], ["least_queue", "shared"], duration_s=3, warmup_s=.5)
    monkeypatch.setattr(experiments, "run_summary", lambda cfg: _quick(run(cfg)))
    assert compact_load.equals(sweep_load(cfg, [20, 100], duration_s=3, warmup_s=.5))
    assert compact_replicas.equals(sweep_replicas(cfg, [1, 3], ["least_queue", "shared"], duration_s=3, warmup_s=.5))
