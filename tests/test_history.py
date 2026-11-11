from copy import deepcopy

import pytest

from sim.config import Config
from sim.history import RunStore, compare_runs


LIBRARY = "a" * 32
OTHER = "b" * 32


def summary():
    return dict(served_rps=500.0, success_rate=0.99, p95_ms=200.0, p99_ms=400.0,
                bottleneck="app", queue=None)


def test_runs_survive_reopening_and_are_scoped_to_library(tmp_path):
    path = tmp_path / "nested" / "runs.sqlite3"
    record = RunStore(path).save(LIBRARY, "Baseline", Config(), summary(), [])
    reopened = RunStore(path)
    assert reopened.list(LIBRARY) == [record]
    assert reopened.list(OTHER) == []
    reopened.delete(OTHER, record["id"])
    assert reopened.list(LIBRARY) == [record]
    reopened.delete(LIBRARY, record["id"])
    assert reopened.list(LIBRARY) == []


def test_names_validation_and_snapshots_are_independent(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    cfg, summ = Config(), summary()
    first = store.save(LIBRARY, "Same name", cfg, summ, [])
    cfg.app.replicas = 8
    summ["p95_ms"] = 50
    second = store.save(LIBRARY, "Same name", cfg, summ, [])
    records = store.list(LIBRARY)
    assert len(records) == 2
    assert first["id"] != second["id"]
    assert records[1]["config"]["app"]["replicas"] == 3
    assert records[1]["summary"]["p95_ms"] == 200
    for name in ("", "   ", "x" * 81):
        with pytest.raises(ValueError):
            store.save(LIBRARY, name, cfg, summ, [])
    with pytest.raises(ValueError, match="library"):
        store.list("../../elsewhere")
    summ["p95_ms"] = float("nan")
    with pytest.raises(ValueError):
        store.save(LIBRARY, "Invalid", cfg, summ, [])
    assert len(store.list(LIBRARY)) == 2


def test_library_capacity_does_not_overwrite_existing_runs(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    for i in range(100):
        store.save(LIBRARY, str(i), Config(), summary(), [])
    with pytest.raises(ValueError, match="100 runs"):
        store.save(LIBRARY, "One more", Config(), summary(), [])
    assert len(store.list(LIBRARY)) == 100


def test_comparison_explains_tradeoffs_and_conditions(tmp_path):
    base = RunStore(tmp_path / "runs.sqlite3").save(LIBRARY, "Base", Config(), summary(), [])
    candidate = deepcopy(base)
    candidate["cost"] += 100
    candidate["summary"].update(p95_ms=100, success_rate=1, bottleneck="db_primary")
    candidate["config"]["app"]["replicas"] = 6
    result = compare_runs(base, candidate)
    metrics = {m["Metric"]: m for m in result["metrics"]}
    assert metrics["p95 latency"]["Change"] == -100
    assert metrics["p95 latency"]["Direction"] == "Better"
    assert metrics["Monthly cost"]["Direction"] == "Worse"
    assert metrics["Success rate"]["Change"] == pytest.approx(1.0)
    assert len(result["warnings"]) == 1  # stochastic caveat, same experiment conditions
    assert any("moved from App tier to DB primary" in n for n in result["notes"])
    assert result["changes"][0]["Setting"] == "app.replicas"
    candidate["config"]["workload"]["rps"] += 100
    candidate["config"]["seed"] += 1
    candidate["config"]["events"] = [dict(kind="traffic_spike", start_s=5, duration_s=10, magnitude=2)]
    result = compare_runs(base, candidate)
    assert "workload, events, seed" in result["warnings"][0]


def test_comparison_handles_zero_baseline_and_async_writes(tmp_path):
    base = RunStore(tmp_path / "runs.sqlite3").save(LIBRARY, "Base", Config(), summary(), [])
    base["cost"] = 0
    base["summary"]["served_rps"] = 0
    candidate = deepcopy(base)
    candidate["summary"]["queue"] = dict(lag_p95_s=2.5, end_depth=40)
    candidate["cost"] = 30
    result = compare_runs(base, candidate)
    assert any("2.50 s" in n and "acknowledgement" in n for n in result["notes"])
    assert result["metrics"][-1]["Change"] == 30


def test_saved_run_ui_saves_completed_config_restores_and_deletes(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("SYSDESIGN_RUN_DB", str(path))
    app = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app, default_timeout=120).run()
    assert not at.exception
    library = at.query_params["library"]
    # Change the pending config, but deliberately do not run it.
    original_replicas = at.slider(key="a_rep").value
    at.slider(key="a_rep").set_value(original_replicas + 1).run()
    at.text_input(key="saved_run_name").set_value("Completed baseline")
    [b for b in at.button if b.label == "Save run"][0].click().run()
    assert not at.exception
    saved = RunStore(path).list(library)
    assert len(saved) == 1
    assert saved[0]["config"]["app"]["replicas"] == original_replicas

    # Add a candidate and exercise the comparison view without another expensive run.
    from sim.config import config_from_dict
    cfg = config_from_dict(saved[0]["config"])
    cfg.app.replicas = original_replicas + 2
    candidate = RunStore(path).save(library, "Candidate", cfg, saved[0]["summary"], [])
    at.run()
    assert not at.exception
    assert at.selectbox(key="compare_baseline").value != at.selectbox(key="compare_candidate").value
    assert any("app.replicas" in str(t.value) for t in at.dataframe)
    # A new browser session with the bookmarked key reopens the same library.
    fresh = AppTest.from_file(app, default_timeout=120)
    fresh.query_params["library"] = library
    fresh.run()
    assert not fresh.exception
    fresh.selectbox(key="library_run").set_value(saved[0]["id"]).run()
    fresh.button(key="restore_run").click().run()
    assert not fresh.exception
    assert fresh.slider(key="a_rep").value == original_replicas
    fresh.selectbox(key="library_run").set_value(candidate["id"]).run()
    fresh.checkbox(key=f"delete_confirm_{candidate['id']}").check().run()
    fresh.button(key="delete_run").click().run()
    assert not fresh.exception
    assert len(RunStore(path).list(library)) == 1
