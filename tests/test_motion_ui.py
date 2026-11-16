"""The native motion control persists and updates the generated illustration."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.ui


def test_traffic_motion_can_be_paused_and_keeps_measured_results():
    app = Path(__file__).resolve().parents[1] / 'app.py'
    at = AppTest.from_file(str(app), default_timeout=90).run()
    assert not at.exception
    scenes = lambda: [element.proto.body for element in at.get('html')
                      if 'class="lab-scene"' in element.proto.body]
    assert scenes() and 'data-motion="on"' in scenes()[0]
    before = [metric.value for metric in at.metric]
    at.toggle(key='animate_traffic').set_value(False).run()
    assert not at.exception
    assert 'data-motion="off"' in scenes()[0]
    assert [metric.value for metric in at.metric] == before
