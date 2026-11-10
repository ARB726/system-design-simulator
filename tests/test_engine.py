"""Engine tests. The first group validates the simulator against closed-form queueing theory."""
import pytest

from sim.analysis import summarize, timeline
from sim.config import AppTier, CacheTier, Config, DBTier, Event, Workload, config_from_dict, presets
from sim.engine import run
from sim.theory import erlang_c, mmc_mean_response, mmc_mean_wait


# ---------------------------------------------------------------- theory sanity
def test_erlang_c_reduces_to_rho_for_one_server():
    assert erlang_c(1, 0.6) == pytest.approx(0.6)


def test_mm1_mean_response_formula():
    assert mmc_mean_response(35, 50, 1) == pytest.approx(1 / (50 - 35))


def test_unstable_queue_is_infinite():
    assert mmc_mean_wait(250, 50, 4) == float("inf")


# ---------------------------------------------------------------- simulation vs theory
def _mmc_cfg(c, mu, rho, seed, duration=300):
    return Config(
        app=AppTier(replicas=1, workers=c, latency_ms=1000 / mu, lb_strategy="shared", max_queue=None),
        workload=Workload(rps=rho * c * mu, read_ratio=1.0, duration_s=duration, timeout_ms=None, warmup_s=20),
        seed=seed, app_only=True,
    )


@pytest.mark.parametrize("c,rho", [(1, 0.5), (1, 0.7), (4, 0.5), (4, 0.8), (8, 0.7)])
def test_matches_erlang_c(c, rho):
    """One run is a noisy estimate (delays are strongly autocorrelated), so pool several seeds
    and check the *average* for bias against the closed-form answer."""
    mu = 50.0
    means = []
    for seed in range(6):
        res = run(_mmc_cfg(c, mu, rho, seed=1000 * c + seed))
        means.append(res.requests[res.requests.t >= 20].latency_ms.mean() / 1000)
    sim = sum(means) / len(means)
    theory = mmc_mean_response(rho * c * mu, mu, c)
    assert sim == pytest.approx(theory, rel=0.05)


# ---------------------------------------------------------------- behaviour
def _small(**kw) -> Config:
    base = dict(app=AppTier(replicas=3, workers=8, latency_ms=20), workload=Workload(rps=600, duration_s=40))
    base.update(kw)
    return Config(**base)


def test_same_seed_is_reproducible():
    a, b = run(_small()), run(_small())
    assert a.requests.equals(b.requests)


def test_arrival_count_matches_rate():
    res = run(_small())
    assert len(res.requests) == pytest.approx(600 * 40, rel=0.05)


def test_overload_sheds_load_and_terminates():
    cfg = _small(workload=Workload(rps=2000, duration_s=30))   # capacity is 1200 rps
    res = run(cfg)
    s = summarize(res)
    assert s["success_rate"] < 0.7
    assert s["served_rps"] < 1300
    assert s["tiers"]["app"]["peak_util"] > 0.99


def test_healthy_design_has_no_failures():
    s = summarize(run(_small(workload=Workload(rps=500, duration_s=40))))
    assert s["success_rate"] > 0.999
    assert s["tiers"]["app"]["status"] == "good"


def test_cache_hit_rate_is_respected():
    s = summarize(run(_small(cache=CacheTier(hit_rate=0.7))))
    assert s["measured_hit_rate"] == pytest.approx(0.7, abs=0.03)


def test_cold_cache_event_loads_the_database():
    cfg = _small(workload=Workload(rps=600, duration_s=60), cache=CacheTier(hit_rate=0.95),
                 events=[Event("cold_cache", 20, 10, 0.0)])
    res = run(cfg)
    tl = timeline(res)
    before = tl.loc[10:19, "util_db_primary"].mean()
    during = tl.loc[21:29, "util_db_primary"].mean()
    assert during > 4 * before


def test_replica_crash_causes_failures_only_during_the_event():
    cfg = _small(app=AppTier(replicas=4, workers=8, latency_ms=20), workload=Workload(rps=1000, duration_s=70),
                 events=[Event("kill_app", 25, 20, 2.0)])
    tl = timeline(run(cfg))
    fails = tl.timeout_rps + tl.dropped_rps + tl.error_rps
    assert fails.loc[30:44].mean() > 100
    assert fails.loc[:20].mean() < 5
    assert fails.loc[55:].mean() < 5


def test_traffic_spike_raises_offered_load():
    cfg = _small(events=[Event("traffic_spike", 10, 10, 2.0)])
    tl = timeline(run(cfg))
    assert tl.loc[12:18, "offered_rps"].mean() == pytest.approx(2 * tl.loc[:8, "offered_rps"].mean(), rel=0.15)


def test_db_slowdown_raises_db_utilization():
    cfg = _small(cache=CacheTier(hit_rate=0.5), events=[Event("db_slow", 15, 10, 4.0)])
    tl = timeline(run(cfg))
    assert tl.loc[17:24, "util_db_primary"].mean() > 2.5 * tl.loc[:12, "util_db_primary"].mean()


def test_smart_load_balancing_beats_random_at_high_utilization():
    def p95(strategy):
        cfg = Config(app=AppTier(replicas=4, workers=4, latency_ms=20, lb_strategy=strategy),
                     workload=Workload(rps=660, duration_s=60))
        return summarize(run(cfg))["p95_ms"]

    assert p95("least_queue") < 0.8 * p95("random")


def test_read_replicas_relieve_reads_but_not_writes():
    def db_util(replicas, read_ratio):
        cfg = Config(app=AppTier(replicas=8, workers=8, latency_ms=10), cache=CacheTier(enabled=False),
                     db=DBTier(workers=8, read_ms=10, write_ms=25, read_replicas=replicas),
                     workload=Workload(rps=500, read_ratio=read_ratio, duration_s=40))
        return summarize(run(cfg))["tiers"]["db_primary"]["mean_util"]

    assert db_util(2, 0.95) < 0.6 * db_util(0, 0.95)     # read-heavy: replicas take most of the load
    assert db_util(2, 0.30) > 0.9                        # write-heavy: the primary is still saturated


def test_config_round_trips_through_dict():
    cfg = presets()["Read-heavy: URL shortener"].cfg
    assert config_from_dict(cfg.to_dict()) == cfg


@pytest.mark.parametrize("name", list(presets()))
def test_every_preset_runs(name):
    cfg = presets()[name].cfg
    cfg.workload.duration_s = 30
    res = run(cfg)
    assert len(res.requests) > 0
    assert summarize(res)["bottleneck"] is not None
