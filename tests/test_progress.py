import json

import pytest

from sim import progress as pg

IDS = ["a", "b", "c"]


def score(all_pass=True, eff=1.0, total=100.0, cost=300.0, over=False):
    return dict(all_pass=all_pass, efficiency=eff, total_score=total, cost=cost, over_budget=over)


def test_stars():
    assert pg.stars_for(score(False, 1.0)) == 0
    assert pg.stars_for(score(True, None)) == 1
    assert pg.stars_for(score(True, 0.5)) == 1
    assert pg.stars_for(score(True, 0.85)) == 2
    assert pg.stars_for(score(True, 0.97)) == 3
    assert pg.stars_for(score(True, 1.0, over=True)) == 0


def test_levels_are_monotonic():
    assert pg.level_info(0)["title"] == "Intern"
    assert pg.level_info(100)["level"] == 2
    top = pg.level_info(10_000)
    assert top["next_title"] is None and top["frac"] == 1.0
    assert 0 < pg.level_info(150)["frac"] < 1


def test_campaign_unlocks_in_order():
    p = pg.empty()
    assert pg.unlocked(p, IDS) == ["a"]
    pg.record_attempt(p, "a", {}, 600, score(False, None, 40), IDS)
    assert pg.unlocked(p, IDS) == ["a"]                       # no star yet
    pg.record_attempt(p, "a", {}, 600, score(True, 0.5, 80), IDS)
    assert pg.unlocked(p, IDS) == ["a", "b"]


def test_xp_does_not_farm_on_repeats():
    p = pg.empty()
    pg.record_attempt(p, "a", {}, 600, score(True, 0.85, 80), IDS)
    xp = pg.xp_total(p)
    for _ in range(5):
        pg.record_attempt(p, "a", {}, 600, score(True, 0.85, 80), IDS)
    assert pg.xp_total(p) == xp
    ev = pg.record_attempt(p, "a", {}, 600, score(True, 1.0, 100), IDS)       # genuine improvement
    assert ev["xp_gained"] > 0 and ev["stars_gained"] == 1


def test_badges():
    p = pg.empty()
    ev = pg.record_attempt(p, "writes", dict(queue=True), 900, score(True, 0.9, 90, cost=400), IDS + ["writes"])
    assert {"first_run", "green", "frugal", "queue_whisperer"} <= set(p["badges"])
    assert "first_run" in ev["new_badges"]
    ev = pg.record_attempt(p, "writes", dict(queue=True), 900, score(True, 1.0, 100, cost=400), IDS)
    assert "cost_crusher" in p["badges"] and "first_run" not in ev["new_badges"]   # awarded once
    pg.record_attempt(p, "ledger", dict(shards=2), 1500, score(True, 0.8, 80, cost=1400), IDS)
    assert "shard_sage" in p["badges"]


def test_prediction_badges_and_xp():
    p = pg.empty()
    for _ in range(3):
        pg.record_prediction(p, dict(total=95, parts=dict(bottleneck=40)), IDS)
    assert "napkin_master" in p["badges"] and p["pred"]["xp"] == 30
    for _ in range(2):
        ev = pg.record_prediction(p, dict(total=50, parts=dict(bottleneck=40)), IDS)
    assert "bottleneck_whisperer" in p["badges"]


def test_completionist_and_triple_crown():
    p = pg.empty()
    for c in IDS:
        pg.record_attempt(p, c, {}, 600, score(True, 1.0, 100), IDS)
    assert {"completionist", "triple_crown"} <= set(p["badges"])


def test_save_load_roundtrip():
    p = pg.empty()
    pg.record_attempt(p, "a", dict(queue=True), 600, score(True, 0.9, 85), IDS)
    q = pg.loads(pg.dumps(p), IDS)
    assert q == p


def test_load_sanitizes_hostile_input():
    evil = json.dumps(dict(best={"a": 1e9, "zzz": 50, "b": "nan"}, stars={"a": 99}, attempts={"a": -5},
                           badges=["green", "hacker"], flags=["frugal", "<script>"],
                           pred=dict(n="x", xp=1e12), extra="ignored"))
    q = pg.loads(evil, IDS)
    assert q["best"] == {"a": 100.0, "b": 0.0} and q["stars"] == {"a": 3} and q["attempts"] == {"a": 0}
    assert q["badges"] == ["green"] and q["flags"] == ["frugal"]
    assert q["pred"]["xp"] == 100_000 and q["pred"]["n"] == 0
    with pytest.raises(ValueError):
        pg.loads("not json", IDS)
    with pytest.raises(ValueError):
        pg.loads("[1,2]", IDS)
