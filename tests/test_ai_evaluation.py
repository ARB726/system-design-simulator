import copy
import pytest
pytest.importorskip('fastapi')

from fullstack.backend.ai_evaluation import score, cases


def answer():
    return dict(summary='Observed results.', observations=[dict(metric='p95_ms', interpretation='Tail latency is 50 ms.')], next_experiment='Change workers with seed fixed.', limitations='Simulation only.')


def test_scores_grounded_and_invented_measurements():
    metrics = dict(p95_ms=50, p99_ms=90, served_rps=120, success_rate=.95)
    assert score(answer(), metrics)['passed']
    wrong = answer(); wrong['observations'][0]['interpretation'] = 'Tail latency is 900 ms.'
    assert not score(wrong, metrics)['passed']
    wrong = answer(); wrong['observations'][0]['metric'] = 'invented'
    assert not score(wrong, metrics)['passed']


def test_invalid_shape_and_nonfinite_claim_fail_closed():
    assert not score({}, {})['passed']
    wrong = answer(); wrong['observations'][0]['value'] = float('nan')
    assert not score(wrong, {'p95_ms':50})['passed']


def test_corpus_is_diverse_reproducible_and_independent():
    first = cases(); second = cases()
    assert len(first) == 36
    assert first == second
    assert len({c['id'] for c in first}) == 36
    assert {c['config']['cache']['enabled'] for c in first} == {True, False}
    baseline = copy.deepcopy(second)
    first[0]['config']['app']['workers'] = 999
    assert second == baseline
