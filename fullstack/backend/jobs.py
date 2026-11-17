"""Bounded experiments using the original, unchanged Python simulation core."""
import math
import os

from sim.config import config_from_dict, cost_breakdown, monthly_cost
from sim.limits import validate_config


def validate(payload):
    kind = payload.get('kind', 'simulate')
    if kind not in ('simulate', 'grade'):
        raise ValueError('Unknown experiment type.')
    cfg = config_from_dict(payload['config'])
    for value in (cfg.cache.enabled, cfg.cdn.enabled, cfg.queue.enabled, cfg.app_only):
        if not isinstance(value, bool):
            raise ValueError('Component switches must be booleans.')
    os.environ.setdefault('SYSDESIGN_MAX_ARRIVALS', '150000')
    validate_config(cfg)
    if kind == 'grade':
        from sim.challenges import challenges, check_config, default_design
        challenge = challenges().get(payload.get('challenge'))
        if not challenge:
            raise ValueError('Unknown challenge.')
        design = design_from_config(cfg)
        for key, default in default_design(challenge).items():
            allowed = challenge.knobs.get(key, [default])
            if design[key] not in allowed:
                raise ValueError(f'{key} must be one of {allowed}.')
        for check in challenge.checks:
            validate_config(check_config(challenge, design, check))
    return cfg


def design_from_config(cfg):
    return dict(app_replicas=cfg.app.replicas, app_workers=cfg.app.workers, cache=cfg.cache.enabled, cdn=cfg.cdn.enabled, db_workers=cfg.db.workers, shards=cfg.db.shards, read_replicas=cfg.db.read_replicas, queue=cfg.queue.enabled, consumers=cfg.queue.consumers)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, 'item'):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def execute(payload):
    from sim.execution import analyzed_run
    cfg = validate(payload)
    if payload.get('kind') == 'grade':
        from sim.challenges import challenges, run_check, apply_design
        ch = challenges()[payload['challenge']]
        checks = [run_check(ch, design_from_config(cfg), c, keep_result=False) for c in ch.checks]
        design_cost = monthly_cost(apply_design(ch.base, design_from_config(cfg)))
        return clean(dict(type='grade', checks=checks, cost=design_cost, budget=ch.budget, passed=all(c['passed'] for c in checks) and design_cost <= ch.budget))
    res, tl, summary, findings = analyzed_run(cfg)
    # Aggregate charts keep cloud payloads small; detailed per-request traces stay server-side.
    timeline = tl.reset_index().to_dict(orient='records')
    import numpy as np
    counts, edges = np.histogram(res.requests.eff_ms.to_numpy(), bins=24)
    histogram = [{'latency': round(float(edges[i]), 2), 'requests': int(n)} for i, n in enumerate(counts)]
    return clean(dict(type='simulation', summary=summary, timeline=timeline, histogram=histogram, findings=findings, warnings=res.warnings, runtime_s=res.runtime_s, cost=monthly_cost(cfg), cost_breakdown=cost_breakdown(cfg)))
