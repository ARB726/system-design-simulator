"""Aggregate recorded evaluations without assuming model prices or missing usage."""
import math
from collections import defaultdict


def summarize(rows, prices=None):
    groups = defaultdict(list)
    for row in rows:
        if type(row.get('passed')) is not bool:
            raise ValueError('passed must be boolean.')
        for field in ('latency_ms', 'input_tokens', 'output_tokens'):
            value = row.get(field)
            if value is None and field != 'latency_ms':
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid benchmark measurement: ' + field)
            if field != 'latency_ms' and type(value) is not int:
                raise ValueError('Token counts must be integers.')
        groups[row['variant']].append(row)
    report = {}
    for variant, samples in groups.items():
        passed = sum(row['passed'] for row in samples)
        latency = sorted(row['latency_ms'] for row in samples)
        usage_known = all(row.get(k) is not None for row in samples for k in ('input_tokens', 'output_tokens'))
        inputs = sum(row['input_tokens'] for row in samples) if usage_known else None
        outputs = sum(row['output_tokens'] for row in samples) if usage_known else None
        price = (prices or {}).get(variant)
        cost = None
        if price and usage_known:
            rates = [price['input_per_million'], price['output_per_million']]
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in rates):
                raise ValueError('Prices must be finite nonnegative USD rates.')
            cost = (inputs * rates[0] + outputs * rates[1]) / 1000000
        report[variant] = dict(cases=len(samples), passed=passed, pass_rate=passed/len(samples),
            p95_latency_ms=latency[math.ceil(.95*len(latency))-1], input_tokens=inputs,
            output_tokens=outputs, estimated_cost_usd=cost, cost_per_success_usd=cost/passed if cost is not None and passed else None)
    return report
