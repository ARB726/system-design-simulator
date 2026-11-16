"""Traffic illustrations must describe the selected topology without inventing data."""
import pytest

from sim.config import Config
from sim.motion import traffic_scene


def test_scene_uses_configuration_and_escapes_untrusted_names():
    cfg = Config(name='<img src=x onerror="alert(1)">')
    cfg.cdn.enabled = cfg.cache.enabled = cfg.queue.enabled = True
    html = traffic_scene(cfg)
    assert '<img src=x' not in html
    assert '&lt;img' in html
    for label in ('Clients', 'CDN', 'Load balancer', 'App tier', 'Cache', 'Database', 'Write queue'):
        assert label in html
    assert 'Illustrative motion' in html
    assert 'Measured throughput' not in html
    # st.html deliberately sanitizes SVG; request paths must survive HTML-only sanitization.
    assert '<svg' not in html
    assert 'class="lab-packets"' in html


def test_app_only_scene_omits_bypassed_tiers():
    cfg = Config(app_only=True)
    cfg.cdn.enabled = cfg.cache.enabled = cfg.queue.enabled = True
    html = traffic_scene(cfg)
    assert 'App tier' in html
    for label in ('CDN', 'Cache', 'Database', 'Write queue'):
        assert label not in html


@pytest.mark.parametrize('animated', [True, False])
def test_motion_is_optional_and_honors_system_preference(animated):
    html = traffic_scene(Config(), animate=animated)
    assert f'data-motion="{"on" if animated else "off"}"' in html
    assert 'prefers-reduced-motion: reduce' in html
    assert 'animation: none !important' in html
    assert '<script' not in html


def test_scene_displays_measured_health_and_summary():
    summary = {'served_rps': 123.4, 'success_rate': .98,
               'tiers': {'app': {'status': 'critical', 'p90_util': 1.12}}}
    html = traffic_scene(Config(), summary)
    assert '123' in html and '98.0%' in html
    assert '112%' in html and 'Saturated' in html
    assert 'Measured throughput' in html
