"""Generate public, synthetic demo snapshots with the actual simulation engine."""
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fullstack.backend.jobs import execute
from sim.config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rps', type=int, default=120)
    parser.add_argument('--output', type=Path, default=ROOT / 'fullstack/frontend/public/guest-demo.json')
    args = parser.parse_args()
    if not 1 <= args.rps <= 2000:
        parser.error('--rps must be between 1 and 2000')
    experiments = []
    created = int(datetime.now(timezone.utc).timestamp())
    for enabled, name in [(False, 'Baseline: reads reach the database'),
                          (True, 'Candidate: add a read cache')]:
        config = Config()
        config.seed = 7
        config.workload.rps = args.rps
        config.workload.duration_s = 15
        config.workload.warmup_s = 2
        config.db.workers = 2
        config.cache.enabled = enabled
        config.cache.hit_rate = .85
        payload = dict(name=name, config=config.to_dict(), kind='simulate')
        result = execute(payload)
        # Keep the static download small without changing summary measurements.
        result['timeline'] = result['timeline'][::max(1, len(result['timeline']) // 40)]
        experiments.append(dict(id='demo-cache' if enabled else 'demo-baseline',
                                created=created, updated=created, status='completed',
                                payload=payload, result=result))
    output = args.output
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(dict(version=1, seed=7, experiments=experiments),
                                 indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('Generated two synthetic, engine-backed snapshots:', output)


if __name__ == '__main__':
    main()
