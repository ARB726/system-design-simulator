"""Deterministic boundary and failure-path regressions."""
import json
import math
import subprocess
from types import SimpleNamespace
import pytest
from sim import progress as pg
from sim import native
from sim.predict import Prediction, bucket_of, score_prediction, truth_from_summary
from sim.theory import erlang_c, mmc_mean_wait, mmc_mean_response


def summary():
    return {"tiers": {"app": {"mean_util": .6}, "cache": {"mean_util": .1}}, "p95_ms": 100}


def test_latency_exactly_50_enters_second_bucket():
    assert bucket_of(50) == 1


def test_latency_exactly_150_enters_third_bucket():
    assert bucket_of(150) == 2


def test_latency_exactly_500_enters_last_bucket():
    assert bucket_of(500) == 3


def test_empty_tiers_have_no_bottleneck():
    result = truth_from_summary({"tiers": {}, "p95_ms": 0})
    assert result["bottleneck"] is None and result["accepted"] == []


def test_tier_outside_tie_band_is_not_accepted():
    s = summary()
    s["tiers"]["cache"]["mean_util"] = .54
    assert truth_from_summary(s)["accepted"] == ["app"]


def test_perfect_prediction_has_no_correction_notes():
    result = score_prediction(Prediction("app", .6, 1, True), summary(), True)
    assert result["total"] == 100 and result["notes"] == []


def test_adjacent_latency_bucket_receives_half_credit():
    assert score_prediction(Prediction("app", .6, 2, True), summary(), True)["parts"]["p95"] == 10


def test_distant_latency_bucket_receives_no_credit():
    assert score_prediction(Prediction("app", .6, 3, True), summary(), True)["parts"]["p95"] == 0


def test_large_utilization_error_never_scores_negative():
    assert score_prediction(Prediction("app", 5, 1, True), summary(), True)["parts"]["util"] == 0


def test_failed_design_prediction_explains_actual_failure():
    result = score_prediction(Prediction("cache", .1, 3, True), summary(), False)
    assert any("did not hold" in note for note in result["notes"])


def test_held_design_prediction_explains_actual_success():
    result = score_prediction(Prediction("app", .6, 1, False), summary(), True)
    assert any("held" in note for note in result["notes"])


def test_unknown_tier_is_explained_without_key_error():
    result = score_prediction(Prediction("custom", .6, 1, True), summary(), True)
    assert result["parts"]["bottleneck"] == 0 and "custom" in result["notes"][0]


def test_failed_score_awards_no_stars():
    assert pg.stars_for({"all_pass": False, "efficiency": 1}) == 0


def test_over_budget_score_awards_no_stars():
    assert pg.stars_for({"all_pass": True, "over_budget": True, "efficiency": 1}) == 0


def test_unknown_optimum_awards_one_star():
    assert pg.stars_for({"all_pass": True, "efficiency": None}) == 1


def test_exact_two_star_threshold():
    assert pg.stars_for({"all_pass": True, "efficiency": .8}) == 2


def test_exact_three_star_threshold():
    assert pg.stars_for({"all_pass": True, "efficiency": .97}) == 3


def test_initial_level_starts_with_zero_progress():
    info = pg.level_info(0)
    assert info["level"] == 1 and info["frac"] == 0 and info["to_next"] == 100


def test_exact_level_boundary_promotes():
    assert pg.level_info(100)["level"] == 2 and pg.level_info(100)["frac"] == 0


def test_max_level_has_no_next_level():
    info = pg.level_info(9999)
    assert info["next_title"] is None and info["frac"] == 1 and info["to_next"] == 0


def test_empty_campaign_unlocks_nothing():
    assert pg.unlocked(pg.empty(), []) == []


def test_new_campaign_only_unlocks_first_challenge():
    assert pg.unlocked(pg.empty(), ["a", "b", "c"]) == ["a"]


def test_progress_save_rejects_non_object_json():
    with pytest.raises(ValueError, match="progress file"):
        pg.loads("[]")


def test_progress_save_rejects_broken_json():
    with pytest.raises(ValueError, match="progress file"):
        pg.loads("{broken")


def test_progress_import_filters_unknown_challenges():
    assert pg.loads('{"stars":{"a":2,"unknown":3}}', ["a"])["stars"] == {"a": 2}


def test_progress_import_clamps_high_and_negative_values():
    result = pg.loads('{"best":{"a":900},"stars":{"a":-1},"attempts":{"a":999999}}')
    assert result["best"]["a"] == 100 and result["stars"]["a"] == 0 and result["attempts"]["a"] == 10000


def test_progress_import_ignores_invalid_numbers():
    assert pg.loads('{"best":{"a":"oops","b":null}}')["best"] == {"a": 0, "b": 0}


def test_progress_import_sanitizes_nan():
    assert pg.loads('{"best":{"a":NaN}}')["best"]["a"] == 0


def test_progress_import_deduplicates_flags():
    assert pg.loads('{"flags":["queue","queue","unknown"]}')["flags"] == ["queue"]


def test_progress_import_discards_unknown_badges():
    assert pg.loads('{"badges":["first_run","invented"]}')["badges"] == ["first_run"]


def test_progress_roundtrip_preserves_valid_state():
    p = pg.empty()
    p["best"]["a"] = 42
    assert pg.loads(pg.dumps(p)) == p


def test_zero_arrival_rate_has_no_wait():
    assert mmc_mean_wait(0, 50, 4) == 0


def test_zero_arrival_rate_response_is_service_time():
    assert mmc_mean_response(0, 50, 4) == pytest.approx(.02)


def test_saturation_has_infinite_wait():
    assert math.isinf(mmc_mean_wait(200, 50, 4))


def test_overload_has_wait_probability_one():
    assert erlang_c(4, 5) == 1


def test_single_server_matches_closed_form():
    assert mmc_mean_response(30, 50, 1) == pytest.approx(1 / 20)


def test_more_servers_reduce_wait():
    assert mmc_mean_wait(80, 50, 4) < mmc_mean_wait(80, 50, 2)


def test_missing_native_binary_has_actionable_error(monkeypatch):
    monkeypatch.setattr(native, "available", lambda: False)
    with pytest.raises(ValueError, match="not installed"):
        native.simulate_mmc(4, 100, 50)


def test_native_timeout_is_wrapped_with_cause(monkeypatch):
    monkeypatch.setattr(native, "available", lambda: True)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("mmc", 30)
    monkeypatch.setattr(native.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="run failed") as error:
        native.simulate_mmc(4, 100, 50)
    assert isinstance(error.value.__cause__, subprocess.TimeoutExpired)


def test_native_invalid_json_is_wrapped(monkeypatch):
    monkeypatch.setattr(native, "available", lambda: True)
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="bad json"))
    with pytest.raises(ValueError, match="run failed"):
        native.simulate_mmc(4, 100, 50)


def test_native_os_failure_is_wrapped(monkeypatch):
    monkeypatch.setattr(native, "available", lambda: True)
    def fail(*args, **kwargs):
        raise OSError("missing runtime library")
    monkeypatch.setattr(native.subprocess, "run", fail)
    with pytest.raises(ValueError, match="run failed"):
        native.simulate_mmc(4, 100, 50)


def test_native_success_parses_results_and_sets_timeout(monkeypatch):
    monkeypatch.setattr(native, "available", lambda: True)
    calls = []
    def success(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=json.dumps({"requests": 20, "mean_wait_s": .1}))
    monkeypatch.setattr(native.subprocess, "run", success)
    assert native.simulate_mmc(4, 100, 50)["requests"] == 20
    assert calls[0][1]["timeout"] == 30 and calls[0][1]["check"] is True


def test_native_availability_checks_actual_file(monkeypatch, tmp_path):
    executable = tmp_path / "kernel"
    monkeypatch.setenv("SYSDESIGN_NATIVE_BINARY", str(executable))
    assert not native.available()
    executable.write_text("binary placeholder")
    assert native.available()


def test_progress_import_ignores_non_mapping_prediction():
    assert pg.loads('{"pred":[]}')["pred"] == pg.empty()["pred"]


def test_progress_import_ignores_non_list_flags():
    assert pg.loads('{"flags":{}}')["flags"] == []


def test_progress_import_ignores_non_list_badges():
    assert pg.loads('{"badges":null}')["badges"] == []


def test_progress_import_ignores_non_mapping_challenge_state():
    result = pg.loads('{"best":[],"stars":null,"attempts":"invalid"}')
    assert result["best"] == result["stars"] == result["attempts"] == {}
