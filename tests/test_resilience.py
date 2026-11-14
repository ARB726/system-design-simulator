"""Admission control and retry semantics, including model accounting."""
import pandas as pd
import pytest

from sim.analysis import summarize, timeline
from sim.config import Config, Event, TrafficPolicy, Workload, config_from_dict
from sim.engine import Simulation, run, run_summary
from sim.experiments import _quick
from sim.limits import SimulationLimitError, validate_config


def small(policy=None):
    return Config(workload=Workload(rps=80, duration_s=2, warmup_s=.25, timeout_ms=100),
                  policy=policy or TrafficPolicy(), seed=7)


def test_old_snapshots_receive_disabled_policy():
    data = small().to_dict()
    data.pop("policy")
    assert config_from_dict(data).policy == TrafficPolicy()
    assert config_from_dict(small(TrafficPolicy(max_retries=2, rate_limit_rps=10)).to_dict()).policy.max_retries == 2


@pytest.mark.parametrize("read", [True, False])
def test_retry_backoff_and_write_safety(read):
    cfg = small(TrafficPolicy(max_retries=3, backoff_ms=100, jitter=False))
    cfg.workload.read_ratio = int(read)
    cfg.workload.warmup_s = 0
    sim = Simulation(cfg)
    times = []
    def attempt(is_read, **kwargs):
        times.append(sim.env.now)
        yield sim.env.timeout(.01)
        return ("ok" if len(times) == 3 else "error"), None, False
    sim._attempt = attempt
    sim.env.process(sim._request())
    sim.env.run()
    assert times == pytest.approx([0, .11, .32] if read else [0])
    assert sim.traffic["attempts"] == (3 if read else 1)
    assert sim.traffic["retries"] == (2 if read else 0)
    assert len(sim.records) == 1
    assert sim.records[0][2] == ("ok" if read else "error")
    assert sim.records[0][1] == pytest.approx(.33 if read else .01)


def test_retries_are_bounded_and_backoff_is_capped():
    cfg = small(TrafficPolicy(max_retries=3, backoff_ms=5000, backoff_multiplier=4, jitter=False))
    cfg.workload.read_ratio, cfg.workload.warmup_s = 1, 0
    sim = Simulation(cfg)
    times = []
    def failed(is_read, **kwargs):
        times.append(sim.env.now)
        yield sim.env.timeout(.01)
        return "error", None, False
    sim._attempt = failed
    sim.env.process(sim._request())
    sim.env.run()
    assert times == pytest.approx([0, 5.01, 15.02, 25.03])
    assert sim.traffic["retries"] == 3
    assert sim.records[0][2] == "error"


def test_token_bucket_burst_refill_and_rejected_denominator():
    cfg = small(TrafficPolicy(rate_limit_rps=2, burst=1))
    cfg.workload.warmup_s = 0
    cfg.app_only = True
    cfg.app.latency_ms = .001
    sim = Simulation(cfg)
    def arrivals():
        for delay in [0, .25, .25]:
            yield sim.env.timeout(delay)
            sim.env.process(sim._request())
    sim.env.process(arrivals())
    sim.env.run()
    assert [record[2] for record in sim.records] == ["ok", "rate_limited", "ok"]
    assert {key: sim.traffic[key] for key in ("logical_requests", "attempts", "retries", "rate_limited_attempts")} == dict(
        logical_requests=3, attempts=3, retries=0, rate_limited_attempts=1)
    assert sim.traffic["to_app"] == 2


def test_each_retry_reacquires_admission_and_can_recover():
    cfg = small(TrafficPolicy(max_retries=3, backoff_ms=100, jitter=False, rate_limit_rps=2, burst=1))
    cfg.workload.read_ratio, cfg.workload.warmup_s = 1, 0
    cfg.app.replicas, cfg.app.latency_ms, cfg.db.read_ms = 1, .001, .001
    cfg.cache.enabled = False
    cfg.events = [Event("kill_app", 0, .5, 1)]
    sim = Simulation(cfg)
    sim.env.process(sim._request())
    sim.env.run()
    assert sim.records[0][2] == "ok"
    assert sim.traffic["attempts"] == 4
    assert sim.traffic["rate_limited_attempts"] == 2
    assert sim.traffic["to_app"] == 2
    assert sim.records[0][1] >= .7


@pytest.mark.parametrize("policy", [TrafficPolicy(max_retries=3),
    TrafficPolicy(max_retries=2, jitter=False, rate_limit_rps=10, burst=2),
    TrafficPolicy(rate_limit_rps=5, burst=1)])
def test_policy_outputs_are_reproducible_and_summary_equivalent(policy):
    cfg = small(policy)
    cfg.app.workers, cfg.app.replicas, cfg.app.max_queue = 1, 1, 2
    cfg.app.latency_ms = 100
    result = run(cfg)
    pd.testing.assert_frame_equal(result.requests, run(cfg).requests, check_exact=True)
    assert run_summary(cfg) == pytest.approx(_quick(result), abs=1e-12, rel=1e-12)
    summary = summarize(result, timeline(result))
    assert sum(summary["fail"].values()) == pytest.approx(len(result.requests[result.requests.t >= .25]) * (1 - summary["success_rate"]))
    assert result.traffic["attempts"] >= result.traffic["logical_requests"]
    if policy.rate_limit_rps:
        assert result.traffic["rate_limited_attempts"] > 0
        assert summary["success_rate"] < 1
    if policy.max_retries:
        assert result.traffic["attempts"] > result.traffic["logical_requests"]
        failed = result.requests[~result.requests.status.isin(["ok", "incomplete"])]
        assert (failed.eff_ms >= failed.latency_ms).all()


@pytest.mark.parametrize("field,value", [("max_retries", 4), ("max_retries", True), ("max_retries", 1.5),
    ("backoff_ms", 0), ("backoff_multiplier", float("inf")), ("jitter", 1),
    ("rate_limit_rps", 0), ("burst", 0)])
def test_invalid_policies_are_rejected(field, value):
    cfg = small()
    setattr(cfg.policy, field, value)
    with pytest.raises(SimulationLimitError):
        validate_config(cfg)


def test_retry_attempts_count_toward_admission_budget(monkeypatch):
    monkeypatch.setenv("SYSDESIGN_MAX_ARRIVALS", "1000")
    cfg = small(TrafficPolicy(max_retries=3))
    cfg.workload.rps = 200
    with pytest.raises(SimulationLimitError, match="budget"):
        validate_config(cfg)
