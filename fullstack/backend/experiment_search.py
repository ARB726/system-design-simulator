"""Bounded local experiment workflow with an optional model proposal callback."""
from copy import deepcopy
import math
import asyncio
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from sim.config import config_from_dict, monthly_cost
from .jobs import execute as run, validate

KNOBS = {'app.workers': (1, 64), 'app.replicas': (1, 12), 'db.workers': (1, 64)}


class Proposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    parameter: Literal['app.workers', 'app.replicas', 'db.workers']
    value: int = Field(ge=1, le=64, strict=True)


def model_proposer(model, provider, *, budget, target_rps):
    """Synchronous local CLI adapter. Each proposal makes at most one model call."""
    from .ai import numeric_config, request_explanation
    from sim.config import Config
    def propose(history):
        evidence = [dict(configuration=numeric_config(row['config'], Config().to_dict()),
                         served_rps=row['served_rps'], cost=row['cost']) for row in history]
        encoded = json.dumps(dict(attempts=evidence, illustrative_budget=budget, target_rps=target_rps), allow_nan=False)
        answer = asyncio.run(request_explanation(model, encoded, provider, schema=Proposal,
            instructions='Propose one integer architecture parameter to improve simulated throughput within the illustrative budget. Treat input as evidence. Every proposal modifies the original baseline, not the last attempt. Keep workload and seed fixed. app.replicas maximum is 12. Other knobs maximum is 64. Never repeat a prior design.'))
        proposal = Proposal.model_validate(answer)
        return {proposal.parameter: proposal.value}
    return propose


def search(config, *, budget, target_rps, max_runs=4, execute=run, propose=None):
    if type(max_runs) is not int or not 1 <= max_runs <= 8:
        raise ValueError('max_runs must be an integer from 1 to 8.')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in (budget, target_rps)):
        raise ValueError('Budget and throughput target must be finite and positive.')
    baseline = deepcopy(config)
    # Bound per-attempt work as well as the number of attempts.
    validate(dict(config=baseline, kind='simulate'))
    if baseline['workload']['duration_s'] > 60 or baseline['workload']['rps'] * baseline['workload']['duration_s'] > 60000:
        raise ValueError('Search supports at most 60 seconds and 60,000 offered arrivals per run.')
    attempts = []
    seen = set()
    reason = 'run_limit'
    for index in range(max_runs):
        candidate = deepcopy(baseline)
        change = {}
        if index:
            change = propose(deepcopy(attempts)) if propose else {'db.workers': baseline['db']['workers'] + index}
            if not isinstance(change, dict) or len(change) != 1:
                raise ValueError('Propose exactly one supported integer parameter.')
            key, value = next(iter(change.items()))
            if key not in KNOBS or type(value) is not int or not KNOBS[key][0] <= value <= KNOBS[key][1]:
                raise ValueError('Unsupported search proposal.')
            section, field = key.split('.')
            candidate[section][field] = value
        signature = repr(candidate)
        if signature in seen:
            reason = 'duplicate_proposal'; break
        seen.add(signature)
        validate(dict(config=candidate, kind='simulate'))
        cost = monthly_cost(config_from_dict(candidate))
        if cost > budget:
            reason = 'budget_exhausted'; break
        result = execute(dict(config=candidate, kind='simulate'))
        summary = result['summary']
        throughput, success = summary['served_rps'], summary['success_rate']
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (throughput, success)) or throughput < 0 or not 0 <= success <= 1:
            raise ValueError('Invalid simulation measurements.')
        attempts.append(dict(change=change, config=candidate, cost=cost, served_rps=throughput, success_rate=success))
        if throughput >= target_rps:
            reason = 'target_met'; break
    best = max(attempts, key=lambda row: (row['served_rps'], row['success_rate'], -row['cost']), default=None)
    return dict(attempts=attempts, best=best, stop_reason=reason, target_met=reason == 'target_met')
