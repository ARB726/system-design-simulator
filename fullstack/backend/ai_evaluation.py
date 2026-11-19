"""Offline, deterministic checks; passing does not prove semantic correctness."""
import math
import re

from .ai import Explanation

PROMPT_VERSION = 'evidence-v1'


def cases():
    """36 synthetic configurations, never production or personal data."""
    from sim.config import Config
    result = []
    for rps in (60, 180, 540):
        for workers in (1, 4, 16):
            for cache in (False, True):
                for seed in (7, 19):
                    cfg = Config().to_dict()
                    cfg['workload'].update(rps=rps, duration_s=4, warmup_s=1)
                    cfg['db']['workers'] = workers
                    cfg['cache']['enabled'] = cache
                    cfg['seed'] = seed
                    result.append(dict(id=f'r{rps}-db{workers}-cache{int(cache)}-s{seed}', config=cfg))
    return result


def score(answer, metrics):
    errors = []
    try:
        Explanation.model_validate(answer)
    except (ValueError, TypeError):
        return dict(passed=False, errors=['schema'])
    for observation in answer['observations']:
        key = observation['metric']
        actual = metrics.get(key)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
            errors.append('missing_metric:' + key)
            continue
        # Only score numbers explicitly attached to a supported measurement unit.
        # Other prose and causal claims require human review.
        for number, unit in re.findall(r'(-?\d+(?:\.\d+)?)\s*(ms|req/s|%)', observation['interpretation']):
            expected_unit = 'ms' if key.endswith('_ms') else 'req/s' if key == 'served_rps' else '%'
            expected = actual * 100 if unit == '%' else actual
            if unit != expected_unit or not math.isclose(float(number), expected, rel_tol=.005, abs_tol=.01):
                errors.append('unsupported_value:' + key)
    return dict(passed=not errors, errors=errors)
