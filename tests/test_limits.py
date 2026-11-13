"""Boundary checks that must hold even when callers bypass the UI."""
import pytest
from sim.config import Config, Event
from sim.limits import SimulationLimitError, validate_config

@pytest.mark.parametrize("group,field,value", [
    ("app", "replicas", True), ("app", "workers", 1.5),
    ("app", "latency_ms", float("inf")), ("app", "lb_strategy", "unknown"),
    ("db", "hot_share", 1.01), ("cache", "hit_rate", -0.01),
    ("queue", "max_depth", 0), ("cdn", "latency_ms", 0),
])
def test_invalid_tier_settings(group, field, value):
    cfg = Config()
    setattr(getattr(cfg, group), field, value)
    with pytest.raises(SimulationLimitError):
        validate_config(cfg)

@pytest.mark.parametrize("event", [
    Event("unknown", 0, 1, 1), Event("cold_cache", 0, 1, 1.1),
    Event("kill_app", 0, 1, 1.5), Event("db_slow", 0, 1, 0),
    Event("traffic_spike", -1, 1, 2), Event("traffic_spike", 0, 0, 2),
])
def test_invalid_chaos_events(event):
    cfg = Config(events=[event])
    with pytest.raises(SimulationLimitError):
        validate_config(cfg)

def test_overlapping_spikes_count_toward_budget(monkeypatch):
    monkeypatch.setenv("SYSDESIGN_MAX_ARRIVALS", "1000")
    cfg = Config(events=[Event("traffic_spike", 1, 2, 2)] * 2)
    cfg.workload.rps = 10
    cfg.workload.duration_s = 30
    with pytest.raises(SimulationLimitError, match="budget"):
        validate_config(cfg)
    cfg.events.pop()
    validate_config(cfg)

def test_event_count_limit():
    cfg = Config(events=[Event("cold_cache", 0, 1, 0)] * 8)
    validate_config(cfg)
    cfg.events.append(Event("cold_cache", 0, 1, 0))
    with pytest.raises(SimulationLimitError, match="eight"):
        validate_config(cfg)

def test_optional_limits_and_integer_replica_loss_are_valid():
    cfg = Config(events=[Event("kill_app", 0, 1, 1)])
    cfg.workload.timeout_ms = None
    cfg.app.max_queue = None
    cfg.db.max_queue = None
    validate_config(cfg)
