"""Differential checks against the pre-optimization engine algorithms."""
import random
from types import SimpleNamespace

import pandas as pd
import pytest
import simpy

from sim.config import Config, Event, config_from_dict, presets
from sim.engine import Events, Tier, run, run_summary


def legacy_pick(self, lo, hi, strategy, rng):
    n = hi - lo
    if n <= 0:
        return None
    if n == 1 or strategy == "shared":
        return lo
    if strategy == "random":
        return lo + rng.randrange(n)
    if strategy == "round_robin":
        self._rr += 1
        return lo + self._rr % n
    loads = [self.load(i) for i in range(lo, hi)]
    best = min(loads)
    ties = [lo + i for i, value in enumerate(loads) if value == best]
    return ties[0] if len(ties) == 1 else rng.choice(ties)


def legacy_factor(events, t):
    factor = 1.0
    for event in [e for e in events if e.start_s <= t < e.end_s]:
        factor *= event.magnitude
    return factor


@pytest.mark.parametrize("strategy", ["least_queue", "random", "round_robin", "shared"])
def test_routing_matches_legacy_choices_and_rng_state(strategy):
    tier = Tier(simpy.Environment(), 8, 4, None)
    reference = Tier(simpy.Environment(), 8, 4, None)
    rng, old_rng, workload = random.Random(17), random.Random(17), random.Random(19)
    # Repeated routing with changing busy counts, queues, subranges, and ties.
    for _ in range(400):
        nodes = [SimpleNamespace(count=workload.randrange(5),
                                 queue=[None] * workload.randrange(4)) for _ in range(8)]
        tier.nodes = reference.nodes = nodes
        lo = workload.randrange(8)
        hi = workload.randrange(lo, 9)
        assert tier.pick(lo, hi, strategy, rng) == legacy_pick(reference, lo, hi, strategy, old_rng)
        assert rng.getstate() == old_rng.getstate()


@pytest.mark.parametrize("t", [0, 1, 1.999999, 2, 3, 3.999999, 4, 5, 6])
def test_event_overlap_and_half_open_boundaries(t):
    cfg = Config(events=[Event(kind, start, duration, magnitude)
                         for kind, magnitude in [("traffic_spike", 2), ("kill_app", 1), ("db_slow", 3)]
                         for start, duration in [(1, 3), (2, 2)]])
    events = Events(cfg)
    assert events.arrival_factor(t) == legacy_factor(events.spikes, t)
    assert events.db_factor(t) == legacy_factor(events.slow, t)
    assert events.killed(t) == sum(int(e.magnitude) for e in events.kills if e.start_s <= t < e.end_s)


def test_empty_event_lists_have_identity_values():
    events = Events(Config())
    assert (events.arrival_factor(0), events.db_factor(0), events.killed(0)) == (1, 1, 0)


@pytest.mark.parametrize("name", list(presets()))
@pytest.mark.parametrize("seed", [7, 29])
def test_full_and_summary_outputs_match_previous_engine(monkeypatch, name, seed):
    cfg = config_from_dict(presets()[name].cfg.to_dict())
    cfg.seed = seed
    # Compress time, not load: retain event order/overlap and exercise failures
    # and recovery without replaying several minutes per differential fixture.
    scale = min(1.0, 8 / cfg.workload.duration_s)
    cfg.workload.duration_s *= scale
    cfg.workload.warmup_s *= scale
    for event in cfg.events:
        event.start_s *= scale
        event.duration_s *= scale
    optimized = run(cfg)
    optimized_summary = run_summary(cfg)
    monkeypatch.setattr(Tier, "pick", legacy_pick)
    monkeypatch.setattr(Events, "arrival_factor", lambda self, t: legacy_factor(self.spikes, t))
    monkeypatch.setattr(Events, "db_factor", lambda self, t: legacy_factor(self.slow, t))
    monkeypatch.setattr(Events, "killed", lambda self, t: sum(
        int(e.magnitude) for e in [e for e in self.kills if e.start_s <= t < e.end_s]))
    reference = run(cfg)
    pd.testing.assert_frame_equal(optimized.requests, reference.requests, check_exact=True)
    pd.testing.assert_frame_equal(optimized.series, reference.series, check_exact=True)
    pd.testing.assert_frame_equal(optimized.lag, reference.lag, check_exact=True)
    assert optimized.warnings == reference.warnings
    assert optimized_summary == run_summary(cfg)
