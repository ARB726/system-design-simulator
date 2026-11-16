"""Interactive optimization must preserve timelines, raw traces and worker contracts."""
import json

import numpy as np
import pandas as pd
import pytest

from sim import execution
from sim.analysis import FAIL_KINDS, diagnose, summarize, timeline
from sim.config import Config, Event, Workload
from sim.engine import run


def reference_timeline(res, bin_s=1.0):
    """Pre-optimization aggregation, kept as an independent regression oracle."""
    idx = pd.Index(np.arange(0, res.cfg.workload.duration_s, bin_s), name="t")
    req = res.requests.assign(bin=(res.requests.t // bin_s) * bin_s)
    g = req.groupby("bin")
    tl = pd.DataFrame(index=idx)
    tl["offered_rps"] = g.size().reindex(idx, fill_value=0) / bin_s
    for status, col in [("ok", "served_rps")] + [(k, f"{k}_rps") for k in FAIL_KINDS]:
        tl[col] = req[req.status == status].groupby("bin").size().reindex(idx, fill_value=0) / bin_s
    q = g.eff_ms.quantile([.5, .95, .99]).unstack().reindex(idx)
    tl["p50"], tl["p95"], tl["p99"] = q[.5], q[.95], q[.99]
    ser = res.series.assign(bin=(res.series.t // bin_s) * bin_s)
    tl = tl.join(ser.drop(columns="t").groupby("bin").mean().reindex(idx))
    if len(res.lag):
        tl["lag_p95_s"] = res.lag.assign(bin=(res.lag.t // bin_s) * bin_s).groupby("bin").lag_s.quantile(.95).reindex(idx)
    return tl


def configuration(name):
    cfg = Config(workload=Workload(rps=100, duration_s=3, warmup_s=.5))
    if name == "overload":
        cfg.app.replicas, cfg.app.workers, cfg.app.max_queue = 1, 1, 1
        cfg.app.latency_ms = 200
        cfg.workload.timeout_ms = 50
    elif name == "async":
        cfg.queue.enabled = True
        cfg.workload.read_ratio = 0
    elif name == "policy":
        cfg.policy.max_retries = 2
        cfg.policy.rate_limit_rps = 20
        cfg.policy.burst = 1
    elif name == "chaos":
        cfg.events = [Event("kill_app", .5, 1, 3), Event("cold_cache", .2, 1, 0)]
    elif name == "empty":
        cfg.workload.rps = .01
    return cfg


@pytest.mark.parametrize("name", ["baseline", "overload", "async", "policy", "chaos"])
@pytest.mark.parametrize("bin_s", [.25, 1.0, 2.0])
def test_timeline_exact_equivalence_and_input_immutability(name, bin_s):
    res = run(configuration(name))
    before = [f.copy(deep=True) for f in (res.requests, res.series, res.lag)]
    expected = reference_timeline(res, bin_s)
    actual = timeline(res, bin_s)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert summarize(res, actual) == summarize(res, expected)
    assert diagnose(res, summarize(res, actual), actual) == diagnose(res, summarize(res, expected), expected)
    for frame, original in zip((res.requests, res.series, res.lag), before):
        pd.testing.assert_frame_equal(frame, original, check_exact=True)


def test_shared_pipeline_timings_do_not_change_outputs(monkeypatch):
    cfg = configuration("policy")
    original = run(cfg)
    monkeypatch.setattr(execution, "run", lambda cfg: original)
    ticks = iter([0., 2., 3., 5., 8.])
    monkeypatch.setattr(execution, "perf_counter", lambda: next(ticks))
    res, tl, summary, findings = execution.analyzed_run(cfg)
    assert res is original
    assert res.timings == dict(simulation_s=2., timeline_s=1., summary_s=2., diagnosis_s=3., pipeline_s=8.)
    pd.testing.assert_frame_equal(tl, reference_timeline(original))
    assert summary == summarize(original, tl)
    assert findings == diagnose(original, summary, tl)


def test_empty_run_has_zero_rates_and_undefined_timeline_percentiles():
    res, tl, summary, _ = execution.analyzed_run(configuration("empty"))
    assert res.requests.empty
    assert (tl[["offered_rps", "served_rps"]] == 0).all().all()
    assert tl[["p50", "p95", "p99"]].isna().all().all()
    assert summary["success_rate"] == 1
    assert summary["p95_ms"] == 0


@pytest.mark.parametrize("name", ["baseline", "async", "policy", "empty"])
def test_worker_json_roundtrip_preserves_traces_and_metrics(name):
    cfg = configuration(name)
    original, tl, summary, findings = execution.analyzed_run(cfg)
    payload = json.loads(json.dumps(execution.execute("simulate", {"config": cfg.to_dict()})))
    restored, actual_tl, actual_summary, actual_findings = execution.decode(payload)
    for old, new in [(original.requests, restored.requests), (original.series, restored.series),
                     (original.lag, restored.lag), (tl, actual_tl)]:
        pd.testing.assert_frame_equal(old, new, check_dtype=False, check_index_type=False)
    assert actual_summary == summary
    assert actual_findings == findings
    assert restored.traffic == original.traffic
    assert all(value >= 0 for value in restored.timings.values())
    assert "serialization_s" in restored.timings and "decode_s" in restored.timings
    payload.pop("timings")  # Results produced by older workers still decode.
    for key in ("requests", "series", "lag", "timeline"):
        payload[key].pop("dtypes")
    legacy, *_ = execution.decode(payload)
    assert set(legacy.timings) == {"decode_s"}


def test_numeric_nulls_and_empty_boolean_columns_survive_json():
    frame = pd.DataFrame({"latency": [float("nan"), float("nan")], "count": [1, 2], "accepted": [True, False]})
    encoded = execution.frame_data(frame)
    assert encoded["data"][0][0] is None
    pd.testing.assert_frame_equal(frame, execution.frame_from(json.loads(json.dumps(encoded))))
    empty = frame.iloc[:0]
    pd.testing.assert_frame_equal(empty, execution.frame_from(json.loads(json.dumps(execution.frame_data(empty)))),
                                  check_index_type=False)
