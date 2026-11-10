"""Smoke test: the Streamlit app renders every tab without raising."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_renders_default_scenario():
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    assert len(at.metric) == 6
    assert len(at.tabs) == 4


def test_switching_scenarios_does_not_crash():
    at = AppTest.from_file(APP, default_timeout=90).run()
    for name in list(at.selectbox[0].options):
        at.selectbox[0].select(name).run()
        assert not at.exception, name


def test_challenge_mode_grades_the_stored_optimum():
    import json
    from sim.challenges import load_optima
    opt = load_optima().get("launch", {}).get("optimum")
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.radio(key="mode").set_value("Challenge").run()
    assert not at.exception
    if opt:
        for k, v in opt.items():
            key = f"k_{k}"
            try:
                at.session_state[key] = v
            except Exception:
                pass
        at.run()
    sub = [b for b in at.button if "Lock prediction" in b.label][0]
    sub.click().run()
    assert not at.exception
    assert any("Score" in m.label for m in at.metric)
    if opt:
        score = [m for m in at.metric if m.label == "Score"][0]
        assert score.value.startswith("100") or int(score.value.split()[0]) >= 70


def test_sandbox_predict_mode_scores_a_prediction():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.toggle(key="predict_on").set_value(True).run()
    assert not at.exception
    [b for b in at.button if "Lock prediction" in b.label][0].click().run()
    assert not at.exception
    assert any(m.label == "Calibration" for m in at.metric)
