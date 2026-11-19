import pytest
from fullstack.backend.ai_benchmarks import summarize


def test_quality_latency_tokens_and_explicit_cost_per_success():
    rows = [dict(variant='a', passed=True, latency_ms=10, input_tokens=100, output_tokens=50),
            dict(variant='a', passed=False, latency_ms=30, input_tokens=100, output_tokens=50)]
    result = summarize(rows, prices={'a':{'input_per_million':1, 'output_per_million':2}})['a']
    assert result['pass_rate'] == .5
    assert result['p95_latency_ms'] == 30
    assert result['input_tokens'] == 200
    assert result['cost_per_success_usd'] == pytest.approx(.0004)
    assert summarize(rows)['a']['cost_per_success_usd'] is None


def test_zero_success_and_invalid_usage():
    row = dict(variant='a', passed=False, latency_ms=1, input_tokens=0, output_tokens=0)
    assert summarize([row])['a']['cost_per_success_usd'] is None
    with pytest.raises(ValueError): summarize([row | {'latency_ms':float('nan')}])
    with pytest.raises(ValueError): summarize([row | {'input_tokens':-1}])
    with pytest.raises(ValueError): summarize([row | {'input_tokens':1.5}])


def test_missing_usage_is_unknown_and_never_free():
    row = dict(variant='a', passed=True, latency_ms=1, input_tokens=None, output_tokens=None)
    report = summarize([row], {'a':{'input_per_million':1, 'output_per_million':2}})['a']
    assert report['estimated_cost_usd'] is None
