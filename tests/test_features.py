"""Tests for CDN, write queue, shards, cost model, challenges and predict-then-run."""
import copy

import pytest

from sim.analysis import diagnose, summarize, timeline
from sim.challenges import (apply_design, challenges, default_design, design_cost, enumerate_designs, load_optima,
                            run_suite, score_design)
from sim.config import (AppTier, CacheTier, CDNTier, Config, DBTier, Event, QueueTier, Workload, config_from_dict,
                        cost_breakdown, monthly_cost, presets)
from sim.engine import Simulation
from sim.predict import BUCKETS, Prediction, bucket_of, score_prediction


def sim(cfg):
    res = Simulation(cfg).run()
    tl = timeline(res)
    return res, tl, summarize(res, tl)


def base(**kw):
    cfg = Config(
        app=AppTier(replicas=6, workers=8, latency_ms=15),
        cache=CacheTier(hit_rate=0.8),
        db=DBTier(workers=16, read_ms=8, write_ms=25),
        workload=Workload(rps=500, read_ratio=0.8, duration_s=30, timeout_ms=1000),
        seed=5,
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------- CDN
def test_cdn_offloads_reads_from_the_app_tier():
    off = sim(base())[2]
    on = sim(base(cdn=CDNTier(enabled=True, hit_rate=0.6)))[2]
    share = on["flows"]["cdn_hits"] / on["flows"]["offered"]
    assert share == pytest.approx(0.8 * 0.6, abs=0.04)          # 80% reads x 60% edge hits
    assert on["flows"]["to_app"] < 0.6 * off["flows"]["to_app"]
    assert on["tiers"]["app"]["mean_util"] < off["tiers"]["app"]["mean_util"]


# ---------------------------------------------------------------- write queue
def write_heavy(queue):
    return base(workload=Workload(rps=600, read_ratio=0.2, duration_s=30, timeout_ms=1000),
                db=DBTier(workers=12, read_ms=8, write_ms=25),
                queue=queue,
                events=[Event("traffic_spike", 8, 8, 1.6)])


def test_queue_keeps_clients_fast_during_a_burst_and_reports_lag():
    direct = sim(write_heavy(QueueTier()))[2]
    queued = sim(write_heavy(QueueTier(enabled=True, consumers=12, max_depth=20000)))[2]
    assert direct["success_rate"] < 0.97                          # database saturates, writes time out
    assert queued["success_rate"] > 0.99
    assert queued["queue"]["lag_p95_s"] > 0.5                     # but acknowledged writes land late
    assert queued["p95_ms"] < direct["p95_ms"]


def test_full_queue_rejects_writes():
    s = sim(write_heavy(QueueTier(enabled=True, consumers=4, max_depth=200)))[2]
    assert s["fail"]["dropped"] > 0
    assert s["queue"]["max_depth"] >= 190


def test_queue_drains_after_the_burst():
    cfg = write_heavy(QueueTier(enabled=True, consumers=16, max_depth=20000))
    cfg.db.workers = 16                       # 640 writes/s of drain capacity vs ~770/s at the peak
    res, tl, s = sim(cfg)
    assert s["queue"]["max_depth"] > 200      # a real backlog formed...
    assert s["queue"]["end_depth"] < 0.05 * s["queue"]["max_depth"] + 5   # ...and then drained


# ---------------------------------------------------------------- shards
def test_hot_shard_carries_more_load_than_the_others():
    cfg = base(db=DBTier(workers=8, read_ms=8, write_ms=25, shards=4, hot_share=0.6),
               workload=Workload(rps=500, read_ratio=0.3, duration_s=30, timeout_ms=1000))
    s = sim(cfg)[2]
    sh = s["shards"]
    assert len(sh) == 4
    assert sh[0] > 2 * (sum(sh[1:]) / 3)


def test_even_shards_are_balanced():
    cfg = base(db=DBTier(workers=8, read_ms=8, write_ms=25, shards=4),
               workload=Workload(rps=500, read_ratio=0.3, duration_s=30, timeout_ms=1000))
    sh = sim(cfg)[2]["shards"]
    assert max(sh) < 1.35 * min(sh)


def test_findings_name_the_hot_shard():
    cfg = presets()["Sharding: the hot key"].cfg
    res, tl, s = sim(cfg)
    titles = " ".join(f["title"] for f in diagnose(res, s, tl))
    assert "Shard 0" in titles


# ---------------------------------------------------------------- cost
def test_cost_model_adds_up():
    cfg = base(cdn=CDNTier(enabled=True), queue=QueueTier(enabled=True, consumers=10),
               db=DBTier(workers=10, shards=2, read_replicas=1))
    bd = cost_breakdown(cfg)
    assert bd["App tier"] == 6 * (15 + 6 * 8)
    assert bd["Cache"] == 50 and bd["CDN"] == 40
    assert bd["Write queue"] == 30 + 4 * 10
    assert bd["Database"] == 2 * 2 * (60 + 12 * 10)
    assert monthly_cost(cfg) == sum(bd.values())


def test_config_roundtrip_keeps_new_fields():
    cfg = base(cdn=CDNTier(enabled=True, hit_rate=0.5), queue=QueueTier(enabled=True, consumers=3),
               db=DBTier(shards=3, hot_share=0.4))
    again = config_from_dict(copy.deepcopy(cfg.to_dict()))
    assert again.to_dict() == cfg.to_dict()


def test_every_preset_runs():
    for name, p in presets().items():
        c = copy.deepcopy(p.cfg)
        c.workload.duration_s = 20
        c.events = [Event(e.kind, min(e.start_s, 8), min(e.duration_s, 6), e.magnitude) for e in c.events]
        assert sim(c)[2]["offered_rps"] > 0, name


# ---------------------------------------------------------------- challenges
def test_designs_enumerate_in_cost_order_and_are_unique():
    for ch in challenges().values():
        ds = enumerate_designs(ch)
        costs = [design_cost(ch, d) for d in ds]
        assert costs == sorted(costs)
        sigs = {tuple(sorted(d.items())) for d in ds}
        assert len(sigs) == len(ds)


def test_apply_design_changes_only_the_design():
    ch = challenges()["launch"]
    d = dict(default_design(ch), app_replicas=7, cdn=True)
    cfg = apply_design(ch.base, d)
    assert cfg.app.replicas == 7 and cfg.cdn.enabled
    assert ch.base.app.replicas == 3 and not ch.base.cdn.enabled          # base untouched
    assert cfg.workload.rps == ch.base.workload.rps


def test_default_designs_fail_a_hidden_test():
    ch = challenges()["launch"]
    rs = run_suite(ch, default_design(ch))
    assert rs[0]["passed"]                                   # fine on a normal day
    assert not all(r["passed"] for r in rs)                  # but not under chaos


def test_grading_is_deterministic():
    ch = challenges()["cache"]
    d = default_design(ch)
    a = run_suite(ch, d)
    b = run_suite(ch, d)
    assert [(r["passed"], round(r["p99_ms"], 3)) for r in a] == [(r["passed"], round(r["p99_ms"], 3)) for r in b]


@pytest.mark.parametrize("cid", list(challenges()))
def test_stored_optimum_really_passes(cid):
    opt = load_optima().get(cid, {}).get("optimum")
    if not opt:
        pytest.skip("run tools/optimize.py first")
    ch = challenges()[cid]
    assert all(r["passed"] for r in run_suite(ch, opt))
    assert design_cost(ch, opt) <= ch.budget


def test_score_formula():
    ch = challenges()["launch"]
    d = default_design(ch)
    ok = [dict(passed=True)] * 3
    s = score_design(ch, d, ok, optimum_cost=design_cost(ch, d) / 2)
    assert s["reliability"] == pytest.approx(70)
    assert s["cost_pts"] == pytest.approx(15)
    s = score_design(ch, d, [dict(passed=True), dict(passed=False), dict(passed=True)], optimum_cost=100)
    assert s["cost_pts"] == 0 and s["reliability"] == pytest.approx(70 * 2 / 3)


# ---------------------------------------------------------------- predict-then-run
def fake_summary(util=0.62, p95=120.0):
    return dict(p95_ms=p95, tiers={"app": dict(mean_util=0.30), "db_primary": dict(mean_util=util),
                                   "cache": dict(mean_util=0.02)})


def test_buckets():
    assert [bucket_of(x) for x in (10, 49.9, 50, 149, 150, 499, 500, 5000)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert len(BUCKETS) == 4


def test_perfect_prediction_scores_full_marks():
    ps = score_prediction(Prediction("db_primary", 0.62, 1, True), fake_summary(), True)
    assert ps["total"] == 100 and not ps["notes"]


def test_scoring_parts():
    s = fake_summary()
    assert score_prediction(Prediction("app", 0.62, 1, True), s, True)["parts"]["bottleneck"] == 0
    assert score_prediction(Prediction("db_primary", 0.62 + 0.15, 1, True), s, True)["parts"]["util"] == pytest.approx(15)
    assert score_prediction(Prediction("db_primary", 0.62 + 0.5, 1, True), s, True)["parts"]["util"] == 0
    assert score_prediction(Prediction("db_primary", 0.62, 2, True), s, True)["parts"]["p95"] == 10      # adjacent
    assert score_prediction(Prediction("db_primary", 0.62, 3, True), s, True)["parts"]["p95"] == 0
    assert score_prediction(Prediction("db_primary", 0.62, 1, False), s, True)["parts"]["holds"] == 0


def test_near_ties_both_count_as_the_bottleneck():
    s = dict(p95_ms=40.0, tiers={"app": dict(mean_util=0.60), "db_primary": dict(mean_util=0.57)})
    assert score_prediction(Prediction("app", 0.6, 0, True), s, True)["parts"]["bottleneck"] == 40
    assert score_prediction(Prediction("db_primary", 0.6, 0, True), s, True)["parts"]["bottleneck"] == 40


# ---------------------------------------------------------------- replay and share card
def test_replay_figure_has_one_frame_per_second_and_controls():
    from sim import charts
    cfg = presets()["Async writes: absorb a burst"].cfg
    cfg = copy.deepcopy(cfg)
    cfg.workload.duration_s = 20
    cfg.events = [Event("traffic_spike", 6, 6, 1.8)]
    res, tl, s = sim(cfg)
    fig = charts.replay_figure(res, tl)
    assert len(fig.frames) == len(tl)
    assert len(fig.layout.sliders[0].steps) == len(tl)
    assert [b.label for b in fig.layout.updatemenus[0].buttons] == ["▶ Play", "❚❚ Pause"]
    assert any("Traffic spike" in f.layout.title.text for f in fig.frames)


def test_share_card_is_a_valid_png_of_the_right_size():
    import io
    from PIL import Image
    from sim.sharecard import design_lines, make_card
    ch = challenges()["launch"]
    png = make_card(ch.title, 91.0, 2, "Engineer", 3, "3/3", 380.0, 352.0, design_lines(default_design(ch)),
                    theme="Sunset", calibration=88)
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630) and img.format == "PNG"
