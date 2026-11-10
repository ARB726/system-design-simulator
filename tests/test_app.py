"""Smoke test: the Streamlit app renders every tab without raising."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_renders_default_scenario():
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    assert len(at.metric) == 5
    assert len(at.tabs) == 4


def test_switching_scenarios_does_not_crash():
    at = AppTest.from_file(APP, default_timeout=90).run()
    for name in list(at.selectbox[0].options):
        at.selectbox[0].select(name).run()
        assert not at.exception, name
