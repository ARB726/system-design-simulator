import pytest

from sim.challenges import challenges, default_design, score_design, screen
from sim.config import AppTier, CacheTier, CDNTier, Config, DBTier, QueueTier, Workload, expected_utilization
from sim.predict import bucket_of, truth_from_summary


def test_truth_from_summary_counts_near_ties_as_same_bottleneck():
    summary = {
        "tiers": {
            "app": {"mean_util": 0.60},
            "db_primary": {"mean_util": 0.57},
            "cache": {"mean_util": 0.10},
        },
        "p95_ms": 240.0,
    }

    truth = truth_from_summary(summary)

    assert truth["bottleneck"] == "app"
    assert set(truth["accepted"]) == {"app", "db_primary"}
    assert truth["p95_bucket"] == 2


def test_screen_keeps_obviously_bad_designs_out():
    ch = challenges()["launch"]
    bad = dict(
        app_replicas=2,
        app_workers=4,
        cache=False,
        cdn=False,
        db_workers=4,
        shards=1,
        read_replicas=0,
        queue=False,
        consumers=8,
    )
    good = dict(
        app_replicas=3,
        app_workers=8,
        cache=True,
        cdn=False,
        db_workers=16,
        shards=1,
        read_replicas=0,
        queue=False,
        consumers=8,
    )

    assert screen(ch, bad) is False
    assert screen(ch, good) is True


def test_load_optima_returns_empty_dict_for_missing_or_invalid_json(tmp_path, monkeypatch):
    import sim.challenges as challenges_mod

    bad_path = tmp_path / "optima.json"
    bad_path.write_text("{not valid json}", encoding="utf-8")
    monkeypatch.setattr(challenges_mod, "OPTIMA_PATH", str(bad_path))
    assert challenges_mod.load_optima() == {}

    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(challenges_mod, "OPTIMA_PATH", str(missing_path))
    assert challenges_mod.load_optima() == {}


def test_expected_utilization_reflects_cdn_and_cache_wins():
    base = Config(
        app=AppTier(replicas=3, workers=8, latency_ms=20),
        cache=CacheTier(enabled=False),
        cdn=CDNTier(enabled=False),
        db=DBTier(workers=16, read_ms=8, write_ms=25),
        workload=Workload(rps=600, read_ratio=0.9, duration_s=25),
    )
    tuned = Config(
        app=AppTier(replicas=3, workers=8, latency_ms=20),
        cache=CacheTier(enabled=True, hit_rate=0.7),
        cdn=CDNTier(enabled=True, hit_rate=0.5),
        db=DBTier(workers=16, read_ms=8, write_ms=25),
        workload=Workload(rps=600, read_ratio=0.9, duration_s=25),
    )

    base_util = expected_utilization(base)
    tuned_util = expected_utilization(tuned)

    assert base_util["app"] > tuned_util["app"]
    assert "cache" in tuned_util
    assert tuned_util["app"] < 1.0
    assert tuned_util["db_primary"] < base_util["db_primary"]


def test_default_design_snaps_to_first_allowed_value_when_base_is_out_of_grid():
    ch = challenges()["launch"]
    ch.base.app.replicas = 99
    ch.knobs["app_replicas"] = [2, 4, 6]

    d = default_design(ch)

    assert d["app_replicas"] == 2
    assert d["cache"] in (True, False)


def test_score_design_allows_cost_efficiency_to_raise_total_score():
    ch = challenges()["launch"]
    design = dict(
        app_replicas=3,
        app_workers=8,
        cache=True,
        cdn=False,
        db_workers=16,
        shards=1,
        read_replicas=0,
        queue=False,
        consumers=8,
    )

    results = [
        {"passed": True},
        {"passed": True},
        {"passed": True},
    ]
    score = score_design(ch, design, results, optimum_cost=200)

    assert score["all_pass"] is True
    assert score["reliability"] == pytest.approx(70.0)
    assert score["cost_pts"] > 0
    assert score["total_score"] > 70


def test_bucket_of_uses_expected_boundaries():
    assert bucket_of(49.9) == 0
    assert bucket_of(50.0) == 1
    assert bucket_of(150.0) == 2
    assert bucket_of(500.0) == 3
    assert bucket_of(1000.0) == 3
