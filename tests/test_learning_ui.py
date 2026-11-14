"""UI behavior for the learning workflow and paired comparison component."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from sim.history import config_changes

pytestmark = pytest.mark.ui
APP = str(Path(__file__).resolve().parents[1] / "app.py")


def comparison_app():
    from sim.config import Config, Workload, config_from_dict
    from sim.learning_ui import comparison_panel
    cfg = Config(workload=Workload(rps=20, duration_s=1, warmup_s=.1), seed=7)
    candidate = config_from_dict(cfg.to_dict())
    candidate.app.replicas += 1
    comparison_panel(cfg, candidate, "test_pair")


def test_comparison_runs_exports_and_marks_changed_seed_count_stale():
    at = AppTest.from_function(comparison_app, default_timeout=60).run()
    at.button(key="test_pair_run").click().run()
    assert not at.exception
    report = at.session_state["test_pair_result"][1]
    assert len(report["rows"]) == 6 and len(at.dataframe) == 3
    at.select_slider(key="test_pair_count").set_value(5).run()
    assert any("earlier comparison" in warning.value for warning in at.warning)
    at.button(key="test_pair_run").click().run()
    assert not at.exception
    assert len(at.session_state["test_pair_result"][1]["rows"]) == 10


def test_rejected_comparison_clears_pending_and_can_run_again(monkeypatch):
    monkeypatch.setenv("SYSDESIGN_MAX_BATCH_ARRIVALS", "1")
    at = AppTest.from_function(comparison_app, default_timeout=60).run()
    at.button(key="test_pair_run").click().run()
    assert not at.exception and at.error
    assert "test_pair_pending" not in at.session_state
    monkeypatch.setenv("SYSDESIGN_MAX_BATCH_ARRIVALS", "10000")
    at.button(key="test_pair_run").click().run()
    assert not at.exception
    assert len(at.session_state["test_pair_result"][1]["rows"]) == 6


def test_walkthrough_changes_one_setting_and_keeps_original_design():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.button(key="start_walkthrough").click().run()
    assert not at.exception
    assert at.session_state["walkthrough"] == 1
    before = json.loads(at.session_state["committed"])
    at.button(key="guided_change").click().run()
    assert not at.exception
    assert at.session_state["walkthrough"] == 2
    after = json.loads(at.session_state["committed"])
    changes = config_changes(before, after)
    assert len(changes) == 1
    assert before["workload"] == after["workload"] and before["events"] == after["events"]
    assert at.session_state["walkthrough_baseline"]["config"] == before
    assert any(button.key == "guided_compare_run" for button in at.button)
    at.button(key="leave_walkthrough").click().run()
    assert at.session_state["walkthrough"] == 0


def test_policy_controls_wait_for_explicit_run():
    at = AppTest.from_file(APP, default_timeout=120).run()
    before = at.session_state["committed"]
    at.slider(key="w_rps").set_value(100)
    at.slider(key="w_dur").set_value(30)
    at.number_input(key="p_retries").set_value(2)
    at.checkbox(key="p_limit").set_value(True)
    at.number_input(key="p_rate").set_value(20.0)
    at.run()
    assert at.session_state["committed"] == before
    next(button for button in at.button if button.label == "Run simulation").click().run()
    assert not at.exception
    config = json.loads(at.session_state["committed"])
    assert config["policy"]["max_retries"] == 2 and config["policy"]["rate_limit_rps"] == 20
    assert any("amplification" in caption.value for caption in at.caption)
