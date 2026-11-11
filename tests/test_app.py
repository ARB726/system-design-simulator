"""Smoke test: the Streamlit app renders every tab without raising."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_renders_default_scenario():
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    assert len(at.metric) == 6
    assert len(at.tabs) == 5


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
            if key in [w.key for w in at.toggle]:
                at.toggle(key=key).set_value(v)
            elif key in [w.key for w in at.select_slider]:
                at.select_slider(key=key).set_value(v)
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


def test_campaign_locks_and_unlocks_by_stars():
    from sim import progress as pg
    from sim.challenges import challenges
    order = list(challenges())
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.radio(key="mode").set_value("Challenge").run()
    assert not at.exception
    assert [b.disabled for b in at.button if b.key and b.key.startswith("play_")][1:] == [True] * (len(order) - 1)
    prog = pg.empty()
    prog["stars"][order[0]] = 1
    at.session_state["progress"] = prog
    at.run()
    assert not at.exception
    play = {b.key: b.disabled for b in at.button if b.key and b.key.startswith("play_")}
    assert play[f"play_{order[1]}"] is False and play[f"play_{order[2]}"] is True


def test_theme_and_industry_filter_do_not_crash():
    from sim.themes import THEMES
    at = AppTest.from_file(APP, default_timeout=120).run()
    for name in THEMES:
        at.selectbox(key="theme").select(name).run()
        assert not at.exception, name
    for ind in ("E-commerce", "Fintech", "Gaming", "Infrastructure"):
        at.selectbox(key="industry").select(ind).run()
        assert not at.exception, ind
