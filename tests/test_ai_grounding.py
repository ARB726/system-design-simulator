import pytest
from fastapi import HTTPException
from fullstack.backend.ai import grounded_observations


def test_citations_use_server_measurements_and_reject_fabrication():
    answer = dict(observations=[dict(metric='p95_ms', interpretation='Measured latency is 50 ms.')])
    rows = grounded_observations(answer, {'p95_ms':50})
    assert rows[0]['value'] == 50
    assert rows[0]['source'] == 'result.summary.p95_ms'
    answer['observations'][0]['interpretation'] = 'Measured latency is 900 ms.'
    with pytest.raises(HTTPException) as error:
        grounded_observations(answer, {'p95_ms':50})
    assert error.value.status_code == 502


def test_unknown_metric_and_mismatched_units_fail_closed():
    for key, text in [('fake', 'Unknown'), ('p95_ms', 'Latency is 50%')]:
        with pytest.raises(HTTPException):
            grounded_observations({'observations':[dict(metric=key, interpretation=text)]}, {'p95_ms':50})
