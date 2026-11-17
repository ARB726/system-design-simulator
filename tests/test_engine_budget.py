"""Cached operational limits preserve seeded behavior and still bound real work."""
import pandas as pd
import pytest

from sim.engine import Simulation
from sim.limits import SimulationLimitError, arrival_limit
from tools.profile_engine import cases


class LegacyBudgetSimulation(Simulation):
    @property
    def arrival_budget(self):
        return arrival_limit()

    @arrival_budget.setter
    def arrival_budget(self, value):
        pass


@pytest.mark.parametrize("name", ["baseline", "overload", "retries", "queued_writes"])
@pytest.mark.parametrize("seed", [7, 23])
def test_cached_limit_preserves_full_and_summary_results(name, seed):
    cfg = cases()[name]
    cfg.workload.duration_s, cfg.workload.warmup_s, cfg.seed = 2, .2, seed
    old = LegacyBudgetSimulation(cfg).run()
    new = Simulation(cfg).run()
    for left, right in [(old.requests, new.requests), (old.series, new.series), (old.lag, new.lag)]:
        pd.testing.assert_frame_equal(left, right, check_exact=True)
    assert old.traffic == new.traffic and old.warnings == new.warnings
    assert LegacyBudgetSimulation(cfg, summary_only=True).run() == Simulation(cfg, summary_only=True).run()


def test_limit_is_read_once_per_run_and_refreshed_for_new_runs(monkeypatch):
    from sim.config import Config, Workload
    import sim.engine as engine
    calls = []
    def budget():
        calls.append(None)
        return 100000
    monkeypatch.setattr(engine, "arrival_limit", budget)
    cfg = Config(workload=Workload(rps=100, duration_s=1, warmup_s=.1))
    sim = Simulation(cfg)
    sim.run()
    assert len(calls) == 1
    Simulation(cfg)
    assert len(calls) == 2


@pytest.mark.parametrize("attempt_budget", [False, True])
def test_runtime_budget_still_stops_work(attempt_budget):
    from sim.config import Config, Workload
    cfg = Config(workload=Workload(rps=100, duration_s=1, warmup_s=.1))
    sim = Simulation(cfg)
    sim.arrival_budget = 1
    if attempt_budget:
        sim.attempt_count = 1
        sim.env.process(sim._request())
        with pytest.raises(SimulationLimitError, match="request-attempt budget"):
            sim.env.run()
    else:
        with pytest.raises(SimulationLimitError, match="arrival budget"):
            sim.run()
