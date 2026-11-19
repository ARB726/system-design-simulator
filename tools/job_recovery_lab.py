"""Run a real process-death schedule or benchmark the local durable pipeline."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fullstack.backend import store as storage
from fullstack.backend.jobs import execute
from sim.config import Config


def recovery(directory):
    url = f'sqlite:///{directory / "recovery.db"}'
    db = storage.SQLStore(url)
    try:
        ref = db.create('lab', {})
        # The child commits a claim, then exits without cleanup or publication.
        child = subprocess.run([sys.executable, '-c',
            'import os,sys; from fullstack.backend.store import SQLStore; '
            'db=SQLStore(sys.argv[1]); assert db.claim(); os._exit(23)', url],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        if child.returncode != 23:
            raise RuntimeError(f'Crash injection failed: {child.stderr}')
        old = db.get('lab', ref['id'])
        assert old['status'] == 'running'
        assert db.claim() is None
        # Advance the application clock to the expiry boundary; no 330s sleep.
        with patch.object(storage, 'now', return_value=old['lease_until']):
            assert not db.finish(old, result={'writer': 'expired'})
            replacement = db.claim()
            assert replacement['attempts'] == 2
            assert not db.finish(old, result={'writer': 'stale'})
            assert db.finish(replacement, result={'writer': 'replacement'})
            assert db.claim() is None
            assert not db.finish(old, error='late failure')
        assert db.get('lab', ref['id'])['result'] == {'writer': 'replacement'}
        return dict(mode='recovery', child_exit_code=child.returncode,
                    attempts=replacement['attempts'], active_duplicate_blocked=True,
                    expired_publication_rejected=True, stale_publication_rejected=True,
                    replacement_result_preserved=True, terminal_redelivery_skipped=True,
                    clock='injected expiry boundary; child process actually exited')
    finally:
        db.engine.dispose()


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def benchmark(directory, jobs, workers):
    cfg = Config()
    cfg.workload.rps = 30
    cfg.workload.duration_s = 10
    cfg.workload.warmup_s = 1
    payload = {'kind': 'simulate', 'config': cfg.to_dict()}
    execute(payload)  # Imports and one warmup execution precede timing.
    db = storage.SQLStore(f'sqlite:///{directory / "benchmark.db"}')
    submitted = {}
    try:
        for i in range(jobs):
            ref = db.create(f'load-{i // 2}', payload)
            submitted[ref['id']] = time.perf_counter()
        start, cpu_start = time.perf_counter(), time.process_time()

        def consume():
            samples = []
            while True:
                job = db.claim()
                if job is None:
                    return samples
                claimed = time.perf_counter()
                result = execute(job['payload'])
                if not db.finish(job, result=result):
                    raise RuntimeError('Benchmark lost its publication lease')
                completed = time.perf_counter()
                samples.append(dict(id=job['id'], queue_wait_s=claimed - submitted[job['id']],
                                    service_s=completed - claimed,
                                    completion_s=completed - submitted[job['id']]))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            samples = [sample for batch in pool.map(lambda _: consume(), range(workers)) for sample in batch]
        elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu_start
        assert len(samples) == jobs
        return dict(mode='benchmark', python=platform.python_version(), platform=platform.platform(),
                    adapter='SQLite; threaded consumers; no HTTP or cloud services',
                    jobs=jobs, workers=workers, initial_queue_depth=jobs, workload=payload,
                    elapsed_s=elapsed, process_cpu_s=cpu, completed_jobs_per_s=jobs / elapsed,
                    p95_completion_s=percentile([s['completion_s'] for s in samples], .95),
                    p95_queue_wait_s=percentile([s['queue_wait_s'] for s in samples], .95),
                    p95_service_s=percentile([s['service_s'] for s in samples], .95),
                    samples=samples)
    finally:
        db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['recovery', 'benchmark'])
    parser.add_argument('--jobs', type=int, default=20)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 200 or not 1 <= args.workers <= 8:
        parser.error('Use 1..200 jobs and 1..8 workers.')
    with TemporaryDirectory(prefix='systems-lab-jobs-') as temporary:
        directory = Path(temporary)
        result = recovery(directory) if args.mode == 'recovery' else benchmark(directory, args.jobs, args.workers)
    encoded = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k not in ('samples', 'workload')}, indent=2))
    else:
        print(encoded)


if __name__ == '__main__':
    main()
